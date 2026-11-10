"""record_prepared: tracker update after a package send (no SMTP)."""

import pytest

import applications
from send_digest import NAME
from send_package import pick_required, record_prepared

PKG = "output/OurCrowd"


def rec(apps, mid="<m1@x>", today="2026-10-18"):
    return record_prepared(apps, PKG, "OurCrowd", "Analyst", "https://j/1", mid, today)


class TestRecordPrepared:
    def test_first_send_creates_app_with_prepared(self, tmp_path):
        path = tmp_path / "applications.json"
        apps = applications.load(path)
        rec(apps)
        applications.save(apps, path)
        (app,) = applications.load(path)
        assert app["package"] == PKG
        assert app["job_url"] == "https://j/1"
        assert [e["type"] for e in app["events"]] == ["prepared"]
        assert app["events"][0]["message_id"] == "<m1@x>"

    def test_second_send_adds_no_second_prepared(self, tmp_path):
        path = tmp_path / "applications.json"
        apps = applications.load(path)
        rec(apps)
        rec(apps, mid="<m2@x>", today="2026-10-19")
        assert len(apps) == 1
        assert [e["type"] for e in apps[0]["events"]] == ["prepared"]

    def test_existing_app_gets_prepared_not_duplicate(self):
        apps = []
        existing = applications.create(apps, "OurCrowd", "Analyst", package=PKG)
        applications.add_event(existing, "2026-10-20", "acknowledged")
        rec(apps)
        assert len(apps) == 1
        assert [e["type"] for e in apps[0]["events"]] == ["prepared", "acknowledged"]


class TestPickRequired:
    def test_suffixed_preferred_over_bare(self, tmp_path):
        for n in (f"{NAME} - CV - Acme.pdf", f"{NAME} - CV.pdf"):
            (tmp_path / n).write_bytes(b"x")
        assert pick_required(tmp_path, "CV").name == f"{NAME} - CV - Acme.pdf"

    def test_bare_fallback(self, tmp_path):
        (tmp_path / f"{NAME} - CL.pdf").write_bytes(b"x")
        assert pick_required(tmp_path, "CL").name == f"{NAME} - CL.pdf"

    def test_ambiguous_exits_1(self, tmp_path):
        for c in ("Acme", "Beta"):
            (tmp_path / f"{NAME} - CV - {c}.pdf").write_bytes(b"x")
        with pytest.raises(SystemExit) as e:
            pick_required(tmp_path, "CV")
        assert e.value.code == 1

    def test_missing_exits_1(self, tmp_path):
        with pytest.raises(SystemExit) as e:
            pick_required(tmp_path, "CV")
        assert e.value.code == 1
