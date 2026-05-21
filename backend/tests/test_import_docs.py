import io

import pytest

from app.draft.from_paste import Skeleton, build_request
from app.draft.import_docs import import_course_documents


def _xlsx_bytes(rows: list[list[object]]) -> bytes:
    openpyxl = pytest.importorskip("openpyxl")
    Workbook = openpyxl.Workbook
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def _workbook_bytes(sheets: dict[str, list[list[object]]]) -> bytes:
    openpyxl = pytest.importorskip("openpyxl")
    Workbook = openpyxl.Workbook
    workbook = Workbook()
    first = True
    for title, rows in sheets.items():
        sheet = workbook.active if first else workbook.create_sheet()
        first = False
        sheet.title = title
        for row in rows:
            sheet.append(row)
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def test_import_xlsx_course_faculty_sheet_to_step2_text():
    payload = _xlsx_bytes(
        [
            ["BMSIT 4th Sem Faculty Mapping"],
            [],
            [
                "Course Code",
                "Course Name",
                "Credits",
                "Type",
                "Sec A Faculty",
                "Sec B Faculty",
            ],
            ["BCS401", "Analysis & Design of Algorithms", 3, "theory", "Dr A", "Dr B"],
            ["BAI402_LAB", "AI Lab", 1, "lab pair=BCSL404", "same-as=BAI402", ""],
            ["DEPT_ACT", "Dept Activity", 0, "activity locked=FRI:5-7", "Dept Coord", ""],
        ]
    )

    result = import_course_documents(
        [("faculty-mapping.xlsx", payload)],
        section_ids=["A", "B"],
    )

    raw_text = result["raw_text"]
    assert "BCS401, Analysis & Design of Algorithms, 3, theory, Dr A; Dr B" in raw_text
    assert "BAI402_LAB, AI Lab, 1, lab pair=BCSL404, same-as=BAI402" in raw_text
    assert "DEPT_ACT, Dept Activity, 0, activity locked=FRI:5-7, Dept Coord" in raw_text
    assert result["summary"]["imported_courses"] == 3


def test_import_adaptive_multisheet_faculty_course_workbook():
    payload = _workbook_bytes(
        {
            "Faculty & Courses": [
                ["FACULTY NAME & THEIR COURSES"],
                ["Faculty Name", "Course Name", "Course Code", "Section(s)"],
                ["Dr A", "PCC- Analysis & Design of Algorithms", "BCS401", "Sem A"],
                ["Dr B", "PCC- Analysis & Design of Algorithms", "BCS401", "Sem B"],
                ["Prof AI A1", "IPCC- Artificial Intelligence", "BAI402", "Sem A"],
                ["Prof AI A2", "IPCC- Artificial Intelligence", "BAI402", "Sem A"],
                ["Prof AI B1", "IPCC- Artificial Intelligence", "BAI402", "Sem B"],
                ["Prof DB A1", "IPCC- Database Management Systems", "BCS403", "Sem A"],
                ["Prof DB B1", "IPCC- Database Management Systems", "BCS403", "Sem B"],
                ["Prof ADA A1", "PCCL- Analysis & Design of Algorithms Lab", "BCSL404", "Sem A"],
                ["Prof ADA B1", "PCCL- Analysis & Design of Algorithms Lab", "BCSL404", "Sem B"],
                ["Prof English", "English Communication Skill - II", "BENGDIP2", "All Sems"],
            ],
            "Courses & Course Codes": [
                ["COURSES WITH THEIR COURSE CODES"],
                ["Course Code", "Course Name", "Type", "Credits"],
                ["BCS401", "PCC- Analysis & Design of Algorithms", "PCC", "3"],
                ["BAI402", "IPCC- Artificial Intelligence", "IPCC", "4(3+1)"],
                ["BCS403", "IPCC- Database Management Systems", "IPCC", "4(3+1)"],
                ["BCSL404", "PCCL- Analysis & Design of Algorithms Lab", "PCCL", "1"],
                ["BENGDIP2", "English Communication Skill - II", "BENG", "0"],
                ["TOTAL CREDITS", "", "", ""],
            ],
        }
    )

    result = import_course_documents(
        [("adaptive.xlsx", payload)],
        section_ids=["A", "B"],
    )

    raw_text = result["raw_text"]
    assert "BCS401, Analysis & Design of Algorithms, 3, theory, Dr A; Dr B" in raw_text
    assert "BAI402, Artificial Intelligence, 3, theory" in raw_text
    assert "BAI402_LAB, Artificial Intelligence Lab, 1, lab pair=BCSL404" in raw_text
    assert "BCS403_LAB, Database Management Systems Lab, 1, lab" in raw_text
    assert "BCSL404, Analysis & Design of Algorithms Lab, 1, lab pair=BAI402_LAB" in raw_text
    assert "BENGDIP2" not in raw_text
    assert "TOTAL_CREDITS" not in raw_text


def test_section_order_faculty_list_is_preserved_in_draft_request():
    skeleton = Skeleton(
        days=["MON"],
        slots_per_day=2,
        slot_timings=[("08:30", "09:25"), ("09:25", "10:20")],
        tea_after_slot=2,
        tea_minutes=20,
        lunch_after_slot=2,
        lunch_minutes=55,
        section_ids=["A", "B"],
        batches_per_section=2,
        classroom_by_section={"A": "", "B": ""},
        inactive_sat_weeks=[],
        sat_locks=[],
        semester=4,
    )

    req = build_request(
        skeleton,
        "BCS401, Analysis & Design of Algorithms, 3, theory, Dr A; Dr B",
    )

    assignments = {
        assignment.section_id: faculty.name
        for faculty in req.faculty
        for assignment in faculty.assignments
        if assignment.course_code == "BCS401"
    }
    assert assignments == {"A": "Dr A", "B": "Dr B"}
