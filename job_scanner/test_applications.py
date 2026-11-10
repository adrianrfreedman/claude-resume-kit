import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import applications as A

TODAY = date(2026, 10, 18)


def app_with(*events):
    app = {"id": "x", "company": "X", "role": "Y", "events": []}
    for d, t in events:
        A.add_event(app, d, t)
    return app


class TestStore:
    def test_missing_file_is_empty(self, tmp_path):
        assert A.load(tmp_path / "nope.json") == []

    def test_round_trip_atomic(self, tmp_path):
        p = tmp_path / "sub" / "apps.json"
        apps = []
        a = A.create(apps, "Námina", "Médical Manager", job_url="u")
        A.add_event(a, "2026-10-01", "applied", "n", "<m1>")
        A.save(apps, p)
        assert A.load(p) == apps
        assert "Námina" in p.read_text(encoding="utf-8")
        assert [f.name for f in tmp_path.glob("sub/*")] == ["apps.json"]


class TestIds:
    def test_slug(self):
        assert A.make_id("Navina", "Medical Manager", []) == "navina-medical-manager"

    def test_slug_max_len(self):
        assert len(A.make_id("C" * 50, "R" * 50, [])) <= 60

    def test_empty_role_company_only(self):
        apps = []
        assert [A.create(apps, "Initech", "")["id"] for _ in range(2)] == ["initech", "initech-2"]

    def test_collision(self):
        apps = []
        ids = [A.create(apps, "Navina", "Medical Manager")["id"] for _ in range(3)]
        assert ids == ["navina-medical-manager", "navina-medical-manager-2", "navina-medical-manager-3"]
        assert A.find(apps, "navina-medical-manager-2") is apps[1]
        assert A.find(apps, "zzz") is None


class TestEvents:
    def test_dedupe_same_message_and_type(self):
        a = app_with()
        assert A.add_event(a, "2026-10-01", "applied", message_id="<m>")
        assert not A.add_event(a, "2026-10-01", "applied", message_id="<m>")
        assert len(a["events"]) == 1

    def test_same_message_two_types(self):
        a = app_with()
        assert A.add_event(a, "2026-10-01", "applied", message_id="<m>")
        assert A.add_event(a, "2026-10-01", "acknowledged", message_id="<m>")

    def test_same_message_two_apps(self):
        a, b = app_with(), app_with()
        assert A.add_event(a, "2026-10-01", "applied", message_id="<m>")
        assert A.add_event(b, "2026-10-01", "applied", message_id="<m>")

    def test_empty_message_id_not_deduped(self):
        a = app_with()
        assert A.add_event(a, "2026-10-01", "note")
        assert A.add_event(a, "2026-10-01", "note")

    def test_sorted_stable(self):
        a = app_with()
        A.add_event(a, "2026-10-05", "applied")
        A.add_event(a, "2026-10-01", "prepared")
        A.add_event(a, "2026-10-05", "acknowledged")
        assert [e["type"] for e in a["events"]] == ["prepared", "applied", "acknowledged"]

    def test_clears_summary(self):
        a = app_with()
        a["summary"] = "old"
        A.add_event(a, "2026-10-01", "applied")
        assert "summary" not in a

    def test_records_clock_time(self, monkeypatch):
        monkeypatch.setattr(A, "CLOCK", lambda: datetime(2026, 10, 19, 8, 30, 5))
        a = app_with()
        A.add_event(a, "2026-10-01", "applied")
        assert a["events"][0]["recorded"] == "2026-10-19T08:30:05"

    def test_unknown_type(self):
        with pytest.raises(ValueError):
            A.add_event(app_with(), "2026-10-01", "bogus")


class TestStatus:
    def test_no_events_prepared(self):
        assert A.status(app_with(), TODAY) == "prepared"
        assert A.days_since(app_with(), TODAY) is None

    def test_ghosted_at_30_not_29(self):
        assert A.status(app_with(("2026-09-18", "applied")), TODAY) == "ghosted"
        assert A.status(app_with(("2026-09-19", "applied")), TODAY) == "applied"

    def test_note_resets_clock_but_not_status(self):
        a = app_with(("2026-09-01", "applied"), ("2026-10-10", "note"))
        assert A.status(a, TODAY) == "applied"
        assert A.last_event(a)["type"] == "note"
        assert A.days_since(a, TODAY) == 8

    def test_prepared_never_ghosts(self):
        assert A.status(app_with(("2026-01-01", "prepared")), TODAY) == "prepared"

    @pytest.mark.parametrize("t", ["rejected", "withdrawn", "offer"])
    def test_terminal_never_ghosts(self, t):
        assert A.status(app_with(("2026-01-01", "applied"), ("2026-01-02", t)), TODAY) == t

    def test_interviewing_and_ack_ghost(self):
        for t in ("acknowledged", "interviewing"):
            assert A.status(app_with(("2026-01-01", t)), TODAY) == "ghosted"


class TestAutoApplied:
    def test_auto_applied_moves_back_to_earlier_event(self):
        a = app_with()
        A.add_event(a, "2026-08-06", "applied", auto=True)
        A.add_event(a, "2026-08-06", "rejected")
        A.add_event(a, "2026-07-23", "interviewing")
        assert [(e["date"], e["type"]) for e in a["events"]] == [
            ("2026-07-23", "applied"), ("2026-07-23", "interviewing"), ("2026-08-06", "rejected")]
        assert a["events"][0]["auto"] is True

    def test_non_auto_applied_not_moved(self):
        a = app_with()
        A.add_event(a, "2026-08-06", "applied")
        A.add_event(a, "2026-07-23", "interviewing")
        assert [(e["date"], e["type"]) for e in a["events"]] == [
            ("2026-07-23", "interviewing"), ("2026-08-06", "applied")]
        assert "auto" not in a["events"][1]


class TestStatusPreparedSameDay:
    def test_applied_outranks_same_day_prepared(self):
        import applications as A
        from datetime import date
        app = {"id": "x", "company": "c", "role": "r", "events": []}
        A.add_event(app, "2026-11-08", "prepared", "cv ready")
        A.add_event(app, "2026-11-08", "note", "n")
        A.add_event(app, "2026-11-08", "applied", "sent")
        assert A.status(app, date(2026, 11, 8)) == "applied"
