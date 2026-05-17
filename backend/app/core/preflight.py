"""Pre-flight validator (Layer 2 of the blueprint).

Detects impossible setups BEFORE the CP-SAT solver runs. The goal is
to surface clear, human-readable errors rather than letting the solver
return INFEASIBLE without context.
"""
from __future__ import annotations

from collections import defaultdict

from ..models.domain import (
    Course,
    CourseType,
    PreflightReport,
    TimetableRequest,
)


def _available_slots_per_section(req: TimetableRequest) -> int:
    """Schedulable cells per section per week, AFTER subtracting reservations.

    The solver doesn't place anything on Saturday (Sat is exclusively for
    locked activities like IIC + BENGDIP2). Weekday capacity is reduced by
    the courses that are pre-locked to specific (day, slot) cells
    (e.g. Dept-Activity FRI V-VI-VII) and by elective block slots.
    """
    tc = req.time_config
    weekday_slots = sum(tc.slots_per_day for d in tc.days if d != "SAT")

    # Subtract weekday locked-activity cells.
    locked_weekday_cells = 0
    for c in req.courses:
        if c.locked_day and c.locked_slots and c.locked_day != "SAT":
            locked_weekday_cells += len(c.locked_slots)

    # Subtract elective block weekday slots (these are reserved for every
    # section that participates).
    elective_weekday_cells = 0
    for b in req.elective_blocks:
        if b.locked_global_slots:
            elective_weekday_cells += sum(
                1 for (d, _t) in b.locked_global_slots if d != "SAT"
            )
        else:
            elective_weekday_cells += b.weekly_slot_count

    return max(weekday_slots - locked_weekday_cells - elective_weekday_cells, 0)


def _required_slots_for_section(
    req: TimetableRequest, section_id: str
) -> tuple[int, list[str]]:
    """Solver-side workload for this section.

    Excluded from the count:
    - elective block slots (already reserved at fixed (day, slot) cells)
    - courses with locked_day + locked_slots (e.g., Dept-Activity)
    - paired labs share cells with their pair, so they're counted once
    """
    courses_by_code = {c.code: c for c in req.courses}
    elective_course_codes: set[str] = set()
    for block in req.elective_blocks:
        if section_id in block.applies_to_sections:
            for opt in block.options:
                elective_course_codes.add(opt.course_code)

    total = 0
    breakdown: list[str] = []
    seen: set[tuple[str, bool]] = set()
    paired_seen: set[frozenset[str]] = set()

    for fac in req.faculty:
        for asn in fac.assignments:
            if asn.section_id != section_id:
                continue
            if asn.course_code in elective_course_codes:
                continue
            course = courses_by_code.get(asn.course_code)
            if course is None or course.is_filler:
                continue
            # Skip locked-cell courses; they consume reserved capacity already
            # subtracted in _available_slots_per_section.
            if course.locked_day and course.locked_slots:
                continue
            key = (asn.course_code, asn.is_lab)
            if key in seen:
                continue
            seen.add(key)

            # Paired labs occupy the same section cells; count once per pair.
            if course.pair_course:
                pair_key = frozenset({course.code, course.pair_course})
                if pair_key in paired_seen:
                    continue
                paired_seen.add(pair_key)

            total += course.effective_weekly_slots()
            kind = "LAB" if asn.is_lab else ("ACT" if course.type.value == "ACTIVITY" else "TH")
            breakdown.append(f"{course.code}({kind}):{course.effective_weekly_slots()}")

    return total, breakdown


def validate(req: TimetableRequest) -> PreflightReport:
    errors: list[str] = []
    warnings: list[str] = []

    tc = req.time_config
    if not req.sections:
        errors.append("No sections provided")
    if not req.courses:
        errors.append("No courses provided")
    if tc.slots_per_day <= 0:
        errors.append("slots_per_day must be > 0")

    courses_by_code = {c.code: c for c in req.courses}

    # Faculty assignment sanity
    for fac in req.faculty:
        for asn in fac.assignments:
            if asn.course_code not in courses_by_code:
                errors.append(
                    f"Faculty {fac.name} assigned to unknown course {asn.course_code}"
                )
            if asn.section_id not in {s.id for s in req.sections}:
                errors.append(
                    f"Faculty {fac.name} assigned to unknown section {asn.section_id}"
                )

    # Capacity per section
    section_capacity = _available_slots_per_section(req)
    for sec in req.sections:
        required, breakdown = _required_slots_for_section(req, sec.id)
        if required > section_capacity:
            errors.append(
                f"Section {sec.id}: requires {required} slots but only "
                f"{section_capacity} are available. Breakdown: {', '.join(breakdown)}"
            )

    # Faculty workload sanity
    elective_codes = {
        opt.course_code for block in req.elective_blocks for opt in block.options
    }
    fac_load: dict[str, int] = defaultdict(int)
    counted_combined: set[tuple[str, str]] = set()
    for fac in req.faculty:
        for asn in fac.assignments:
            course = courses_by_code.get(asn.course_code)
            if course is None:
                continue
            if course.code in elective_codes or course.combined_sections:
                key = (fac.id, course.code)
                if key in counted_combined:
                    continue
                counted_combined.add(key)
            fac_load[fac.id] += course.effective_weekly_slots()
    max_week_slots = len(tc.days) * tc.slots_per_day
    for fid, load in fac_load.items():
        if load > max_week_slots:
            errors.append(
                f"Faculty {fid} workload {load} exceeds week capacity {max_week_slots}"
            )

    # Elective pool sanity
    for block in req.elective_blocks:
        for opt in block.options:
            if len(opt.faculty_pool) < 1:
                errors.append(
                    f"Elective option {opt.course_code} has empty faculty pool"
                )
        # Elective blocks use combined teaching per option, so the combined
        # pool only needs to cover the available options, not every section.
        total_pool = sum(len(o.faculty_pool) for o in block.options)
        if total_pool < len(block.options):
            errors.append(
                f"Elective {block.name}: combined faculty pool {total_pool} < "
                f"{len(block.options)} options"
            )

    # Lab consistency: pair_course exists and is also a LAB
    for c in req.courses:
        if c.type == CourseType.LAB and c.pair_course:
            other = courses_by_code.get(c.pair_course)
            if other is None:
                errors.append(
                    f"Lab {c.code} pairs with unknown course {c.pair_course}"
                )
            elif other.type != CourseType.LAB:
                errors.append(
                    f"Lab {c.code} paired with non-LAB {c.pair_course}"
                )

    # Locked activities reference valid days/slots
    for c in req.courses:
        if c.locked_day and c.locked_day not in tc.days:
            errors.append(f"Course {c.code} locked_day {c.locked_day} not in days")
        if c.locked_slots:
            for s in c.locked_slots:
                if not 1 <= s <= tc.slots_per_day:
                    errors.append(
                        f"Course {c.code} locked_slot {s} out of range"
                    )

    # Sections-without-faculty warning
    for sec in req.sections:
        has_any = any(
            asn.section_id == sec.id for fac in req.faculty for asn in fac.assignments
        )
        in_block = any(
            sec.id in b.applies_to_sections for b in req.elective_blocks
        )
        if not has_any and not in_block:
            warnings.append(f"Section {sec.id} has no faculty assignments")

    return PreflightReport(ok=len(errors) == 0, errors=errors, warnings=warnings)
