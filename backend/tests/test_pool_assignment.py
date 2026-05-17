from app.core.preflight import validate
from app.core.verifier import verify
from app.draft.from_paste import build_request, default_skeleton
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
from app.solver.cpsat_solver import solve


def _course_sections(req, course_code: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for fac in req.faculty:
        sections = sorted(
            a.section_id for a in fac.assignments if a.course_code == course_code
        )
        if sections:
            out[fac.name] = sections
    return out


def test_build_request_uses_global_load_for_teacher_pools():
    req = build_request(
        default_skeleton(num_sections=6),
        "\n".join(
            [
                "NET, Networks, 3, theory, Dr Ramesh",
                "ML, Machine Learning, 3, theory, Dr Ramesh; Dr Priya; Dr Anitha",
            ]
        ),
    )

    ml_sections = _course_sections(req, "ML")
    assert ml_sections["Dr Ramesh"] == []
    assert ml_sections["Dr Priya"] == ["A", "C", "E"]
    assert ml_sections["Dr Anitha"] == ["B", "D", "F"]


def test_build_request_assigns_lab_batches_with_batch_ids():
    req = build_request(
        default_skeleton(num_sections=2),
        "LABX, Applied Lab, 1, lab, Dr Lab One; Dr Lab Two",
    )

    assignments = [
        a
        for fac in req.faculty
        for a in fac.assignments
        if a.course_code == "LABX"
    ]
    assert len(assignments) == 4
    assert all(a.batch_id for a in assignments)
    assert {(a.section_id, a.batch_id) for a in assignments} == {
        ("A", "A1"),
        ("A", "A2"),
        ("B", "B1"),
        ("B", "B2"),
    }


def test_build_request_splits_electives_evenly():
    elective_blocks = [
        {
            "id": "ELEC1",
            "name": "DMS/OT/AGT",
            "weekly_slot_count": 4,
            "locked_global_slots": [("MON", 2), ("TUE", 3), ("THU", 3), ("FRI", 3)],
            "options": [
                {"course_code": "DMS", "course_name": "DMS", "faculty": ["Dr DMS"]},
                {"course_code": "OT", "course_name": "OT", "faculty": ["Dr OT"]},
                {"course_code": "AGT", "course_name": "AGT", "faculty": ["Dr AGT"]},
            ],
        }
    ]
    req = build_request(
        default_skeleton(num_sections=6),
        "CORE, Core Subject, 3, theory, Dr Core",
        elective_blocks_raw=elective_blocks,
    )

    block = req.elective_blocks[0]
    sizes = sorted(len(opt.assigned_sections) for opt in block.options)
    assert sizes == [2, 2, 2]
    assert all(opt.assigned_faculty_id for opt in block.options)
    for opt in block.options:
        assigned = {
            a.section_id
            for fac in req.faculty
            if fac.id == opt.assigned_faculty_id
            for a in fac.assignments
            if a.course_code == opt.course_code
        }
        assert assigned == set(opt.assigned_sections)


def test_solver_allows_combined_section_activity_for_one_teacher():
    tc = TimeConfig(
        days=["MON"],
        slots_per_day=1,
        slot_timings=[Timing(start="09:00", end="10:00")],
        tea_break=BreakConfig(after_slot=99, duration_min=0),
        lunch_break=BreakConfig(after_slot=99, duration_min=0),
        saturday_rules=SaturdayRules(inactive_weeks=[]),
    )
    req = TimetableRequest(
        time_config=tc,
        sections=[
            Section(id="A", name="A", semester=1),
            Section(id="B", name="B", semester=1),
        ],
        courses=[
            Course(
                code="CRC",
                name="CRC",
                credits=0,
                weekly_slots=1,
                type=CourseType.ACTIVITY,
                combined_sections=True,
            )
        ],
        faculty=[
            Faculty(
                id="F1",
                name="CRC Coord",
                assignments=[
                    Assignment(course_code="CRC", section_id="A"),
                    Assignment(course_code="CRC", section_id="B"),
                ],
            )
        ],
        time_limit_sec=5,
    )

    report = validate(req)
    assert report.ok, report.errors
    tt = solve(req)
    assert tt.status in ("OPTIMAL", "FEASIBLE")
    verified = verify(req, tt)
    assert verified.ok, [v.model_dump() for v in verified.violations]
