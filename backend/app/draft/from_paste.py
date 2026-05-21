"""Build a TimetableRequest from a small form skeleton + a pasted course table.

The paste format is intentionally forgiving and spreadsheet-friendly:

  # comments start with '#'
  CODE, NAME, CREDITS, TYPE, FACULTY1; FACULTY2; ...

  Types:
    theory
    lab                       (solo lab)
    lab pair=BCSL404          (paired with another lab - H5 batch swap)
    activity                  (flex activity, placed by solver)
    activity locked=FRI:5,6,7 (locked to a specific day + slot list)

  Faculty list (after the 4th comma):
    Dr A; Dr B; ...             (one per section when the count matches sections)
    Dr A; Dr B; Dr C            (otherwise teacher pool, auto-balanced)
    same-as=BAI402              (re-use the faculty assigned to BAI402)
    auto                        (auto-generate "<Code> Faculty X" placeholders)
    x6                          (generate 6 placeholders)

  Elective blocks: separate paste, one line per block:
    BLOCK_ID | NAME | weekly_slots | locked: MON-2,TUE-3,THU-3,FRI-3 | OPT1=fac1,fac2,fac3 | OPT2=fac1,fac2

  Saturday locks: pre-configured by the wizard, but the API also accepts a
  list of {day, slots, label} for arbitrary day-wide locks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ..models.domain import (
    Assignment,
    Batch,
    BreakConfig,
    Course,
    CourseType,
    ElectiveBlock,
    ElectiveOption,
    Faculty,
    LockedSlot,
    SaturdayRules,
    Section,
    TimeConfig,
    Timing,
    TimetableRequest,
)
from .pool_assign import (
    AssignmentTarget,
    PoolAssignmentError,
    assign_targets,
    even_groups,
    slots_tuple,
)

DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]


# ---------------------------------------------------------------------------
# Skeleton
# ---------------------------------------------------------------------------
@dataclass
class Skeleton:
    days: list[str]
    slots_per_day: int
    slot_timings: list[tuple[str, str]]
    tea_after_slot: int
    tea_minutes: int
    lunch_after_slot: int
    lunch_minutes: int
    section_ids: list[str]
    batches_per_section: int
    classroom_by_section: dict[str, str]
    inactive_sat_weeks: list[int]
    sat_locks: list[tuple[str, list[int], list[str] | None]]  # (label, slots, sections)
    semester: int = 4


def default_skeleton(num_sections: int = 6) -> Skeleton:
    section_ids = [chr(ord("A") + i) for i in range(num_sections)]
    return Skeleton(
        days=list(DAYS),
        slots_per_day=7,
        slot_timings=[
            ("08:30", "09:25"),
            ("09:25", "10:20"),
            ("10:40", "11:35"),
            ("11:35", "12:30"),
            ("13:25", "14:20"),
            ("14:20", "15:15"),
            ("15:15", "16:10"),
        ],
        tea_after_slot=2,
        tea_minutes=20,
        lunch_after_slot=4,
        lunch_minutes=55,
        section_ids=section_ids,
        batches_per_section=2,
        classroom_by_section={s: "" for s in section_ids},
        inactive_sat_weeks=[1, 3],
        sat_locks=[
            ("IIC-Activity", [1, 2], None),
            ("BENGDIP2", [3, 4], None),
        ],
        semester=4,
    )


# ---------------------------------------------------------------------------
# Course-table parser
# ---------------------------------------------------------------------------
_TYPE_RE = re.compile(r"^(theory|lab|activity)\b\s*(.*)$", re.IGNORECASE)


@dataclass
class ParsedCourse:
    code: str
    name: str
    credits: int
    type: CourseType
    pair_course: Optional[str]
    locked_day: Optional[str]
    locked_slots: Optional[list[int]]
    faculty_spec: str  # raw faculty list text
    is_combined: bool


def _normalise_day(s: str) -> str:
    s = s.strip().upper()[:3]
    if s not in DAYS:
        raise ValueError(f"unknown day {s!r}")
    return s


def _parse_locked(spec: str) -> tuple[Optional[str], Optional[list[int]]]:
    """Parse 'locked=FRI:5,6,7' or 'locked=FRI:5-7' inside a type field."""
    m = re.search(r"locked\s*=\s*([A-Za-z]+)\s*:\s*([\d,\-\s]+)", spec)
    if not m:
        return None, None
    day = _normalise_day(m.group(1))
    raw = m.group(2)
    slots: list[int] = []
    for chunk in re.split(r"\s*,\s*", raw):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            a, b = chunk.split("-")
            slots.extend(range(int(a), int(b) + 1))
        else:
            slots.append(int(chunk))
    return day, slots


def _parse_pair(spec: str) -> Optional[str]:
    m = re.search(r"pair\s*=\s*([A-Za-z0-9_]+)", spec)
    return m.group(1) if m else None


def _parse_combined(spec: str) -> bool:
    return "combined" in spec.lower()


def parse_courses_text(text: str) -> list[ParsedCourse]:
    rows: list[ParsedCourse] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",", 4)]
        if len(parts) < 4:
            raise ValueError(
                f"Course row needs at least 4 comma-separated fields, got: {line!r}"
            )
        code, name, credits_s, type_field = parts[:4]
        faculty_spec = parts[4] if len(parts) > 4 else ""
        m = _TYPE_RE.match(type_field)
        if not m:
            raise ValueError(f"Bad type in {line!r}; expected theory/lab/activity")
        ctype_str = m.group(1).lower()
        suffix = m.group(2).strip()
        ctype = {
            "theory": CourseType.THEORY,
            "lab": CourseType.LAB,
            "activity": CourseType.ACTIVITY,
        }[ctype_str]
        pair = _parse_pair(suffix) if ctype is CourseType.LAB else None
        locked_day, locked_slots = (
            _parse_locked(suffix) if ctype is CourseType.ACTIVITY else (None, None)
        )
        rows.append(
            ParsedCourse(
                code=code,
                name=name,
                credits=int(credits_s),
                type=ctype,
                pair_course=pair,
                locked_day=locked_day,
                locked_slots=locked_slots,
                faculty_spec=faculty_spec,
                is_combined=_parse_combined(suffix),
            )
        )
    return rows


def _split_faculty(spec: str) -> list[str]:
    if not spec:
        return []
    parts = re.split(r"\s*[;|/]\s*", spec)
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
def build_request(
    skeleton: Skeleton,
    courses_text: str,
    elective_blocks_raw: list[dict] | None = None,
    extra_courses: list[ParsedCourse] | None = None,
    time_limit_sec: int = 20,
) -> TimetableRequest:
    parsed = parse_courses_text(courses_text)
    if extra_courses:
        parsed.extend(extra_courses)

    section_batches = {
        sec_id: [f"{sec_id}{idx + 1}" for idx in range(skeleton.batches_per_section)]
        for sec_id in skeleton.section_ids
    }

    elective_course_codes: set[str] = set()
    if elective_blocks_raw:
        for blk in elective_blocks_raw:
            for opt in blk.get("options", []):
                elective_course_codes.add(opt["course_code"])

    # ---- Build courses ----
    courses: list[Course] = []
    for p in parsed:
        weekly_slots: Optional[int] = None
        if p.type is CourseType.LAB:
            weekly_slots = 4 if (p.pair_course and p.credits >= 1) else 2
        elif p.type is CourseType.ACTIVITY:
            weekly_slots = max(p.credits, 1) if p.credits else 1
            if p.locked_slots:
                weekly_slots = len(p.locked_slots)
        courses.append(
            Course(
                code=p.code,
                name=p.name,
                credits=p.credits,
                weekly_slots=weekly_slots,
                type=p.type,
                pair_course=p.pair_course,
                consecutive_required=p.type is CourseType.LAB,
                locked_day=p.locked_day,
                locked_slots=p.locked_slots,
                combined_sections=p.is_combined
                or (p.type is CourseType.ACTIVITY and not p.locked_day)
                or (p.code in elective_course_codes),
            )
        )

    existing_course_codes = {course.code for course in courses}
    if elective_blocks_raw:
        for blk in elective_blocks_raw:
            weekly_slots = int(blk.get("weekly_slot_count", 4))
            for opt in blk.get("options", []):
                code = opt["course_code"]
                if code in existing_course_codes:
                    continue
                courses.append(
                    Course(
                        code=code,
                        name=opt.get("course_name", code),
                        credits=max(1, min(weekly_slots, 4)),
                        weekly_slots=weekly_slots,
                        type=CourseType.THEORY,
                        combined_sections=True,
                    )
                )
                existing_course_codes.add(code)

    elective_blocks_resolved: list[ElectiveBlock] = []
    fac_index: dict[str, Faculty] = {}
    fac_by_id: dict[str, Faculty] = {}
    course_assignments: dict[str, list[tuple[str, Assignment]]] = {}
    global_teacher_loads: dict[str, int] = {}
    fac_count = 0

    def make_fac(name: str) -> Faculty:
        nonlocal fac_count
        existing = fac_index.get(name)
        if existing:
            return existing
        fac_count += 1
        faculty = Faculty(id=f"F{fac_count:03d}", name=name, assignments=[])
        fac_index[name] = faculty
        fac_by_id[faculty.id] = faculty
        global_teacher_loads.setdefault(faculty.id, 0)
        return faculty

    def append_assignment(
        teacher_id: str,
        *,
        course_code: str,
        section_id: str,
        is_lab: bool,
        batch_id: str | None = None,
    ) -> None:
        assignment = Assignment(
            course_code=course_code,
            section_id=section_id,
            is_lab=is_lab,
            batch_id=batch_id,
        )
        fac_by_id[teacher_id].assignments.append(assignment)
        course_assignments.setdefault(course_code, []).append((teacher_id, assignment))

    def unavailable_by_teacher() -> dict[str, set[tuple[str, int]]]:
        return {
            teacher.id: {(slot.day, slot.slot) for slot in teacher.unavailable_slots}
            for teacher in fac_by_id.values()
        }

    def section_targets(course: ParsedCourse) -> list[AssignmentTarget]:
        required_slots = (
            [(course.locked_day, slot) for slot in course.locked_slots]
            if course.locked_day and course.locked_slots
            else []
        )
        return [
            AssignmentTarget(
                section_id=sec_id,
                required_slots=slots_tuple(required_slots),
                label=f"{course.code} section {sec_id}",
            )
            for sec_id in skeleton.section_ids
        ]

    def batch_targets(course: ParsedCourse) -> list[AssignmentTarget]:
        return [
            AssignmentTarget(
                section_id=sec_id,
                batch_id=batch_id,
                label=f"{course.code} batch {batch_id}",
            )
            for sec_id in skeleton.section_ids
            for batch_id in section_batches[sec_id]
        ]

    def assign_pool(course: ParsedCourse, teacher_ids: list[str]) -> None:
        targets = batch_targets(course) if course.type is CourseType.LAB else section_targets(course)
        try:
            picked = assign_targets(
                teacher_ids,
                targets,
                global_teacher_loads,
                unavailable_by_teacher(),
                {teacher_id: fac_by_id[teacher_id].name for teacher_id in teacher_ids},
            )
        except PoolAssignmentError as e:
            raise ValueError(str(e))
        for target, teacher_id in picked:
            append_assignment(
                teacher_id,
                course_code=course.code,
                section_id=target.section_id,
                is_lab=course.type is CourseType.LAB,
                batch_id=target.batch_id,
            )

    def copy_same_as(course: ParsedCourse, ref_code: str) -> None:
        refs = list(course_assignments.get(ref_code, []))
        if not refs:
            raise ValueError(f"same-as={ref_code} referenced before assignments existed")
        for teacher_id, ref in refs:
            if course.type is CourseType.LAB and ref.batch_id is None:
                for batch_id in section_batches.get(ref.section_id, []):
                    append_assignment(
                        teacher_id,
                        course_code=course.code,
                        section_id=ref.section_id,
                        is_lab=True,
                        batch_id=batch_id,
                    )
                    global_teacher_loads[teacher_id] += 1
            else:
                append_assignment(
                    teacher_id,
                    course_code=course.code,
                    section_id=ref.section_id,
                    is_lab=course.type is CourseType.LAB,
                    batch_id=ref.batch_id if course.type is CourseType.LAB else None,
                )
                global_teacher_loads[teacher_id] += 1

    def assign_section_order(course: ParsedCourse, teacher_ids: list[str]) -> None:
        for sec_id, teacher_id in zip(skeleton.section_ids, teacher_ids):
            if course.type is CourseType.LAB:
                for batch_id in section_batches[sec_id]:
                    append_assignment(
                        teacher_id,
                        course_code=course.code,
                        section_id=sec_id,
                        is_lab=True,
                        batch_id=batch_id,
                    )
                    global_teacher_loads[teacher_id] += 1
            else:
                append_assignment(
                    teacher_id,
                    course_code=course.code,
                    section_id=sec_id,
                    is_lab=False,
                )
                global_teacher_loads[teacher_id] += 1

    for p in parsed:
        if p.code in elective_course_codes:
            continue
        names_or_directives = _split_faculty(p.faculty_spec) or ["auto"]

        if len(names_or_directives) == 1 and names_or_directives[0].lower() == "auto":
            if p.type is CourseType.LAB:
                for sec_id in skeleton.section_ids:
                    for batch_id in section_batches[sec_id]:
                        teacher_id = make_fac(f"{p.code} Faculty {batch_id}").id
                        append_assignment(
                            teacher_id,
                            course_code=p.code,
                            section_id=sec_id,
                            is_lab=True,
                            batch_id=batch_id,
                        )
                        global_teacher_loads[teacher_id] += 1
            else:
                teacher_ids = [make_fac(f"{p.code} Faculty {sec_id}").id for sec_id in skeleton.section_ids]
                assign_pool(p, teacher_ids)
            continue

        if len(names_or_directives) == 1 and names_or_directives[0].lower().startswith("x"):
            try:
                count = int(names_or_directives[0][1:])
            except ValueError:
                count = len(batch_targets(p)) if p.type is CourseType.LAB else len(section_targets(p))
            teacher_ids = [make_fac(f"{p.code} Faculty {idx + 1}").id for idx in range(count)]
            assign_pool(p, teacher_ids)
            continue

        if len(names_or_directives) == 1 and names_or_directives[0].lower().startswith("same-as="):
            copy_same_as(p, names_or_directives[0].split("=", 1)[1].strip())
            continue

        teacher_ids = [make_fac(name).id for name in names_or_directives]
        if len(teacher_ids) == len(skeleton.section_ids):
            assign_section_order(p, teacher_ids)
            continue
        assign_pool(p, teacher_ids)

    # ---- Build elective blocks ----
    if elective_blocks_raw:
        for blk in elective_blocks_raw:
            opt_objs: list[ElectiveOption] = []
            for opt in blk.get("options", []):
                pool_ids: list[str] = []
                for name in opt.get("faculty", []):
                    pool_ids.append(make_fac(name).id)
                opt_objs.append(
                    ElectiveOption(
                        course_code=opt["course_code"],
                        course_name=opt.get("course_name", opt["course_code"]),
                        faculty_pool=pool_ids,
                    )
                )

            locked: list[tuple[str, int]] = []
            for day, slot in blk.get("locked_global_slots", []):
                locked.append((_normalise_day(day), int(slot)))

            applicable_sections = [
                sec_id
                for sec_id in blk.get("applies_to_sections", skeleton.section_ids)
                if sec_id in section_batches
            ]
            grouped_sections = (
                even_groups([opt.course_code for opt in opt_objs], applicable_sections)
                if opt_objs
                else {}
            )
            for opt_obj in opt_objs:
                opt_obj.assigned_sections = grouped_sections.get(opt_obj.course_code, [])
                if opt_obj.faculty_pool and opt_obj.assigned_sections:
                    try:
                        teacher_id = assign_targets(
                            opt_obj.faculty_pool,
                            [
                                AssignmentTarget(
                                    section_id=",".join(opt_obj.assigned_sections),
                                    required_slots=slots_tuple(locked),
                                    load_units=len(opt_obj.assigned_sections),
                                    label=f"{blk.get('name', 'Elective')} / {opt_obj.course_code}",
                                )
                            ],
                            global_teacher_loads,
                            unavailable_by_teacher(),
                            {teacher_id: fac_by_id[teacher_id].name for teacher_id in opt_obj.faculty_pool},
                        )[0][1]
                    except PoolAssignmentError as e:
                        raise ValueError(str(e))
                    opt_obj.assigned_faculty_id = teacher_id
                    for sec_id in opt_obj.assigned_sections:
                        append_assignment(
                            teacher_id,
                            course_code=opt_obj.course_code,
                            section_id=sec_id,
                            is_lab=False,
                        )

            elective_blocks_resolved.append(
                ElectiveBlock(
                    id=blk.get("id", "ELEC_BLOCK"),
                    name=blk.get("name", "Elective"),
                    weekly_slot_count=int(blk.get("weekly_slot_count", len(locked) or 4)),
                    applies_to_sections=blk.get("applies_to_sections", skeleton.section_ids),
                    applies_to_semesters=[skeleton.semester],
                    locked_global_slots=locked or None,
                    options=opt_objs,
                )
            )

    # ---- Build sections ----
    sections = [
        Section(
            id=sec_id,
            name=f"{skeleton.semester}th Sem {sec_id}",
            semester=skeleton.semester,
            classroom=skeleton.classroom_by_section.get(sec_id, ""),
            batches=[Batch(id=batch_id, section_id=sec_id) for batch_id in section_batches[sec_id]],
        )
        for sec_id in skeleton.section_ids
    ]

    # ---- Build time config ----
    sat_locks_list: list[LockedSlot] = []
    for label, slots, sections_filter in skeleton.sat_locks:
        sec_filter = sections_filter or skeleton.section_ids
        for sec_id in sec_filter:
            for slot in slots:
                sat_locks_list.append(
                    LockedSlot(day="SAT", slot=slot, label=label, applies_to_sections=[sec_id])
                )

    tc = TimeConfig(
        days=skeleton.days,
        slots_per_day=skeleton.slots_per_day,
        slot_timings=[Timing(start=a, end=b) for a, b in skeleton.slot_timings],
        tea_break=BreakConfig(
            after_slot=skeleton.tea_after_slot,
            duration_min=skeleton.tea_minutes,
        ),
        lunch_break=BreakConfig(
            after_slot=skeleton.lunch_after_slot,
            duration_min=skeleton.lunch_minutes,
        ),
        saturday_rules=SaturdayRules(
            inactive_weeks=skeleton.inactive_sat_weeks,
            locked_slots=sat_locks_list,
        ),
    )

    return TimetableRequest(
        time_config=tc,
        sections=sections,
        courses=courses,
        faculty=list(fac_index.values()),
        elective_blocks=elective_blocks_resolved,
        time_limit_sec=time_limit_sec,
        seek_optimal=False,
    )
