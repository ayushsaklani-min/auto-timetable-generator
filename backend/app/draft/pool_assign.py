"""Shared helpers for section/batch pool assignment."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, MutableMapping, Sequence


Slot = tuple[str, int]


@dataclass(frozen=True)
class AssignmentTarget:
    """A unit that needs one teacher assignment from a pool."""

    section_id: str
    batch_id: str | None = None
    required_slots: tuple[Slot, ...] = ()
    load_units: int = 1
    label: str = ""

    def describe(self) -> str:
        if self.batch_id:
            return f"{self.section_id}/{self.batch_id}"
        return self.section_id


class PoolAssignmentError(ValueError):
    """Raised when no teacher in a pool can take a target."""


def even_groups(keys: Sequence[str], items: Sequence[str]) -> dict[str, list[str]]:
    """Split items across keys as evenly as possible, preserving order."""
    out = {key: [] for key in keys}
    counts = defaultdict(int)
    order = {key: idx for idx, key in enumerate(keys)}
    for item in items:
        key = min(keys, key=lambda current: (counts[current], order[current]))
        out[key].append(item)
        counts[key] += 1
    return out


def assign_targets(
    teacher_ids: Sequence[str],
    targets: Sequence[AssignmentTarget],
    global_loads: MutableMapping[str, int],
    unavailable_by_teacher: Mapping[str, set[Slot]] | None = None,
    teacher_labels: Mapping[str, str] | None = None,
) -> list[tuple[AssignmentTarget, str]]:
    """Assign each target to the least-loaded teacher that can take it."""
    unique_teacher_ids: list[str] = []
    seen: set[str] = set()
    for teacher_id in teacher_ids:
        if not teacher_id or teacher_id in seen:
            continue
        seen.add(teacher_id)
        unique_teacher_ids.append(teacher_id)

    if not unique_teacher_ids:
        return []

    unavailable = unavailable_by_teacher or {}
    labels = teacher_labels or {}
    subject_loads: dict[str, int] = defaultdict(int)
    teacher_order = {teacher_id: idx for idx, teacher_id in enumerate(unique_teacher_ids)}
    assignments: list[tuple[AssignmentTarget, str]] = []

    for target in targets:
        candidates: list[tuple[int, int, int, str]] = []
        conflicts: list[tuple[str, list[Slot]]] = []
        for teacher_id in unique_teacher_ids:
            blocked = unavailable.get(teacher_id, set())
            overlap = sorted(set(target.required_slots) & blocked)
            if overlap:
                conflicts.append((teacher_id, overlap))
                continue
            candidates.append(
                (
                    int(global_loads.get(teacher_id, 0)),
                    subject_loads[teacher_id],
                    teacher_order[teacher_id],
                    teacher_id,
                )
            )

        if not candidates:
            if conflicts:
                parts = [
                    f"{labels.get(teacher_id, teacher_id)} blocked at "
                    + ", ".join(f"{day}-{slot}" for day, slot in slots)
                    for teacher_id, slots in conflicts
                ]
                raise PoolAssignmentError(
                    f"No teacher in the pool can take {target.label or target.describe()}: "
                    + "; ".join(parts)
                )
            raise PoolAssignmentError(
                f"No teacher in the pool can take {target.label or target.describe()}"
            )

        _, _, _, picked_teacher = min(candidates)
        assignments.append((target, picked_teacher))
        global_loads[picked_teacher] = int(global_loads.get(picked_teacher, 0)) + target.load_units
        subject_loads[picked_teacher] += target.load_units

    return assignments


def slots_tuple(slots: Iterable[Slot] | None) -> tuple[Slot, ...]:
    return tuple(slots or ())
