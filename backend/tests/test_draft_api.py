from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _payload(time_limit_sec: int) -> dict:
    return {
        "skeleton": {
            "days": ["MON", "TUE", "WED", "THU", "FRI", "SAT"],
            "slots_per_day": 7,
            "slot_timings": [
                ["08:30", "09:25"],
                ["09:25", "10:20"],
                ["10:40", "11:35"],
                ["11:35", "12:30"],
                ["13:25", "14:20"],
                ["14:20", "15:15"],
                ["15:15", "16:10"],
            ],
            "tea_after_slot": 2,
            "tea_minutes": 20,
            "lunch_after_slot": 4,
            "lunch_minutes": 55,
            "section_ids": ["A"],
            "batches_per_section": 2,
            "classroom_by_section": {},
            "inactive_sat_weeks": [1, 3],
            "sat_locks": [],
            "semester": 4,
        },
        "courses_text": "BCS401, Analysis & Design of Algorithms, 3, theory, Dr Sample",
        "elective_blocks": [],
        "time_limit_sec": time_limit_sec,
    }


def test_draft_preview_caps_long_solver_limit():
    resp = client.post("/draft/preview", json=_payload(60))
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["request"]["time_limit_sec"] == 20


def test_draft_preview_preserves_shorter_solver_limit():
    resp = client.post("/draft/preview", json=_payload(10))
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["request"]["time_limit_sec"] == 10
