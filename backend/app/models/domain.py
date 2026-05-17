"""Domain models for the timetable generator.

These mirror Section 3 of the blueprint and serve as the wire format
between LLM input, validator, solver, and exporter.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------
DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]


class Timing(BaseModel):
    start: str  # "08:30"
    end: str  # "09:25"


class BreakConfig(BaseModel):
    after_slot: int  # break inserted AFTER this 1-indexed slot
    duration_min: int


class LockedSlot(BaseModel):
    day: str  # "SAT"
    slot: int  # 1-indexed
    label: str  # "IIC-Activity", "BENGDIP2"
    faculty_id: Optional[str] = None
    applies_to_sections: Optional[list[str]] = None  # None = all


class SaturdayRules(BaseModel):
    inactive_weeks: list[int] = Field(default_factory=lambda: [1, 3])
    locked_slots: list[LockedSlot] = Field(default_factory=list)


class TimeConfig(BaseModel):
    days: list[str] = Field(default_factory=lambda: DAYS.copy())
    slots_per_day: int = 7
    slot_timings: list[Timing] = Field(default_factory=list)
    tea_break: BreakConfig
    lunch_break: BreakConfig
    saturday_rules: SaturdayRules = Field(default_factory=SaturdayRules)

    @field_validator("days")
    @classmethod
    def days_known(cls, v: list[str]) -> list[str]:
        unknown = [d for d in v if d not in DAYS]
        if unknown:
            raise ValueError(f"unknown day codes: {unknown}")
        return v


# ---------------------------------------------------------------------------
# Section / Batch
# ---------------------------------------------------------------------------
class Batch(BaseModel):
    id: str  # "A1"
    section_id: str  # "A"


class Section(BaseModel):
    id: str  # "A"
    name: str  # "4th Sem A"
    semester: int
    classroom: str = ""
    batches: list[Batch] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Course
# ---------------------------------------------------------------------------
class CourseType(str, Enum):
    THEORY = "THEORY"
    LAB = "LAB"
    ACTIVITY = "ACTIVITY"


class Course(BaseModel):
    code: str
    name: str
    credits: int
    weekly_slots: Optional[int] = None  # auto-derived from credits if None
    type: CourseType = CourseType.THEORY

    # LAB specific
    pair_course: Optional[str] = None  # course code it pairs with
    consecutive_required: bool = False
    spans_break: bool = False
    lab_room: Optional[str] = None  # shared lab room name

    # ACTIVITY specific
    preferred_slots: Optional[list[int]] = None
    locked_day: Optional[str] = None
    locked_slots: Optional[list[int]] = None

    # marks 0-credit fillers that don't strictly need slots (Activities)
    is_filler: bool = False

    # When true, a single faculty may teach multiple sections at the same
    # (day, slot) — e.g., Dept-Activity led for the whole semester at once.
    combined_sections: bool = False

    def effective_weekly_slots(self) -> int:
        if self.weekly_slots is not None:
            return self.weekly_slots
        if self.type == CourseType.LAB:
            return 2  # one 2-slot session
        return max(self.credits, 1)


# ---------------------------------------------------------------------------
# Faculty
# ---------------------------------------------------------------------------
class UnavailableSlot(BaseModel):
    day: str
    slot: int


class Assignment(BaseModel):
    course_code: str
    section_id: str
    is_lab: bool = False
    batch_id: Optional[str] = None  # specific batch for batch-split labs


class Faculty(BaseModel):
    id: str
    name: str
    assignments: list[Assignment] = Field(default_factory=list)
    max_per_day: int = 5
    unavailable_slots: list[UnavailableSlot] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Elective Block
# ---------------------------------------------------------------------------
class ElectiveOption(BaseModel):
    course_code: str
    course_name: str
    faculty_pool: list[str]  # faculty ids
    assigned_sections: list[str] = Field(default_factory=list)
    assigned_faculty_id: Optional[str] = None


class ElectiveBlock(BaseModel):
    id: str
    name: str
    weekly_slot_count: int
    applies_to_sections: list[str]
    applies_to_semesters: list[int]
    # If you already know the (day, slot) pairs the electives should be locked
    # into globally (e.g., Mon-II, Tue-III, ...), set them here. Otherwise the
    # solver picks them but synchronises across sections.
    locked_global_slots: Optional[list[tuple[str, int]]] = None
    options: list[ElectiveOption]


# ---------------------------------------------------------------------------
# Request / Response
# ---------------------------------------------------------------------------
class TimetableRequest(BaseModel):
    time_config: TimeConfig
    sections: list[Section]
    courses: list[Course]
    faculty: list[Faculty]
    elective_blocks: list[ElectiveBlock] = Field(default_factory=list)
    # solver options
    time_limit_sec: int = 20
    seek_optimal: bool = False


class ScheduledClass(BaseModel):
    section_id: str
    course_code: str
    faculty_id: Optional[str] = None
    day: str
    slot: int  # 1-indexed
    is_lab: bool = False
    batch_id: Optional[str] = None
    room: Optional[str] = None
    label: Optional[str] = None  # for elective rendering ("DMS"/"OT") or activity


class Timetable(BaseModel):
    classes: list[ScheduledClass]
    status: str  # OPTIMAL / FEASIBLE / INFEASIBLE / UNKNOWN
    cost: Optional[int] = None
    solve_time_sec: float = 0.0
    notes: list[str] = Field(default_factory=list)


class Violation(BaseModel):
    code: str  # H1, H2, ...
    message: str
    details: dict = Field(default_factory=dict)


class VerificationReport(BaseModel):
    ok: bool
    violations: list[Violation] = Field(default_factory=list)
    soft_score: int = 0  # 0..100


class PreflightReport(BaseModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
