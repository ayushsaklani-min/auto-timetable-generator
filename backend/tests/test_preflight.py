from app.data.bmsit_4th_sem import build_request
from app.core.preflight import validate
from app.models.domain import Course, CourseType, TimetableRequest


def test_bmsit_reference_passes_preflight():
    req = build_request()
    report = validate(req)
    assert report.ok, f"errors: {report.errors}"


def test_capacity_overflow_detected():
    req = build_request()
    # Pump up the workload past what fits in a week
    huge = Course(
        code="BOGUS",
        name="Impossible",
        credits=10,
        weekly_slots=200,
        type=CourseType.THEORY,
    )
    req.courses.append(huge)
    # Give it a faculty so it counts
    req.faculty[0].assignments.append(
        type(req.faculty[0].assignments[0])(course_code="BOGUS", section_id="A")
    )
    report = validate(req)
    assert not report.ok
    assert any("requires" in e for e in report.errors)


def test_elective_pool_too_small():
    req = build_request()
    # Empty the OT pool, which had 2 faculty
    for block in req.elective_blocks:
        for opt in block.options:
            if opt.course_code == "BCS405C":
                opt.faculty_pool = []
    report = validate(req)
    assert not report.ok


def test_elective_pool_needs_options_not_sections():
    req = build_request()
    block = req.elective_blocks[0]
    for opt in block.options:
        opt.faculty_pool = opt.faculty_pool[:1]
    report = validate(req)
    assert report.ok, report.errors
