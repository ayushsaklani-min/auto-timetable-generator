"""CP-SAT based timetable solver (Layer 3 of the blueprint). [v2]

Encoding strategy:
- For each section we expand its workload into a list of *tasks*:
    THEORY  -> N independent 1-slot placements
    LAB     -> M independent 2-slot placements (consecutive, no break crossing)
    ACTIVITY-> N placements (possibly locked to specific (day, slot))
- For each task we create one BoolVar per legal placement; exactly one is true.
- Elective blocks reserve (day, slot) tuples globally across all sections.
- Hard constraints H1..H12 are added as linear/boolean constraints.
- Soft constraints S1..S7 are penalty terms in the objective.

This keeps variable count linear and the model small enough to solve in
seconds for the BMSIT 4th sem dataset (~6 sections, ~10 courses).
"""
from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from ortools.sat.python import cp_model

from ..models.domain import (
    Course,
    CourseType,
    ElectiveBlock,
    Faculty,
    ScheduledClass,
    Section,
    Timetable,
    TimetableRequest,
)
from ..draft.pool_assign import (
    AssignmentTarget,
    PoolAssignmentError,
    assign_targets,
    even_groups,
    slots_tuple,
)

# ---------------------------------------------------------------------------
# Task representation
# ---------------------------------------------------------------------------
@dataclass
class Task:
    """A unit of work to place in a section's grid."""

    section_id: str
    course_code: str
    kind: str  # "THEORY" | "LAB" | "ACTIVITY" | "ELECTIVE_RESERVE"
    width: int  # 1 for theory/activity, 2 for lab
    quantity: int  # number of placements per week (number of variable groups)
    faculty_id: Optional[str] = None
    batch_id: Optional[str] = None
    paired_with: Optional[str] = None  # other course code for paired labs
    lab_room: Optional[str] = None
    preferred_slots: Optional[list[int]] = None
    locked_day: Optional[str] = None
    locked_slots: Optional[list[int]] = None
    label: Optional[str] = None
    session_index: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _break_after(req: TimetableRequest) -> set[int]:
    """Slot indices that have a break IMMEDIATELY after them.

    A lab starting at slot t spans t and t+1; it spans a break if a break
    sits between slots t and t+1, i.e., if t is in this set.
    """
    tc = req.time_config
    return {tc.tea_break.after_slot, tc.lunch_break.after_slot}


def _to_minutes(hhmm: str) -> Optional[int]:
    try:
        hh, mm = [int(x) for x in hhmm.split(":")]
    except Exception:
        return None
    return hh * 60 + mm


def _blocked_slots(req: TimetableRequest) -> set[int]:
    """Slots whose clock interval overlaps a configured tea/lunch break."""
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


def _saturday_inactive(req: TimetableRequest) -> bool:
    """Treat Saturday as fully inactive in the planar weekly model.

    BMSIT has alternating Saturdays (1st & 3rd off). For the weekly grid
    we model an *active* Saturday with fixed activities. To handle the
    inactive ones, the consumer iterates calendar weeks; the solver only
    cares about one canonical week.
    """
    sat_rules = req.time_config.saturday_rules
    return len(sat_rules.locked_slots) == 0


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------
class TimetableSolver:
    def __init__(self, req: TimetableRequest):
        self.req = req
        self.tc = req.time_config
        self.days = list(self.tc.days)
        self.slots = list(range(1, self.tc.slots_per_day + 1))
        self.courses_by_code = {c.code: c for c in req.courses}
        self.section_ids = [s.id for s in req.sections]
        self.faculty_by_id = {f.id: f for f in req.faculty}
        self._elective_course_codes = {
            opt.course_code for block in req.elective_blocks for opt in block.options
        }
        self._combined_teaching_codes = {
            course.code for course in req.courses if course.combined_sections
        } | self._elective_course_codes

        # Reserved cells: (section, day, slot) -> label (str)
        # These cells are pre-filled (electives, activities locked, Saturday locks).
        self._reserved: dict[tuple[str, str, int], ScheduledClass] = {}

        # Faculty unavailability derived from reservations.
        # (faculty_id, day, slot) -> True if blocked
        self._faculty_blocked: set[tuple[str, str, int]] = set()

        self._tasks_by_section: dict[str, list[Task]] = defaultdict(list)
        self._break_after = _break_after(req)
        self._blocked_slots = _blocked_slots(req)
        self._teacher_assignment_loads: dict[str, int] = defaultdict(int)
        self._teacher_unavailability: dict[str, set[tuple[str, int]]] = {}
        for fac in req.faculty:
            self._teacher_unavailability[fac.id] = {
                (slot.day, slot.slot) for slot in fac.unavailable_slots
            }
            for assignment in fac.assignments:
                self._teacher_assignment_loads[fac.id] += 1

        # CP model
        self.model = cp_model.CpModel()
        # For each task we keep (task, var_dict) where var_dict maps (day, slot)->BoolVar.
        # For LAB tasks "slot" is the START slot.
        self._task_vars: list[tuple[Task, dict[tuple[str, int], cp_model.IntVar]]] = []

        # All (section, day, slot, var, task) for clash/aggregation.
        # For labs, the var contributes to TWO (day, slot) cells.
        self._cell_contrib: dict[
            tuple[str, str, int], list[tuple[cp_model.IntVar, Task]]
        ] = (
            defaultdict(list)
        )
        # Faculty -> list of vars active at (day, slot)
        self._fac_contrib: dict[
            tuple[str, str, int], list[tuple[cp_model.IntVar, Task]]
        ] = (
            defaultdict(list)
        )
        # Lab-room -> list of vars at (day, slot)
        self._room_contrib: dict[tuple[str, str, int], list[cp_model.IntVar]] = (
            defaultdict(list)
        )
        # Track all (task, day, slot, var) tuples for export
        self._index: list[tuple[Task, str, int, cp_model.IntVar]] = []
        self._section_slot_occupancy_cache: dict[
            tuple[str, str, int], list[cp_model.IntVar]
        ] = {}
        self._faculty_slot_occupancy_cache: dict[
            tuple[str, str, int], list[cp_model.IntVar]
        ] = {}
        self._section_occupied_cache: dict[tuple[str, str, int], cp_model.IntVar] = {}
        self._faculty_occupied_cache: dict[tuple[str, str, int], cp_model.IntVar] = {}
        self._room_occupied_cache: dict[tuple[str, str, int], cp_model.IntVar] = {}
        self._true_var = self.model.NewConstant(1)
        self._false_var = self.model.NewConstant(0)

    # ------------------------------------------------------------------
    # Reservations
    # ------------------------------------------------------------------
    def _reserve(self, sec_id: str, day: str, slot: int, sc: ScheduledClass) -> None:
        self._reserved[(sec_id, day, slot)] = sc
        if sc.faculty_id:
            self._faculty_blocked.add((sc.faculty_id, day, slot))

    def _section_slot_occupancies(self, sec_id: str, day: str, slot: int) -> list[cp_model.IntVar]:
        key = (sec_id, day, slot)
        cached = self._section_slot_occupancy_cache.get(key)
        if cached is not None:
            return cached

        regular_vars: list[cp_model.IntVar] = []
        batch_groups: dict[tuple[str, int], list[cp_model.IntVar]] = defaultdict(list)
        for var, task in self._cell_contrib.get(key, []):
            if task.kind == "LAB" and task.batch_id:
                batch_groups[(task.course_code, task.session_index)].append(var)
            else:
                regular_vars.append(var)

        occupancies = list(regular_vars)
        for (course_code, session_index), vars_ in batch_groups.items():
            if len(vars_) == 1:
                occupancies.append(vars_[0])
                continue
            occ = self.model.NewBoolVar(
                f"sec_occ_{sec_id}_{course_code}_{session_index}_{day}_{slot}"
            )
            self.model.AddMaxEquality(occ, vars_)
            occupancies.append(occ)

        self._section_slot_occupancy_cache[key] = occupancies
        return occupancies

    def _faculty_slot_occupancies(self, fac_id: str, day: str, slot: int) -> list[cp_model.IntVar]:
        key = (fac_id, day, slot)
        cached = self._faculty_slot_occupancy_cache.get(key)
        if cached is not None:
            return cached

        regular_vars: list[cp_model.IntVar] = []
        combined_groups: dict[str, list[cp_model.IntVar]] = defaultdict(list)
        for var, task in self._fac_contrib.get(key, []):
            if task.course_code in self._combined_teaching_codes:
                combined_groups[task.course_code].append(var)
            else:
                regular_vars.append(var)

        occupancies = list(regular_vars)
        for course_code, vars_ in combined_groups.items():
            if len(vars_) == 1:
                occupancies.append(vars_[0])
                continue
            occ = self.model.NewBoolVar(f"occ_{fac_id}_{course_code}_{day}_{slot}")
            self.model.AddMaxEquality(occ, vars_)
            occupancies.append(occ)

        self._faculty_slot_occupancy_cache[key] = occupancies
        return occupancies

    def _bool_or(self, terms: list[cp_model.IntVar], name: str) -> cp_model.IntVar:
        if not terms:
            return self._false_var
        if len(terms) == 1:
            return terms[0]
        out = self.model.NewBoolVar(name)
        self.model.AddMaxEquality(out, terms)
        return out

    def _bool_not(self, term: cp_model.IntVar, name: str) -> cp_model.IntVar:
        out = self.model.NewBoolVar(name)
        self.model.Add(out + term == 1)
        return out

    def _bool_and(
        self,
        terms: list[cp_model.IntVar],
        name: str,
    ) -> cp_model.IntVar:
        if not terms:
            return self._false_var
        if len(terms) == 1:
            return terms[0]
        out = self.model.NewBoolVar(name)
        for term in terms:
            self.model.Add(out <= term)
        self.model.Add(out >= sum(terms) - (len(terms) - 1))
        return out

    def _section_slot_occupied(self, sec_id: str, day: str, slot: int) -> cp_model.IntVar:
        key = (sec_id, day, slot)
        cached = self._section_occupied_cache.get(key)
        if cached is not None:
            return cached
        if key in self._reserved:
            occupied = self._true_var
        else:
            occupied = self._bool_or(
                self._section_slot_occupancies(sec_id, day, slot),
                f"sec_used_{sec_id}_{day}_{slot}",
            )
        self._section_occupied_cache[key] = occupied
        return occupied

    def _faculty_slot_occupied(self, fac_id: str, day: str, slot: int) -> cp_model.IntVar:
        key = (fac_id, day, slot)
        cached = self._faculty_occupied_cache.get(key)
        if cached is not None:
            return cached
        has_reserved = any(
            sc.faculty_id == fac_id
            for (sec_id, d, t), sc in self._reserved.items()
            if d == day and t == slot
        )
        if has_reserved:
            occupied = self._true_var
        else:
            occupied = self._bool_or(
                self._faculty_slot_occupancies(fac_id, day, slot),
                f"fac_used_{fac_id}_{day}_{slot}",
            )
        self._faculty_occupied_cache[key] = occupied
        return occupied

    def _room_slot_occupied(self, room: str, day: str, slot: int) -> cp_model.IntVar:
        key = (room, day, slot)
        cached = self._room_occupied_cache.get(key)
        if cached is not None:
            return cached
        occupied = self._bool_or(
            self._room_contrib.get(key, []),
            f"room_used_{room}_{day}_{slot}",
        )
        self._room_occupied_cache[key] = occupied
        return occupied

    def _usable_slots(self) -> list[int]:
        return [slot for slot in self.slots if slot not in self._blocked_slots]

    def _weekday_days(self) -> list[str]:
        days = [day for day in self.days if day != "SAT"]
        return days or list(self.days)

    def _apply_elective_blocks(self) -> None:
        """Reserve global elective slots in every applying section.

        Each section gets the concrete elective option assigned to it. A single
        teacher may cover multiple sections for the same option at the same time
        because elective teaching is modelled as combined across the section
        group.
        """
        section_set = set(self.section_ids)
        for block in self.req.elective_blocks:
            applicable = [s for s in block.applies_to_sections if s in section_set]
            if not applicable:
                continue
            globals_ = block.locked_global_slots
            if not globals_:
                globals_ = []
                needed = block.weekly_slot_count
                for d in self.days:
                    if d == "SAT":
                        continue
                    for t in self.slots:
                        if len(globals_) >= needed:
                            break
                        globals_.append((d, t))
                    if len(globals_) >= needed:
                        break

            if block.options:
                for opt in block.options:
                    opt.assigned_sections = [sec_id for sec_id in opt.assigned_sections if sec_id in section_set]
                missing_sections = [
                    sec_id
                    for sec_id in applicable
                    if not any(sec_id in opt.assigned_sections for opt in block.options)
                ]
                if missing_sections:
                    groups = even_groups(
                        [opt.course_code for opt in block.options],
                        applicable,
                    )
                    for opt in block.options:
                        opt.assigned_sections = groups.get(opt.course_code, [])

                for opt in block.options:
                    if opt.assigned_sections and not opt.assigned_faculty_id and opt.faculty_pool:
                        try:
                            opt.assigned_faculty_id = assign_targets(
                                opt.faculty_pool,
                                [
                                    AssignmentTarget(
                                        section_id=",".join(opt.assigned_sections),
                                        required_slots=slots_tuple(globals_),
                                        load_units=len(opt.assigned_sections),
                                        label=f"{block.name} / {opt.course_code}",
                                    )
                                ],
                                self._teacher_assignment_loads,
                                self._teacher_unavailability,
                                {
                                    teacher_id: self.faculty_by_id[teacher_id].name
                                    for teacher_id in opt.faculty_pool
                                    if teacher_id in self.faculty_by_id
                                },
                            )[0][1]
                        except PoolAssignmentError as e:
                            raise RuntimeError(str(e))

                    for sec_id in opt.assigned_sections:
                        for (day, slot) in globals_:
                            self._reserve(
                                sec_id,
                                day,
                                slot,
                                ScheduledClass(
                                    section_id=sec_id,
                                    course_code=opt.course_code,
                                    faculty_id=opt.assigned_faculty_id,
                                    day=day,
                                    slot=slot,
                                    label=f"{block.name}: {opt.course_name}",
                                ),
                            )
                    if opt.assigned_faculty_id:
                        for (day, slot) in globals_:
                            self._faculty_blocked.add((opt.assigned_faculty_id, day, slot))
                continue

            for sec_id in applicable:
                for (day, slot) in globals_:
                    self._reserve(
                        sec_id,
                        day,
                        slot,
                        ScheduledClass(
                            section_id=sec_id,
                            course_code=block.id,
                            faculty_id=None,
                            day=day,
                            slot=slot,
                            label=block.name,
                        ),
                    )

    def _apply_saturday_locks(self) -> None:
        for ls in self.tc.saturday_rules.locked_slots:
            applies = ls.applies_to_sections or self.section_ids
            for sec_id in applies:
                self._reserve(
                    sec_id,
                    ls.day,
                    ls.slot,
                    ScheduledClass(
                        section_id=sec_id,
                        course_code=ls.label,
                        faculty_id=ls.faculty_id,
                        day=ls.day,
                        slot=ls.slot,
                        label=ls.label,
                    ),
                )

    def _apply_course_locks(self) -> None:
        """Courses with locked_day + locked_slots (e.g., Dept-Activity)."""
        for course in self.req.courses:
            if not course.locked_day or not course.locked_slots:
                continue
            for sec_id in self.section_ids:
                # Find faculty (optional) from assignments
                fac_id = None
                for f in self.req.faculty:
                    for a in f.assignments:
                        if a.course_code == course.code and a.section_id == sec_id:
                            fac_id = f.id
                            break
                    if fac_id:
                        break
                for t in course.locked_slots:
                    self._reserve(
                        sec_id,
                        course.locked_day,
                        t,
                        ScheduledClass(
                            section_id=sec_id,
                            course_code=course.code,
                            faculty_id=fac_id,
                            day=course.locked_day,
                            slot=t,
                            label=course.name,
                        ),
                    )

    # ------------------------------------------------------------------
    # Task generation
    # ------------------------------------------------------------------
    def _build_tasks(self) -> None:
        """Convert the workload into placement tasks per section.

        Each (faculty, course, section) assignment yields tasks based on the
        course type. Courses that are part of an elective block are skipped
        (already reserved). Courses with locked_day/locked_slots are skipped.
        Batch-aware lab assignments preserve paired-lab swap semantics when
        batch ids are available on the upstream assignments.
        """
        elective_course_codes: set[str] = set()
        for b in self.req.elective_blocks:
            for opt in b.options:
                elective_course_codes.add(opt.course_code)

        # Index assignments by (section, course, is_lab) -> [(faculty_id, batch_id)]
        assignment_index: dict[
            tuple[str, str, bool], list[tuple[str, Optional[str]]]
        ] = defaultdict(list)
        for fac in self.req.faculty:
            for a in fac.assignments:
                assignment_index[(a.section_id, a.course_code, a.is_lab)].append(
                    (fac.id, a.batch_id)
                )

        # Count cells already reserved per (section, course_code) so pinned
        # classes count toward the workload and we don't schedule duplicates.
        reserved_by_sec_course: dict[tuple[str, str], int] = defaultdict(int)
        for (sec_id, _d, _t), sc in self._reserved.items():
            reserved_by_sec_course[(sec_id, sc.course_code)] += 1

        for sec in self.req.sections:
            for course in self.req.courses:
                if course.code in elective_course_codes:
                    continue
                if course.locked_day and course.locked_slots:
                    continue  # already reserved

                if course.type == CourseType.LAB:
                    bindings = assignment_index.get((sec.id, course.code, True)) or assignment_index.get(
                        (sec.id, course.code, False)
                    )
                    if not bindings:
                        continue
                    sessions = max(course.effective_weekly_slots() // 2, 1)
                    batch_map = {
                        batch_id: faculty_id
                        for faculty_id, batch_id in bindings
                        if batch_id
                    }
                    if not batch_map:
                        for s_idx in range(sessions):
                            self._tasks_by_section[sec.id].append(
                                Task(
                                    section_id=sec.id,
                                    course_code=course.code,
                                    kind="LAB",
                                    width=2,
                                    quantity=1,
                                    faculty_id=bindings[0][0],
                                    paired_with=course.pair_course,
                                    lab_room=course.lab_room,
                                    label=course.name,
                                    session_index=s_idx,
                                )
                            )
                        continue

                    section_batch_ids = [
                        batch.id for batch in sec.batches if batch.id in batch_map
                    ] or list(batch_map.keys())

                    if course.pair_course and len(section_batch_ids) >= 2:
                        ordered_batches = list(section_batch_ids)
                        if course.code > course.pair_course:
                            ordered_batches = list(reversed(ordered_batches))
                        for s_idx in range(sessions):
                            batch_id = ordered_batches[s_idx % len(ordered_batches)]
                            self._tasks_by_section[sec.id].append(
                                Task(
                                    section_id=sec.id,
                                    course_code=course.code,
                                    kind="LAB",
                                    width=2,
                                    quantity=1,
                                    faculty_id=batch_map[batch_id],
                                    batch_id=batch_id,
                                    paired_with=course.pair_course,
                                    lab_room=course.lab_room,
                                    label=course.name,
                                    session_index=s_idx,
                                )
                            )
                        continue

                    for s_idx in range(sessions):
                        for batch_id in section_batch_ids:
                            self._tasks_by_section[sec.id].append(
                                Task(
                                    section_id=sec.id,
                                    course_code=course.code,
                                    kind="LAB",
                                    width=2,
                                    quantity=1,
                                    faculty_id=batch_map[batch_id],
                                    batch_id=batch_id,
                                    paired_with=course.pair_course,
                                    lab_room=course.lab_room,
                                    label=course.name,
                                    session_index=s_idx,
                                )
                            )
                elif course.type == CourseType.ACTIVITY:
                    bindings = assignment_index.get((sec.id, course.code, False))
                    fac_id = bindings[0][0] if bindings else None
                    n = course.effective_weekly_slots()
                    n -= reserved_by_sec_course.get((sec.id, course.code), 0)
                    for _ in range(max(n, 0)):
                        self._tasks_by_section[sec.id].append(
                            Task(
                                section_id=sec.id,
                                course_code=course.code,
                                kind="ACTIVITY",
                                width=1,
                                quantity=1,
                                faculty_id=fac_id,
                                preferred_slots=course.preferred_slots,
                                label=course.name,
                            )
                        )
                else:  # THEORY
                    bindings = assignment_index.get((sec.id, course.code, False))
                    if not bindings:
                        continue
                    n = course.effective_weekly_slots()
                    n -= reserved_by_sec_course.get((sec.id, course.code), 0)
                    for _ in range(max(n, 0)):
                        self._tasks_by_section[sec.id].append(
                            Task(
                                section_id=sec.id,
                                course_code=course.code,
                                kind="THEORY",
                                width=1,
                                quantity=1,
                                faculty_id=bindings[0][0],
                                label=course.name,
                            )
                        )

    # ------------------------------------------------------------------
    # Variable creation
    # ------------------------------------------------------------------
    def _create_variables(self) -> None:
        for sec_id, tasks in self._tasks_by_section.items():
            for idx, task in enumerate(tasks):
                var_map: dict[tuple[str, int], cp_model.IntVar] = {}
                for d in self.days:
                    # Saturday is reserved exclusively for the explicit locks
                    # (IIC, BENGDIP2, etc.). No solver-placed task may land on
                    # Saturday — this enforces the user rule "no class on
                    # Saturday other than English / IIC / Dept-Activity".
                    if d == "SAT":
                        continue
                    for t in self.slots:
                        if t in self._blocked_slots:
                            continue
                        if task.width == 2:
                            # Lab start: t and t+1 must both be valid and not span a break.
                            if t + 1 not in self.slots:
                                continue
                            if t in self._break_after:
                                continue
                            if t + 1 in self._blocked_slots:
                                continue
                            # Both cells must be free of reservation.
                            if (sec_id, d, t) in self._reserved:
                                continue
                            if (sec_id, d, t + 1) in self._reserved:
                                continue
                        else:
                            if (sec_id, d, t) in self._reserved:
                                continue
                        # Locked-day check (activities/courses with locked_day only)
                        if task.locked_day and d != task.locked_day:
                            continue
                        if task.locked_slots and t not in task.locked_slots:
                            continue
                        # Faculty unavailability
                        if task.faculty_id:
                            if (task.faculty_id, d, t) in self._faculty_blocked:
                                continue
                            if task.width == 2 and (task.faculty_id, d, t + 1) in self._faculty_blocked:
                                continue
                            unav = self._teacher_unavailability.get(task.faculty_id, set())
                            if (d, t) in unav:
                                continue
                            if task.width == 2 and (d, t + 1) in unav:
                                continue
                        v = self.model.NewBoolVar(f"x_{sec_id}_{task.course_code}_{idx}_{d}_{t}")
                        var_map[(d, t)] = v
                        # Cell contributions. For PAIRED labs only the
                        # alphabetically-first course in the pair contributes,
                        # because the two labs share the same (day, slot) for
                        # the section grid (different batches, same cell).
                        contributes_to_cell = not (
                            task.kind == "LAB"
                            and task.paired_with
                            and task.course_code > task.paired_with
                        )
                        if contributes_to_cell:
                            self._cell_contrib[(sec_id, d, t)].append((v, task))
                            if task.width == 2:
                                self._cell_contrib[(sec_id, d, t + 1)].append((v, task))
                        # Faculty contributions
                        if task.faculty_id:
                            self._fac_contrib[(task.faculty_id, d, t)].append((v, task))
                            if task.width == 2:
                                self._fac_contrib[(task.faculty_id, d, t + 1)].append((v, task))
                        # Room contributions
                        if task.lab_room:
                            self._room_contrib[(task.lab_room, d, t)].append(v)
                            if task.width == 2:
                                self._room_contrib[(task.lab_room, d, t + 1)].append(v)
                        self._index.append((task, d, t, v))
                if not var_map:
                    raise RuntimeError(
                        f"No legal placement for {task.kind} {task.course_code} in section {sec_id}"
                    )
                self._task_vars.append((task, var_map))

    # ------------------------------------------------------------------
    # Hard constraints
    # ------------------------------------------------------------------
    def _add_hard_constraints(self) -> None:
        # H3: each task placed EXACTLY once
        for task, var_map in self._task_vars:
            self.model.Add(sum(var_map.values()) == 1)

        # H2: section no-clash. Reserved cells already consume the slot;
        # for non-reserved cells, at most 1 visible course may occupy it.
        for (sec_id, d, t) in self._cell_contrib:
            occupancies = self._section_slot_occupancies(sec_id, d, t)
            if occupancies:
                self.model.Add(sum(occupancies) <= 1)

        # H1: faculty no-clash. Combined teaching codes (dept activities,
        # electives, etc.) count as one occupancy across sections.
        for (fid, d, t) in self._fac_contrib:
            occupancies = self._faculty_slot_occupancies(fid, d, t)
            if occupancies:
                self.model.Add(sum(occupancies) <= 1)

        # H6: lab room contention.
        for (_room, _d, _t), vars_ in self._room_contrib.items():
            self.model.Add(sum(vars_) <= 1)

        # H4 lab consecutiveness / no spanning break is enforced at variable
        # creation (lab vars only exist for legal start slots).

        # Multi-batch unpaired labs represent one visible lab session in the
        # section grid, so all batches of the same session must align.
        by_lab_session: dict[tuple[str, str, int], list[dict[tuple[str, int], cp_model.IntVar]]] = defaultdict(list)
        for task, vm in self._task_vars:
            if task.kind != "LAB" or not task.batch_id or task.paired_with:
                continue
            by_lab_session[(task.section_id, task.course_code, task.session_index)].append(vm)
        for (_sec, _code, _session), vms in by_lab_session.items():
            if len(vms) < 2:
                continue
            anchor = vms[0]
            keys = set().union(*(vm.keys() for vm in vms))
            for vm in vms[1:]:
                for k in keys:
                    a_v = anchor.get(k)
                    b_v = vm.get(k)
                    if a_v is not None and b_v is not None:
                        self.model.Add(a_v == b_v)
                    elif a_v is not None and b_v is None:
                        self.model.Add(a_v == 0)
                    elif b_v is not None and a_v is None:
                        self.model.Add(b_v == 0)

        # H5: paired labs must run at the same (day, slot) within a section
        # for each pair index, AND on different days across pair sessions.
        for sec_id in self.section_ids:
            paired_groups: dict[frozenset[str], list[tuple[Task, dict[tuple[str, int], cp_model.IntVar]]]] = defaultdict(list)
            for task, vm in self._task_vars:
                if task.section_id != sec_id or task.kind != "LAB":
                    continue
                if task.paired_with:
                    key = frozenset({task.course_code, task.paired_with})
                    paired_groups[key].append((task, vm))
            for group in paired_groups.values():
                by_code: dict[str, list[tuple[Task, dict[tuple[str, int], cp_model.IntVar]]]] = defaultdict(list)
                for task, vm in group:
                    by_code[task.course_code].append((task, vm))
                codes = list(by_code.keys())
                if len(codes) != 2:
                    continue
                a_list = sorted(by_code[codes[0]], key=lambda item: item[0].session_index)
                b_list = sorted(by_code[codes[1]], key=lambda item: item[0].session_index)
                n = min(len(a_list), len(b_list))
                for i in range(n):
                    _a_task, a_vm = a_list[i]
                    _b_task, b_vm = b_list[i]
                    for k in set(a_vm.keys()) | set(b_vm.keys()):
                        a_v = a_vm.get(k)
                        b_v = b_vm.get(k)
                        if a_v is not None and b_v is not None:
                            self.model.Add(a_v == b_v)
                        elif a_v is not None and b_v is None:
                            self.model.Add(a_v == 0)
                        elif b_v is not None and a_v is None:
                            self.model.Add(b_v == 0)
                # Sessions on different days: i!=j must be on different days
                if n > 1:
                    for i in range(n):
                        for j in range(i + 1, n):
                            ai_vm = a_list[i][1]
                            aj_vm = a_list[j][1]
                            for d in self.days:
                                same_day_i = [v for (dd, _t), v in ai_vm.items() if dd == d]
                                same_day_j = [v for (dd, _t), v in aj_vm.items() if dd == d]
                                if same_day_i and same_day_j:
                                    self.model.Add(sum(same_day_i) + sum(same_day_j) <= 1)

        # Spread theory: same course must not appear twice on the same day in
        # a section (this also helps S7 but is a near-hard rule in practice).
        # Implemented as a soft hint instead in soft_constraints; keep hard
        # behavior only when course has multiple non-lab tasks.
        # (Optional, omitted as hard to allow tight schedules.)

        # H12 faculty availability already filtered at variable creation.

        # H_SLOT1: every section's slot 1 (8:30) on every active weekday must
        # be occupied — either by a reserved cell or by a solver placement.
        # SAT slot 1 is already locked to IIC.
        for sec_id in self.section_ids:
            for d in self.days:
                if d == "SAT":
                    continue
                if (sec_id, d, 1) in self._reserved:
                    continue
                occupancies = self._section_slot_occupancies(sec_id, d, 1)
                if occupancies:
                    self.model.Add(sum(occupancies) >= 1)

        # Faculty max_per_day (H + soft hybrid)
        for fac in self.req.faculty:
            cap = fac.max_per_day or 0
            if cap <= 0:
                continue
            for d in self.days:
                day_vars: list[cp_model.IntVar] = []
                for t in self.slots:
                    day_vars.extend(self._faculty_slot_occupancies(fac.id, d, t))
                if day_vars:
                    self.model.Add(sum(day_vars) <= cap)

    # ------------------------------------------------------------------
    # Soft constraints
    # ------------------------------------------------------------------
    def _add_idle_gap_penalties(
        self,
        penalties: list[cp_model.IntVar],
        owner_ids: list[str],
        occupied_fn,
        label: str,
        weight: int,
        days: Optional[list[str]] = None,
    ) -> None:
        """Penalize empty cells trapped between earlier and later work."""
        usable_slots = self._usable_slots()
        if len(usable_slots) < 3:
            return
        for owner_id in owner_ids:
            for day in days or self.days:
                occ_by_slot = [
                    (slot, occupied_fn(owner_id, day, slot))
                    for slot in usable_slots
                ]
                for idx in range(1, len(occ_by_slot) - 1):
                    slot, occupied = occ_by_slot[idx]
                    before = self._bool_or(
                        [occ for _slot, occ in occ_by_slot[:idx]],
                        f"{label}_before_{owner_id}_{day}_{slot}",
                    )
                    after = self._bool_or(
                        [occ for _slot, occ in occ_by_slot[idx + 1:]],
                        f"{label}_after_{owner_id}_{day}_{slot}",
                    )
                    empty = self._bool_not(
                        occupied,
                        f"{label}_empty_{owner_id}_{day}_{slot}",
                    )
                    idle = self._bool_and(
                        [before, empty, after],
                        f"{label}_idle_{owner_id}_{day}_{slot}",
                    )
                    penalties.append(self._scale(idle, weight))

    def _add_common_blank_penalties(self, penalties: list[cp_model.IntVar]) -> None:
        """Discourage columns where every section is free inside the day."""
        usable_slots = self._usable_slots()
        if len(usable_slots) < 3 or not self.section_ids:
            return
        post_lunch = self.tc.lunch_break.after_slot + 1
        for day in self._weekday_days():
            section_any_by_slot: list[tuple[int, cp_model.IntVar]] = []
            for slot in usable_slots:
                any_section = self._bool_or(
                    [
                        self._section_slot_occupied(sec_id, day, slot)
                        for sec_id in self.section_ids
                    ],
                    f"any_section_{day}_{slot}",
                )
                section_any_by_slot.append((slot, any_section))

            for idx in range(1, len(section_any_by_slot) - 1):
                slot, any_section = section_any_by_slot[idx]
                before = self._bool_or(
                    [occ for _slot, occ in section_any_by_slot[:idx]],
                    f"common_before_{day}_{slot}",
                )
                after = self._bool_or(
                    [occ for _slot, occ in section_any_by_slot[idx + 1:]],
                    f"common_after_{day}_{slot}",
                )
                empty_for_all = self._bool_not(any_section, f"common_empty_{day}_{slot}")
                common_gap = self._bool_and(
                    [before, empty_for_all, after],
                    f"common_gap_{day}_{slot}",
                )
                weight = 55 if slot == post_lunch else 16
                penalties.append(self._scale(common_gap, weight))

    def _add_late_slot_penalties(self, penalties: list[cp_model.IntVar]) -> None:
        """Prefer compact earlier days once breaks and locks are respected."""
        post_lunch = self.tc.lunch_break.after_slot + 1
        for sec_id in self.section_ids:
            for day in self._weekday_days():
                for slot in self._usable_slots():
                    if slot <= post_lunch:
                        continue
                    weight = (slot - post_lunch) * 3
                    penalties.append(
                        self._scale(
                            self._section_slot_occupied(sec_id, day, slot),
                            weight,
                        )
                    )

    def _add_daily_spread_penalties(
        self,
        penalties: list[cp_model.IntVar],
        owner_ids: list[str],
        occupied_fn,
        label: str,
        weight: int,
    ) -> None:
        """Balance workload by minimizing max-day minus min-day load."""
        days = self._weekday_days()
        if len(days) < 2:
            return
        usable_slots = self._usable_slots()
        for owner_id in owner_ids:
            day_loads: list[cp_model.IntVar] = []
            for day in days:
                terms = [occupied_fn(owner_id, day, slot) for slot in usable_slots]
                load = self.model.NewIntVar(
                    0,
                    len(usable_slots),
                    f"{label}_load_{owner_id}_{day}",
                )
                self.model.Add(load == sum(terms))
                day_loads.append(load)
            max_v = self.model.NewIntVar(0, len(usable_slots), f"{label}_max_{owner_id}")
            min_v = self.model.NewIntVar(0, len(usable_slots), f"{label}_min_{owner_id}")
            self.model.AddMaxEquality(max_v, day_loads)
            self.model.AddMinEquality(min_v, day_loads)
            spread = self.model.NewIntVar(
                0,
                len(usable_slots),
                f"{label}_spread_{owner_id}",
            )
            self.model.Add(spread == max_v - min_v)
            penalties.append(self._scale(spread, weight))

    def _add_soft_constraints(self) -> list[cp_model.IntVar]:
        penalties: list[cp_model.IntVar] = []

        # S1 + S7: avoid same course twice on same day (in a section)
        # Group THEORY tasks by (section, course)
        by_sec_course: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for task, vm in self._task_vars:
            if task.kind == "THEORY":
                by_sec_course[(task.section_id, task.course_code)].append(vm)

        for (sec_id, code), vms in by_sec_course.items():
            if len(vms) < 2:
                continue
            for d in self.days:
                day_vars: list[cp_model.IntVar] = []
                for vm in vms:
                    day_vars.extend(v for (dd, _t), v in vm.items() if dd == d)
                if len(day_vars) < 2:
                    continue
                # Penalize: count = sum(day_vars). Penalty = max(count - 1, 0)
                overflow = self.model.NewIntVar(0, len(day_vars), f"of_{sec_id}_{code}_{d}")
                self.model.Add(sum(day_vars) - 1 <= overflow)
                penalties.append(self._scale(overflow, 10))

        # S2: at most 2 high-credit (>=3) theory classes per day per section
        high_codes = {c.code for c in self.req.courses if c.credits >= 3 and c.type == CourseType.THEORY}
        for sec_id in self.section_ids:
            for d in self.days:
                day_vars: list[cp_model.IntVar] = []
                for task, vm in self._task_vars:
                    if task.section_id != sec_id or task.course_code not in high_codes:
                        continue
                    day_vars.extend(v for (dd, _t), v in vm.items() if dd == d)
                if not day_vars:
                    continue
                of = self.model.NewIntVar(0, len(day_vars), f"s2_{sec_id}_{d}")
                self.model.Add(sum(day_vars) - 2 <= of)
                penalties.append(self._scale(of, 8))

        # S6: activities prefer afternoon (slot >= post_lunch)
        post_lunch = self.tc.lunch_break.after_slot + 1
        for task, vm in self._task_vars:
            if task.kind != "ACTIVITY":
                continue
            morning_vars = [
                v for (_d, t), v in vm.items()
                if t < (self.tc.lunch_break.after_slot + 1)
            ]
            if morning_vars:
                pen = self.model.NewIntVar(0, len(morning_vars), f"s6_{task.section_id}_{task.course_code}")
                self.model.Add(sum(morning_vars) <= pen)
                penalties.append(self._scale(pen, 2))

        active_faculty_ids = sorted(
            {fac_id for fac_id, _day, _slot in self._fac_contrib}
            | {
                sc.faculty_id
                for sc in self._reserved.values()
                if sc.faculty_id
            }
        )
        active_rooms = sorted({room for room, _day, _slot in self._room_contrib})

        # Lowest-waste objective: keep days compact for students first, then
        # faculty and rooms, while preserving all hard conflict constraints.
        self._add_idle_gap_penalties(
            penalties,
            self.section_ids,
            self._section_slot_occupied,
            "student",
            45,
            days=self._weekday_days(),
        )
        self._add_common_blank_penalties(penalties)
        self._add_late_slot_penalties(penalties)
        self._add_daily_spread_penalties(
            penalties,
            self.section_ids,
            self._section_slot_occupied,
            "section",
            9,
        )
        self._add_idle_gap_penalties(
            penalties,
            active_faculty_ids,
            self._faculty_slot_occupied,
            "faculty",
            14,
            days=self._weekday_days(),
        )
        self._add_daily_spread_penalties(
            penalties,
            active_faculty_ids,
            self._faculty_slot_occupied,
            "faculty",
            5,
        )
        self._add_idle_gap_penalties(
            penalties,
            active_rooms,
            self._room_slot_occupied,
            "room",
            6,
            days=self._weekday_days(),
        )
        self._add_daily_spread_penalties(
            penalties,
            active_rooms,
            self._room_slot_occupied,
            "room",
            3,
        )

        return penalties

    def _scale(self, var: cp_model.IntVar, weight: int) -> cp_model.IntVar:
        scaled = self.model.NewIntVar(0, 10000, f"sc_{var.Name()}_{weight}")
        self.model.Add(scaled == var * weight)
        return scaled

    # ------------------------------------------------------------------
    # Driver
    # ------------------------------------------------------------------
    def solve(self) -> Timetable:
        self._apply_elective_blocks()
        self._apply_saturday_locks()
        self._apply_course_locks()
        self._build_tasks()
        self._create_variables()
        self._add_hard_constraints()
        penalties = self._add_soft_constraints()

        if penalties:
            self.model.Minimize(sum(penalties))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(self.req.time_limit_sec)
        solver.parameters.num_search_workers = 8
        start = time.time()
        status = solver.Solve(self.model)
        elapsed = time.time() - start

        status_name = {
            cp_model.OPTIMAL: "OPTIMAL",
            cp_model.FEASIBLE: "FEASIBLE",
            cp_model.INFEASIBLE: "INFEASIBLE",
            cp_model.MODEL_INVALID: "MODEL_INVALID",
            cp_model.UNKNOWN: "UNKNOWN",
        }.get(status, "UNKNOWN")

        classes: list[ScheduledClass] = []
        # Add reserved cells first
        for sc in self._reserved.values():
            classes.append(sc)

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            for task, d, t, v in self._index:
                if solver.Value(v) == 1:
                    classes.append(
                        ScheduledClass(
                            section_id=task.section_id,
                            course_code=task.course_code,
                            faculty_id=task.faculty_id,
                            day=d,
                            slot=t,
                            is_lab=(task.kind == "LAB"),
                            batch_id=task.batch_id,
                            room=task.lab_room,
                            label=task.label,
                        )
                    )
                    if task.kind == "LAB":
                        classes.append(
                            ScheduledClass(
                                section_id=task.section_id,
                                course_code=task.course_code,
                                faculty_id=task.faculty_id,
                                day=d,
                                slot=t + 1,
                                is_lab=True,
                                batch_id=task.batch_id,
                                room=task.lab_room,
                                label=task.label,
                            )
                        )
            cost = int(solver.ObjectiveValue()) if penalties else None
            return Timetable(
                classes=classes,
                status=status_name,
                cost=cost,
                solve_time_sec=elapsed,
            )
        return Timetable(
            classes=classes,
            status=status_name,
            cost=None,
            solve_time_sec=elapsed,
            notes=[f"CP-SAT returned {status_name}"],
        )


def solve(req: TimetableRequest) -> Timetable:
    return TimetableSolver(req).solve()
