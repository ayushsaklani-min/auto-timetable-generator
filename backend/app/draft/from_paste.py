"""Build a TimetableRequest from a small form skeleton + a pasted course table.

The paste format is intentionally forgiving and spreadsheet-friendly:

  # comments start with '#'
  CODE, NAME, CREDITS, TYPE, FACULTY1; FACULTY2; ...

  Types:
    theory
    lab                       (solo lab)
    lab pair=BCSL404          (paired with another lab — H5 batch swap)
    activity                  (flex activity, placed by solver)
    activity locked=FRI:5,6,7 (locked to a specific day + slot list)

  Faculty list (after the 4th comma):
    Dr A; Dr B; Dr C            (one per section, in order A, B, C, ...)
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
    # Allow ';', '|', or '/' as delimiters
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

    # ---- Build courses ----
    courses: list[Course] = []
    for p in parsed:
        weekly_slots: Optional[int] = None
        if p.type is CourseType.LAB:
            # 1cr lab → 1 session (2 slots) typical for BMSIT
            # 2+ credits could be 2 sessions (4 slots)
            weekly_slots = 4 if (p.pair_course and p.credits >= 1) else 2
        elif p.type is CourseType.ACTIVITY:
            weekly_slots = max(p.credits, 1) if p.credits else 1
            if p.locked_slots:
                weekly_slots = len(p.locked_slots)
        # theory: leave None to fall back to credits
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
                or (p.type is CourseType.ACTIVITY and not p.locked_day),
            )
        )

    # ---- Build faculty ----
    # Elective options are tracked here so we can mark their faculty pools
    # but NOT generate per-section assignments for them (the block reserves
    # the slots globally).
    elective_codes_to_pool: dict[str, list[str]] = {}
    elective_blocks_resolved: list[ElectiveBlock] = []
    fac_index: dict[str, Faculty] = {}  # name -> Faculty
    fac_count = 0

    def make_fac(name: str) -> Faculty:
        nonlocal fac_count
        existing = fac_index.get(name)
        if existing:
            return existing
        fac_count += 1
        f = Faculty(id=f"F{fac_count:03d}", name=name, assignments=[])
        fac_index[name] = f
        return f

    # First pass: regular per-course faculty
    by_code = {p.code: p for p in parsed}
    elective_course_codes: set[str] = set()
    if elective_blocks_raw:
        for blk in elective_blocks_raw:
            for opt in blk.get("options", []):
                elective_course_codes.add(opt["course_code"])

    for p in parsed:
        if p.code in elective_course_codes:
            # Handled below in the elective pool builder.
            continue
        names_or_directives = _split_faculty(p.faculty_spec)
        if not names_or_directives:
            # No faculty given: auto-generate one per section
            names_or_directives = [f"auto"]
        for name_spec in names_or_directives:
            if name_spec.lower() == "auto":
                # Generate one placeholder per section
                for sec in skeleton.section_ids:
                    f = make_fac(f"{p.code} Faculty {sec}")
                    f.assignments.append(
                        Assignment(
                            course_code=p.code,
                            section_id=sec,
                            is_lab=p.type is CourseType.LAB,
                        )
                    )
                break
            if name_spec.lower().startswith("x"):
                try:
                    n = int(name_spec[1:])
                except ValueError:
                    n = len(skeleton.section_ids)
                for i in range(n):
                    sec = skeleton.section_ids[i % len(skeleton.section_ids)]
                    f = make_fac(f"{p.code} Faculty {i + 1}")
                    f.assignments.append(
                        Assignment(
                            course_code=p.code,
                            section_id=sec,
                            is_lab=p.type is CourseType.LAB,
                        )
                    )
                break
            if name_spec.lower().startswith("same-as="):
                ref_code = name_spec.split("=", 1)[1].strip()
                # Copy assignments from another course
                for fac in fac_index.values():
                    for a in list(fac.assignments):
                        if a.course_code == ref_code:
                            fac.assignments.append(
                                Assignment(
                                    course_code=p.code,
                                    section_id=a.section_id,
                                    is_lab=p.type is CourseType.LAB,
                                )
                            )
                break
            # Regular: assign this faculty to one section in order
            # We round-robin: faculty index i goes to section i mod N
            idx = sum(
                1
                for n2 in names_or_directives[: names_or_directives.index(name_spec)]
                if not n2.lower().startswith(("auto", "x", "same-as="))
            )
            sec = skeleton.section_ids[idx % len(skeleton.section_ids)]
            f = make_fac(name_spec)
            f.assignments.append(
                Assignment(
                    course_code=p.code,
                    section_id=sec,
                    is_lab=p.type is CourseType.LAB,
                )
            )
        # Combined-section courses (e.g., BBOK407 taught by one person to all):
        # if exactly one faculty name was provided AND the course is single,
        # extend assignments across all sections.
        if (
            len([n for n in names_or_directives if not n.startswith(("auto", "x"))]) == 1
            and p.type is not CourseType.LAB
            and not p.is_combined  # avoid duplicating if combined flag also set
        ):
            # Only one faculty across all sections → spread.
            only = [n for n in names_or_directives if not n.startswith(("auto", "x"))][0]
            f = fac_index.get(only)
            if f:
                existing_sections = {
                    a.section_id for a in f.assignments if a.course_code == p.code
                }
                for sec in skeleton.section_ids:
                    if sec not in existing_sections:
                        f.assignments.append(
                            Assignment(
                                course_code=p.code,
                                section_id=sec,
                                is_lab=False,
                            )
                        )

    # ---- Build elective blocks ----
    if elective_blocks_raw:
        for blk in elective_blocks_raw:
            opt_objs: list[ElectiveOption] = []
            for opt in blk.get("options", []):
                pool_ids: list[str] = []
                for nm in opt.get("faculty", []):
                    f = make_fac(nm)
                    pool_ids.append(f.id)
                opt_objs.append(
                    ElectiveOption(
                        course_code=opt["course_code"],
                        course_name=opt.get("course_name", opt["course_code"]),
                        faculty_pool=pool_ids,
                    )
                )
            locked: list[tuple[str, int]] = []
            for d, s in blk.get("locked_global_slots", []):
                locked.append((_normalise_day(d), int(s)))
            elective_blocks_resolved.append(
                ElectiveBlock(
                    id=blk.get("id", "ELEC_BLOCK"),
                    name=blk.get("name", "Elective"),
                    weekly_slot_count=int(
                        blk.get("weekly_slot_count", len(locked) or 4)
                    ),
                    applies_to_sections=blk.get(
                        "applies_to_sections", skeleton.section_ids
                    ),
                    applies_to_semesters=[skeleton.semester],
                    locked_global_slots=locked or None,
                    options=opt_objs,
                )
            )

    # ---- Build sections ----
    sections = [
        Section(
            id=s,
            name=f"{skeleton.semester}th Sem {s}",
            semester=skeleton.semester,
            classroom=skeleton.classroom_by_section.get(s, ""),
            batches=[
                Batch(id=f"{s}{i + 1}", section_id=s)
                for i in range(skeleton.batches_per_section)
            ],
        )
        for s in skeleton.section_ids
    ]

    # ---- Build time config ----
    sat_locks_list: list[LockedSlot] = []
    for label, slots, sections_filter in skeleton.sat_locks:
        sec_filter = sections_filter or skeleton.section_ids
        for sec in sec_filter:
            for s in slots:
                sat_locks_list.append(
                    LockedSlot(
                        day="SAT", slot=s, label=label, applies_to_sections=[sec]
                    )
                )

    tc = TimeConfig(
        days=skeleton.days,
        slots_per_day=skeleton.slots_per_day,
        slot_timings=[Timing(start=a, end=b) for a, b in skeleton.slot_timings],
        tea_break=BreakConfig(
            after_slot=skeleton.tea_after_slot, duration_min=skeleton.tea_minutes
        ),
        lunch_break=BreakConfig(
            after_slot=skeleton.lunch_after_slot, duration_min=skeleton.lunch_minutes
        ),
        saturday_rules=SaturdayRules(
            inactive_weeks=skeleton.inactive_sat_weeks, locked_slots=sat_locks_list
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
