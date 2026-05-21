import pytest

from app.data.bmsit_4th_sem import build_request
from app.core.preflight import validate
from app.core.verifier import verify
from app.solver.cpsat_solver import solve


@pytest.mark.slow
def test_bmsit_solves_and_verifies():
    req = build_request(time_limit_sec=60)
    pf = validate(req)
    assert pf.ok, f"preflight errors: {pf.errors}"

    tt = solve(req)
    assert tt.status in ("OPTIMAL", "FEASIBLE"), f"solver: {tt.status} {tt.notes}"

    report = verify(req, tt)
    assert report.ok, f"violations: {[v.model_dump() for v in report.violations[:5]]}"


def test_minimal_problem_solves():
    """Tiny synthetic problem — 1 section, 1 theory course, 2 slots needed."""
    from app.models.domain import (
        Assignment,
        BreakConfig,
        Course,
        CourseType,
        Faculty,
        SaturdayRules,
        Section,
        TimeConfig,
        Timing,
        TimetableRequest,
    )

    tc = TimeConfig(
        days=["MON", "TUE"],
        slots_per_day=3,
        slot_timings=[Timing(start="9", end="10")] * 3,
        tea_break=BreakConfig(after_slot=99, duration_min=0),
        lunch_break=BreakConfig(after_slot=99, duration_min=0),
        saturday_rules=SaturdayRules(inactive_weeks=[]),
    )
    req = TimetableRequest(
        time_config=tc,
        sections=[Section(id="A", name="A", semester=1)],
        courses=[Course(code="X", name="X", credits=2, weekly_slots=2, type=CourseType.THEORY)],
        faculty=[
            Faculty(
                id="F1",
                name="Solo Prof",
                assignments=[Assignment(course_code="X", section_id="A")],
            )
        ],
        time_limit_sec=10,
    )
    tt = solve(req)
    assert tt.status in ("OPTIMAL", "FEASIBLE")
    assert sum(1 for c in tt.classes if c.course_code == "X") == 2


def test_waste_objective_fills_post_lunch_gap_before_late_slot():
    """A movable class should fill the open post-lunch gap before using later slots."""
    from app.models.domain import (
        Assignment,
        BreakConfig,
        Course,
        CourseType,
        Faculty,
        SaturdayRules,
        Section,
        TimeConfig,
        Timing,
        TimetableRequest,
    )

    tc = TimeConfig(
        days=["MON"],
        slots_per_day=7,
        slot_timings=[Timing(start="9", end="10")] * 7,
        tea_break=BreakConfig(after_slot=99, duration_min=0),
        lunch_break=BreakConfig(after_slot=4, duration_min=0),
        saturday_rules=SaturdayRules(inactive_weeks=[]),
    )
    req = TimetableRequest(
        time_config=tc,
        sections=[Section(id="A", name="A", semester=1)],
        courses=[
            Course(
                code="LOCKED",
                name="Locked Activity",
                credits=0,
                weekly_slots=5,
                type=CourseType.ACTIVITY,
                locked_day="MON",
                locked_slots=[1, 2, 3, 4, 6],
            ),
            Course(
                code="X",
                name="Theory",
                credits=3,
                weekly_slots=1,
                type=CourseType.THEORY,
            ),
        ],
        faculty=[
            Faculty(
                id="F1",
                name="Solo Prof",
                assignments=[Assignment(course_code="X", section_id="A")],
            )
        ],
        time_limit_sec=10,
    )

    tt = solve(req)
    assert tt.status in ("OPTIMAL", "FEASIBLE")
    assert [(c.day, c.slot) for c in tt.classes if c.course_code == "X"] == [
        ("MON", 5)
    ]
