import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sheet as S

TODAY = date(2026, 10, 19)


def ev(d, type_, note=""):
    return {"date": d, "type": type_, "note": note, "message_id": None}


def app(co, events, role="Analyst", **kw):
    return {"id": co.lower(), "company": co, "role": role, "events": events, **kw}


def apps_rows(apps):
    return S.tabs(apps, TODAY)["Applications"]["values"][1:]


class TestTabs:
    def test_sort_phase_then_recency(self):
        apps = [
            app("Rej", [ev("2026-10-10", "applied"), ev("2026-10-18", "rejected")]),
            app("App", [ev("2026-10-17", "applied")]),
            app("Wd", [ev("2026-10-10", "applied"), ev("2026-10-18", "withdrawn")]),
            app("Int", [ev("2026-10-01", "applied"), ev("2026-10-05", "interviewing")]),
        ]
        assert [r[1] for r in apps_rows(apps)] == ["Int", "App", "Rej", "Wd"]

    def test_hyperlink_escapes_quotes(self):
        a = app("Co", [ev("2026-10-17", "applied")], role='The "Best" Role', job_url="https://x.test/a")
        assert apps_rows([a])[0][2] == '=HYPERLINK("https://x.test/a","The ""Best"" Role")'

    def test_injection_guard(self):
        a = app("Co", [ev("2026-10-17", "applied", "=cmd()")])
        assert apps_rows([a])[0][6] == "'=cmd()"

    def test_empty_role(self):
        a = app("Co", [ev("2026-10-17", "applied")], role="")
        assert apps_rows([a])[0][2] == "(role not stated)"

    def test_timeline_newest_first(self):
        a = app("Co", [ev("2026-10-01", "applied"), ev("2026-10-09", "interviewing")])
        b = app("Bo", [ev("2026-10-05", "applied")])
        dates = [r[0] for r in S.tabs([a, b], TODAY)["Timeline"]["values"][1:]]
        assert dates == ["2026-10-09", "2026-10-05", "2026-10-01"]

    def test_backgrounds_match_values(self):
        a = app("Co", [ev("2026-10-17", "applied")])
        b = app("Bo", [ev("2026-10-05", "applied"), ev("2026-10-06", "rejected")])
        t = S.tabs([a, b], TODAY)["Applications"]
        assert [len(r) for r in t["backgrounds"]] == [len(r) for r in t["values"]]


class TestPush:
    def _posts(self, monkeypatch):
        calls = []

        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self): return b"ok\n"

        monkeypatch.setattr(S.urllib.request, "urlopen", lambda *a, **k: calls.append(a) or Resp())
        return calls

    def test_unchanged_hash_skips_post(self, monkeypatch, tmp_path):
        calls = self._posts(monkeypatch)
        monkeypatch.setattr(S, "WEB_APP", "https://script.example/exec")
        apps = [app("Co", [ev("2026-10-17", "applied")])]
        hf = tmp_path / "sheet.sha256"
        assert S.push(apps, TODAY, hash_file=hf) is True
        assert S.push(apps, TODAY, hash_file=hf) is False
        assert len(calls) == 1

    def test_no_web_app_no_post(self, monkeypatch, tmp_path):
        calls = self._posts(monkeypatch)
        monkeypatch.setattr(S, "WEB_APP", None)
        assert S.push([], TODAY, hash_file=tmp_path / "h") is False
        assert calls == []
