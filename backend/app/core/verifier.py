"""Independent verifier (Layer 4 of the blueprint).

Re-checks every hard constraint on a solved Timetable WITHOUT touching the
CP-SAT model. The goal: catch any bug in the constraint encoding.
"""
from __future__ import annotations

from collections import defaultdict

from ..models.domain import (
    CourseType,
    Timetable,
    TimetableRequest,
    VerificationReport,
    Violation,
)


def _to_minutes(hhmm: str) -> int | None:
    try:
        hh, mm = [int(x) for x in hhmm.split(":")]
    except Exception:
        return None
    return hh * 60 + mm


def _blocked_slots(req: TimetableRequest) -> set[int]:
    timings = req.time_config.slot_timings
    if not timings:
        return set()

    breaks: list[tuple[int, int]] = []
    if 0 < req.time_config.tea_break.after_slot <= len(timings):
        end_m = _to_minutes(timings[req.time_config.tea_break.after_slot - 1].end)
        if end_m is not None:
            breaks.append((end_m, end_m + req.time_config.tea_break.duration_min))
    if 0 < req.time_config.lunch_break.after_slot <= len(timings):
        end_m = _to_minutes(timings[req.time_config.lunch_break.after_slot - 1].end)
        if end_m is not None:
            breaks.append((end_m, end_m + req.time_config.lunch_break.duration_min))

    blocked: set[int] = set()
    for slot_idx, timing in enumerate(timings, start=1):
        start_m = _to_minutes(timing.start)
        end_m = _to_minutes(timing.end)
        if start_m is None or end_m is None:
            continue
        for break_start, break_end in breaks:
            if start_m < break_end and end_m > break_start:
                blocked.add(slot_idx)
                break
    return blocked


def verify(req: TimetableRequest, tt: Timetable) -> VerificationReport:
    violations: list[Violation] = []
    courses_by_code = {c.code: c for c in req.courses}
    tc = req.time_config
    break_after = {tc.tea_break.after_slot, tc.lunch_break.after_slot}
    blocked_slots = _blocked_slots(req)
    elective_codes = {
        opt.course_code for block in req.elective_blocks for opt in block.options
    }
    combined_codes = {
        course.code for course in req.courses if course.combined_sections
    } | elective_codes

    pair_index: dict[str, str] = {}
    for c in req.courses:
        if c.type == CourseType.LAB and c.pair_course:
            pair_index[c.code] = c.pair_course

    # H2 section no-clash
    cell: dict[tuple[str, str, int], list] = defaultdict(list)
    for c in tt.classes:
        cell[(c.section_id, c.day, c.slot)].append(c)
    for (s, d, t), items in cell.items():
        if len(items) <= 1:
            continue
        if all(it.course_code == items[0].course_code for it in items):
            continue
        codes = {it.course_code for it in items if it.is_lab}
        if len(codes) == 2:
            a, b = list(codes)
            if pair_index.get(a) == b and pair_index.get(b) == a:
                continue
        batches = {it.batch_id for it in items}
        labs = all(it.is_lab for it in items)
        if labs and None not in batches and len(batches) == len(items):
            continue
        violations.append(
            Violation(
                code="H2",
                message=f"Section {s} double-booked at {d} slot {t}",
                details={"items": [it.model_dump() for it in items]},
            )
        )

    # H1 faculty no-clash
    fac_cell: dict[tuple[str, str, int], list] = defaultdict(list)
    for c in tt.classes:
        if c.faculty_id:
            fac_cell[(c.faculty_id, c.day, c.slot)].append(c)
    for (fid, d, t), items in fac_cell.items():
        if len(items) <= 1:
            continue
        codes = {it.course_code for it in items}
        if len(codes) == 1 and next(iter(codes)) in combined_codes:
            continue
        violations.append(
            Violation(
                code="H1",
                message=f"Faculty {fid} double-booked at {d} slot {t}",
                details={"items": [it.model_dump() for it in items]},
            )
        )

    # H6 lab-room contention
    room_cell: dict[tuple[str, str, int], list] = defaultdict(list)
    for c in tt.classes:
        if c.room:
            room_cell[(c.room, c.day, c.slot)].append(c)
    for (r, d, t), items in room_cell.items():
        sections = {it.section_id for it in items}
        if len(sections) > 1:
            violations.append(
                Violation(
                    code="H6",
                    message=f"Lab room {r} used by multiple sections at {d} slot {t}",
                    details={"sections": list(sections)},
                )
            )

    # H3 credit satisfaction (per section, per course)
    needed_by_sec_course: dict[tuple[str, str], int] = {}
    for fac in req.faculty:
        for a in fac.assignments:
            if a.course_code not in courses_by_code:
                continue
            course = courses_by_code[a.course_code]
            if course.code in elective_codes:
                continue
            needed_by_sec_course[(a.section_id, course.code)] = (
                course.effective_weekly_slots()
            )

    placed: dict[tuple[str, str], set[tuple[str, int]]] = defaultdict(set)
    for c in tt.classes:
        placed[(c.section_id, c.course_code)].add((c.day, c.slot))

    for (sec, code), need in needed_by_sec_course.items():
        got = len(placed.get((sec, code), set()))
        if got != need:
            violations.append(
                Violation(
                    code="H3",
                    message=f"Section {sec} course {code}: needed {need} slots, got {got}",
                )
            )

    # H4 lab consecutiveness + no spanning break
    lab_groups: dict[tuple[str, str, str, str], set[int]] = defaultdict(set)
    for c in tt.classes:
        if c.is_lab:
            batch_key = c.batch_id or "__section__"
            lab_groups[(c.section_id, c.course_code, c.day, batch_key)].add(c.slot)
    for (s, code, d, _batch), slot_set in lab_groups.items():
        slots = sorted(slot_set)
        if len(slots) % 2 != 0:
            violations.append(
                Violation(
                    code="H4",
                    message=f"Lab {code} section {s} {d}: odd slot count {slots}",
                )
            )
            continue
        for i in range(0, len(slots), 2):
            a, b = slots[i], slots[i + 1]
            if b - a != 1:
                violations.append(
                    Violation(
                        code="H4",
                        message=f"Lab {code} section {s} {d}: non-consecutive slots {a},{b}",
                    )
                )
            if a in break_after:
                violations.append(
                    Violation(
                        code="H4",
                        message=f"Lab {code} section {s} {d}: spans a break between {a} and {b}",
                    )
                )

    # H7 elective block sync: all participating sections share the same cells,
    # and option assignment matches the section grouping when available.
    for block in req.elective_blocks:
        sec_set = set(block.applies_to_sections)
        option_codes = {opt.course_code for opt in block.options}
        per_sec: dict[str, set[tuple[str, int]]] = defaultdict(set)
        per_sec_codes: dict[str, set[str]] = defaultdict(set)
        for c in tt.classes:
            if c.section_id in sec_set and c.course_code in option_codes:
                per_sec[c.section_id].add((c.day, c.slot))
                per_sec_codes[c.section_id].add(c.course_code)
        expected_cells = set(block.locked_global_slots or [])
        if not per_sec and not expected_cells:
            continue
        canonical = expected_cells or next(iter(per_sec.values()))
        for sec in sec_set:
            cells = per_sec.get(sec, set())
            if cells != canonical:
                violations.append(
                    Violation(
                        code="H7",
                        message=f"Elective {block.name} not synchronized for section {sec}",
                        details={"expected": sorted(canonical), "got": sorted(cells)},
                    )
                )
        expected_option_by_section: dict[str, str] = {}
        for opt in block.options:
            for sec in opt.assigned_sections:
                if sec in sec_set:
                    expected_option_by_section[sec] = opt.course_code
        for sec, option_code in expected_option_by_section.items():
            codes = per_sec_codes.get(sec, set())
            if codes != {option_code}:
                violations.append(
                    Violation(
                        code="H7",
                        message=f"Elective {block.name} section {sec} assigned wrong option",
                        details={"expected": option_code, "got": sorted(codes)},
                    )
                )

    # H9 break sanctity
    for c in tt.classes:
        if c.slot in blocked_slots:
            violations.append(
                Violation(
                    code="H9",
                    message=f"Class {c.course_code} for section {c.section_id} placed in blocked break slot {c.day}/{c.slot}",
                )
            )

    # H10 saturday rules
    sat_inactive = req.time_config.saturday_rules.inactive_weeks
    if sat_inactive:
        for ls in tc.saturday_rules.locked_slots:
            applies = ls.applies_to_sections or [s.id for s in req.sections]
            for sec in applies:
                found = any(
                    c.section_id == sec
                    and c.day == ls.day
                    and c.slot == ls.slot
                    and (c.label == ls.label or c.course_code == ls.label)
                    for c in tt.classes
                )
                if not found:
                    violations.append(
                        Violation(
                            code="H10",
                            message=f"Saturday lock {ls.label} missing for section {sec} at {ls.day}/{ls.slot}",
                        )
                    )

    # H11 hard-locked blocks
    for course in req.courses:
        if not (course.locked_day and course.locked_slots):
            continue
        for sec in req.sections:
            for t in course.locked_slots:
                ok = any(
                    c.section_id == sec.id
                    and c.day == course.locked_day
                    and c.slot == t
                    and c.course_code == course.code
                    for c in tt.classes
                )
                if not ok:
                    violations.append(
                        Violation(
                            code="H11",
                            message=f"Locked block {course.code} missing for section {sec.id} at {course.locked_day}/{t}",
                        )
                    )

    # H12 faculty availability
    for fac in req.faculty:
        unav = {(u.day, u.slot) for u in fac.unavailable_slots}
        for c in tt.classes:
            if c.faculty_id == fac.id and (c.day, c.slot) in unav:
                violations.append(
                    Violation(
                        code="H12",
                        message=f"Faculty {fac.id} scheduled during declared unavailability at {c.day}/{c.slot}",
                    )
                )

    soft_score = _soft_score(req, tt)
    return VerificationReport(
        ok=len(violations) == 0, violations=violations, soft_score=soft_score
    )


def _soft_score(req: TimetableRequest, tt: Timetable) -> int:
    """Rough lowest-waste quality score, 0..100."""
    if not tt.classes:
        return 0
    tc = req.time_config
    blocked_slots = _blocked_slots(req)
    usable_slots = [s for s in range(1, tc.slots_per_day + 1) if s not in blocked_slots]
    weekday_days = [d for d in tc.days if d != "SAT"] or list(tc.days)
    post_lunch = tc.lunch_break.after_slot + 1
    cls_by_sec_day = defaultdict(list)
    sec_slots: dict[tuple[str, str], set[int]] = defaultdict(set)
    fac_slots: dict[tuple[str, str], set[int]] = defaultdict(set)
    room_slots: dict[tuple[str, str], set[int]] = defaultdict(set)
    for c in tt.classes:
        cls_by_sec_day[(c.section_id, c.day)].append(c)
        if c.slot in blocked_slots:
            continue
        sec_slots[(c.section_id, c.day)].add(c.slot)
        if c.faculty_id:
            fac_slots[(c.faculty_id, c.day)].add(c.slot)
        if c.room:
            room_slots[(c.room, c.day)].add(c.slot)

    section_ids = {s.id for s in req.sections} or {c.section_id for c in tt.classes}
    n_sections = max(len(section_ids), 1)
    n_days = max(len(weekday_days), 1)
    cells_max = n_sections * n_days

    dup_total = 0
    for (sec, d), items in cls_by_sec_day.items():
        seen: dict[str, int] = defaultdict(int)
        for c in items:
            if not c.is_lab:
                seen[c.course_code] += 1
        for _code, n in seen.items():
            if n > 1:
                dup_total += n - 1
    dup_score = 100 * (1 - min(1.0, dup_total / max(cells_max * 0.3, 1)))

    high_codes = {
        c.code for c in req.courses
        if c.credits >= 3 and c.type == CourseType.THEORY
    }
    hc_overflow = 0
    for (sec, d), items in cls_by_sec_day.items():
        hc = sum(1 for it in items if it.course_code in high_codes and not it.is_lab)
        if hc > 2:
            hc_overflow += hc - 2
    hc_score = 100 * (1 - min(1.0, hc_overflow / max(cells_max * 0.4, 1)))

    def idle_gaps(slots: set[int]) -> int:
        if len(slots) < 2:
            return 0
        first = min(slots)
        last = max(slots)
        return sum(1 for slot in usable_slots if first < slot < last and slot not in slots)

    student_gaps = sum(
        idle_gaps(sec_slots[(sec_id, day)])
        for sec_id in section_ids
        for day in weekday_days
    )
    gap_capacity = max(n_sections * n_days * max(len(usable_slots) - 2, 1), 1)
    student_gap_score = 100 * (1 - min(1.0, student_gaps / gap_capacity))

    common_gaps = 0
    for day in weekday_days:
        used = {
            slot
            for slot in usable_slots
            if any(slot in sec_slots[(sec_id, day)] for sec_id in section_ids)
        }
        if len(used) < 2:
            continue
        first = min(used)
        last = max(used)
        common_gaps += sum(
            2 if slot == post_lunch else 1
            for slot in usable_slots
            if first < slot < last and slot not in used
        )
    common_gap_score = 100 * (1 - min(1.0, common_gaps / max(n_days * 3, 1)))

    active_faculty = {c.faculty_id for c in tt.classes if c.faculty_id}
    faculty_waste = 0
    for fac_id in active_faculty:
        loads = []
        for day in weekday_days:
            slots = fac_slots[(fac_id, day)]
            loads.append(len(slots))
            faculty_waste += idle_gaps(slots)
        if loads:
            faculty_waste += max(loads) - min(loads)
    faculty_score = 100 * (
        1 - min(1.0, faculty_waste / max(len(active_faculty) * n_days * 2, 1))
    )

    active_rooms = {c.room for c in tt.classes if c.room}
    room_waste = 0
    for room in active_rooms:
        loads = []
        for day in weekday_days:
            slots = room_slots[(room, day)]
            loads.append(len(slots))
            room_waste += idle_gaps(slots)
        if loads:
            room_waste += max(loads) - min(loads)
    room_score = 100 * (
        1 - min(1.0, room_waste / max(len(active_rooms) * n_days * 2, 1))
    )

    late_units = sum(
        max(0, c.slot - post_lunch)
        for c in tt.classes
        if c.day in weekday_days and c.slot > post_lunch and not c.is_lab
    )
    late_score = 100 * (1 - min(1.0, late_units / max(cells_max * 1.5, 1)))

    final = round(
        0.15 * dup_score
        + 0.15 * hc_score
        + 0.30 * student_gap_score
        + 0.15 * common_gap_score
        + 0.15 * faculty_score
        + 0.05 * room_score
        + 0.05 * late_score
    )
    return max(0, min(100, int(final)))
