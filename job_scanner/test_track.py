import email
import email.policy
import datetime as _dt
import json
import sys
from email.message import EmailMessage
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import applications as A
import track as T

DOM = T.DOMAIN  # per-candidate message-id domain from config.md

ACK_ID = f"<ack-abc123.20261018T100000@{DOM}>"


def mk(subject="Hi", mid="<m1@x>", body="hello", to=T.SENDER, cc=None,
       irt=None, refs=None, date="Wed, 02 Sep 2026 10:00:00 +0300"):
    m = EmailMessage()
    m["From"] = T.CANDIDATE  # the candidate address from config.md, whichever clone runs the tests
    m["To"] = to
    if cc:
        m["Cc"] = cc
    m["Subject"] = subject
    m["Message-ID"] = mid
    m["Date"] = date
    if irt:
        m["In-Reply-To"] = irt
    if refs:
        m["References"] = refs
    m.set_content(body)
    return m


def raw(m):
    return m.as_bytes()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "STATE", tmp_path / "state")
    monkeypatch.setattr(T, "DIGESTS", tmp_path / "digests")
    monkeypatch.setattr(T, "OUTPUT", tmp_path / "output")
    monkeypatch.setattr(T, "KIT", tmp_path)
    monkeypatch.setattr(T, "APPS", tmp_path / "apps.json")
    (tmp_path / "digests").mkdir()
    (tmp_path / "output").mkdir()
    sent = []
    monkeypatch.setattr(T, "send_mail", sent.append)
    monkeypatch.setattr(T, "ask_haiku", lambda p, s: {"summary": "Did a thing."} if "summary" in s["properties"] else pytest.fail("no stub"))
    return tmp_path, sent


def stub(monkeypatch, answer):
    """Stub Haiku: answer for the main call, a fixed summary for summaries."""
    calls = []

    def fake(prompt, schema):
        calls.append(prompt)
        return {"summary": "Summary."} if "summary" in schema["properties"] else answer

    monkeypatch.setattr(T, "ask_haiku", fake)
    return calls


def run_saved(m, ledger=None):
    """process() with the store loaded from disk, as run_items does."""
    kind, tag, fid = T.classify(m)
    ledger = {} if ledger is None else ledger
    apps = A.load(T.APPS)
    res = T.process(raw(m), kind, tag, fid, ledger, apps, False)
    return ledger, res


class TestClassify:
    @pytest.mark.parametrize("kind", ["scan", "package", "tracker", "ack"])
    def test_tagged_in_reply_to(self, kind):
        m = mk(irt=f"<{kind}-some_tag-1.20261018T100000@{DOM}>")
        assert T.classify(m)[:2] == (kind, "some_tag-1")

    def test_reply_to_alias_still_uses_tag(self):
        # Our emails set Reply-To: +jobs, so replies are addressed to the alias; the tag must win.
        m = mk(to=T.ALIAS, irt=f"<package-x.20261018T100000@{DOM}>")
        assert T.classify(m)[0] == "package"

    def test_scan_tag_with_date(self):
        m = mk(irt=f"<scan-2026-09-02.20260902T080000@{DOM}>")
        assert T.classify(m)[:2] == ("scan", "2026-09-02")

    def test_tag_from_references(self):
        m = mk(refs=f"<other@x> <tracker-2026-10-18.20261018T083000@{DOM}>")
        assert T.classify(m)[0] == "tracker"

    def test_in_reply_to_wins(self):
        m = mk(irt=f"<ack-a.1@{DOM}>", refs=f"<scan-b.1@{DOM}>")
        assert T.classify(m)[0] == "ack"

    def test_subject_fallback(self):
        m = mk(subject="Re: Application package: OurCrowd Portfolio Analyst")
        assert T.classify(m)[:2] == ("package", None)

    def test_subject_fallback_needs_re(self):
        assert T.classify(mk(subject="Application package: OurCrowd"))[0] == "ignore"

    def test_alias_to_and_cc(self):
        assert T.classify(mk(to=T.ALIAS))[0] == "alias"
        assert T.classify(mk(cc=f"Jane <{T.ALIAS}>"))[0] == "alias"

    def test_ignore(self):
        assert T.classify(mk())[0] == "ignore"

    @pytest.mark.parametrize("tag", ["2026-09-02", "2026-05-31_morning", "acme_portfolio_analyst", "a1b2c3d4e5"])
    def test_tag_charset_ok(self, tag):
        assert T.classify(mk(irt=f"<tracker-{tag}.1@{DOM}>"))[:2] == ("tracker", tag)

    def test_tag_with_slash_not_tagged(self):
        assert T.classify(mk(irt=f"<tracker-a/b.1@{DOM}>"))[0] == "ignore"

    def test_own_ack_ignored(self):
        # Sender == candidate: our ack replying to their reply must not be re-ingested.
        m = mk(mid=f"<ack-b.2@{DOM}>", irt="<reply@mail.gmail.com>", refs=f"<ack-a.1@{DOM}> <reply@mail.gmail.com>")
        assert T.classify(m)[0] == "ignore"


class TestScan:
    def sidecar(self, tmp, tag="2026-09-02"):
        jobs = [
            {"n": 1, "scan_id": "s1", "company": "Teva", "title": "Data Analyst", "url": "http://t"},
            {"n": 2, "scan_id": "s2", "company": "Immunai", "title": "Scientist", "url": "http://i"},
        ]
        (tmp / "digests" / f"digest_{tag}.json").write_text(json.dumps(jobs))

    def test_applied_event_and_ack(self, env, monkeypatch):
        tmp, sent = env
        self.sidecar(tmp)
        calls = stub(monkeypatch, {"jobs": [1], "understood": True})
        m = mk(subject="Re: Job digest", irt=f"<scan-2026-09-02.20260902T080000@{DOM}>",
               body="Applied to the Teva one\n\nOn Wed wrote:\n> old")
        ledger, res = run_saved(m)
        apps = A.load(T.APPS)
        assert apps[0]["scan_id"] == "s1" and apps[0]["job_url"] == "http://t"
        assert [(e["type"], e["date"], e["message_id"]) for e in apps[0]["events"]] == [("applied", "2026-09-02", "<m1@x>")]
        assert apps[0]["summary"] == "Summary."
        assert "Teva one" in calls[0] and "old" not in calls[0]
        assert ledger["<m1@x>"]["status"] == "done"
        assert ledger["<m1@x>"]["events"] == [["teva-data-analyst", "applied"]]
        ack = sent[0]
        assert ack["To"] == T.CANDIDATE and ack["Cc"] is None
        assert ack["In-Reply-To"] == "<m1@x>" and ack["Subject"] == "Re: Job digest"
        assert ack["Message-ID"].startswith("<ack-") and ledger["<m1@x>"]["ack_id"] == ack["Message-ID"]
        body = ack.get_content()
        assert "Recorded: Applied — Data Analyst at Teva (from the 2 Sep scan)." in body
        assert "Wrong? Reply to this email to correct it." in body

    def test_existing_app_by_scan_id(self, env, monkeypatch):
        tmp, _ = env
        self.sidecar(tmp)
        apps = []
        A.create(apps, "Teva", "Analyst", scan_id="s1")
        A.save(apps, T.APPS)
        stub(monkeypatch, {"jobs": [1], "understood": True})
        run_saved(mk(irt=f"<scan-2026-09-02.1@{DOM}>"))
        assert len(A.load(T.APPS)) == 1

    def test_missing_sidecar_unusable(self, env, monkeypatch):
        _, sent = env
        stub(monkeypatch, {})
        ledger, _ = run_saved(mk(irt=f"<scan-2020-01-01.1@{DOM}>"))
        assert ledger["<m1@x>"]["status"] == "unusable"
        assert "job list" in sent[0].get_content()

    def test_not_understood_unusable(self, env, monkeypatch):
        tmp, sent = env
        self.sidecar(tmp)
        stub(monkeypatch, {"jobs": [], "understood": False})
        ledger, _ = run_saved(mk(irt=f"<scan-2026-09-02.1@{DOM}>"))
        assert ledger["<m1@x>"]["status"] == "unusable"
        assert T.UNUSABLE_ACK in sent[0].get_content()
        assert A.load(T.APPS) == []


class TestPackage:
    def folder(self, tmp):
        d = tmp / "output" / "OurCrowd"
        d.mkdir()
        (d / "session_ourcrowd_portfolio_analyst.md").write_text("s")
        return d

    def tagged(self):
        return f"<package-ourcrowd_portfolio_analyst.20261001T090000@{DOM}>"

    def test_applied(self, env, monkeypatch):
        tmp, sent = env
        self.folder(tmp)
        stub(monkeypatch, {"intent": "applied"})
        ledger, _ = run_saved(mk(irt=self.tagged(), body="I applied!"))
        a = A.load(T.APPS)[0]
        assert a["package"] == "output/OurCrowd" and a["company"] == "OurCrowd"
        assert a["role"] == "ourcrowd_portfolio_analyst"
        assert a["events"][0]["type"] == "applied"
        assert "Recorded: Applied" in sent[0].get_content()

    def test_edits_runs_revise_no_ack(self, env, monkeypatch):
        tmp, sent = env
        d = self.folder(tmp)
        stub(monkeypatch, {"intent": "edits"})
        cmds = []

        class P:
            returncode, stdout, stderr = 0, "", ""

        monkeypatch.setattr(T, "run_claude", lambda cmd, timeout: (cmds.append((cmd, timeout)), P)[1])
        ledger, _ = run_saved(mk(irt=self.tagged(), body="Please shorten the CL"))
        cmd, timeout = cmds[0]
        saved = list((d / "replies").glob("reply_*.md"))
        assert len(saved) == 1 and "intent: edits\n" in saved[0].read_text()
        assert cmd == ["claude", "-p",
                       f"/revise-package output/OurCrowd/session_ourcrowd_portfolio_analyst.md "
                       f"--reply output/OurCrowd/replies/{saved[0].name} --unattended",
                       "--permission-mode", "acceptEdits", "--allowedTools", *T.revise_tools("output/OurCrowd")]
        assert timeout == 1800
        assert sent == []
        assert ledger["<m1@x>"]["status"] == "done"
        assert ledger["<m1@x>"]["intent"] == "edits" and ledger["<m1@x>"]["time"]

    def test_both_applies_and_acks(self, env, monkeypatch):
        tmp, sent = env
        d = self.folder(tmp)
        stub(monkeypatch, {"intent": "both"})

        class P:
            returncode, stdout, stderr = 0, "", ""

        cmds = []
        monkeypatch.setattr(T, "run_claude", lambda cmd, timeout: (cmds.append(cmd), P)[1])
        run_saved(mk(irt=self.tagged()))
        assert len(sent) == 1 and len(cmds) == 1
        assert A.load(T.APPS)[0]["events"][0]["type"] == "applied"
        assert "intent: both\n" in next((d / "replies").glob("reply_*.md")).read_text()

    def test_revise_failure_saves_output(self, env, monkeypatch):
        tmp, _ = env
        self.folder(tmp)
        stub(monkeypatch, {"intent": "edits"})

        class P:
            returncode, stdout, stderr = 1, "out", "boom"

        monkeypatch.setattr(T, "run_claude", lambda cmd, timeout: P)
        with pytest.raises(T.Failure):
            run_saved(mk(irt=self.tagged()))
        assert (tmp / "state" / "failed" / "m1_x.claude.txt").exists()

    def test_subject_fallback_folder(self, env, monkeypatch):
        tmp, _ = env
        self.folder(tmp)
        stub(monkeypatch, {"intent": "applied"})
        run_saved(mk(subject="Re: Application package: ourcrowd Portfolio Analyst"))
        assert A.load(T.APPS)[0]["package"] == "output/OurCrowd"

    def test_other_records_nothing(self, env, monkeypatch):
        tmp, sent = env
        self.folder(tmp)
        stub(monkeypatch, {"intent": "other"})
        ledger, _ = run_saved(mk(irt=self.tagged(), body="thanks"))
        assert sent == [] and ledger["<m1@x>"]["status"] == "unusable"

    def test_dry_run_writes_nothing(self, env, monkeypatch):
        tmp, sent = env
        d = self.folder(tmp)
        stub(monkeypatch, {"intent": "both"})
        monkeypatch.setattr(T, "run_claude", lambda *a: pytest.fail("revise ran"))
        m = mk(irt=self.tagged())
        T.process(raw(m), *T.classify(m), {}, [], True)
        assert not (d / "replies").exists() and sent == [] and not T.APPS.exists()


class TestEvents:
    def test_alias_new_acknowledged_adds_applied(self, env, monkeypatch):
        _, sent = env
        calls = stub(monkeypatch, {"relevant": True, "undo_previous": False, "events": [
            {"app_id": "new", "company": "Acme Diagnostics", "role": "Data Analyst",
             "type": "acknowledged", "date": "2026-09-30", "note": "Thanks for applying"}]})
        m = mk(subject="Fwd: Thanks", to=T.ALIAS,
               body="---------- Forwarded message ---------\nThanks for applying")
        ledger, _ = run_saved(m)
        a = A.load(T.APPS)[0]
        assert [(e["type"], e["date"]) for e in a["events"]] == [("applied", "2026-09-30"), ("acknowledged", "2026-09-30")]
        assert ledger["<m1@x>"]["events"] == [["acme-diagnostics-data-analyst", "applied"],
                                               ["acme-diagnostics-data-analyst", "acknowledged"]]
        assert "Forwarded message" in calls[0]  # full body, not strip_quoted
        assert "Recorded: Acknowledged — Data Analyst at Acme Diagnostics: Thanks for applying." in sent[0].get_content()

    def test_unknown_app_id_is_new(self, env, monkeypatch):
        env
        stub(monkeypatch, {"relevant": True, "undo_previous": False, "events": [
            {"app_id": "ghost", "company": "X", "role": "Y", "type": "note", "date": "2026-10-01", "note": "n"}]})
        run_saved(mk(irt=f"<tracker-2026-10-18.1@{DOM}>"))
        assert A.load(T.APPS)[0]["id"] == "x-y"

    def test_two_new_events_same_job_one_app(self, env, monkeypatch):
        env
        stub(monkeypatch, {"relevant": True, "undo_previous": False, "events": [
            {"app_id": "new", "company": "Initech", "role": "Junior Business Development Manager",
             "type": "applied", "date": "2026-10-01", "note": ""},
            {"app_id": "new", "company": " initech.", "role": "junior business development manager ",
             "type": "rejected", "date": "2026-10-10", "note": "No"}]})
        run_saved(mk(subject="Fwd: x", to=T.ALIAS, body="b"))
        apps = A.load(T.APPS)
        assert len(apps) == 1
        assert [e["type"] for e in apps[0]["events"]] == ["applied", "rejected"]

    def test_new_matching_existing_app_reuses(self, env, monkeypatch):
        apps = []
        a = A.create(apps, "Teva", "Data Analyst")
        A.add_event(a, "2026-09-01", "applied", "", "<old>")
        A.save(apps, T.APPS)
        stub(monkeypatch, {"relevant": True, "undo_previous": False, "events": [
            {"app_id": "new", "company": "TEVA", "role": "data analyst", "type": "interviewing",
             "date": "2026-10-20", "note": "Thu"}]})
        run_saved(mk(subject="Fwd: x", to=T.ALIAS, body="b"))
        apps = A.load(T.APPS)
        assert len(apps) == 1
        assert [e["type"] for e in apps[0]["events"]] == ["applied", "interviewing"]

    def test_new_app_from_note_gets_applied(self, env, monkeypatch):
        env
        stub(monkeypatch, {"relevant": True, "undo_previous": False, "events": [
            {"app_id": "new", "company": "Acme", "role": "Analyst", "type": "note",
             "date": "2026-10-01", "note": "Recruiter call"}]})
        run_saved(mk(subject="Fwd: x", to=T.ALIAS, body="b"))
        evs = A.load(T.APPS)[0]["events"]
        assert [(e["type"], e["date"], e["message_id"]) for e in evs] == [
            ("applied", "2026-10-01", "<m1@x>"), ("note", "2026-10-01", "<m1@x>")]

    def test_existing_app_gets_event(self, env, monkeypatch):
        apps = []
        a = A.create(apps, "Teva", "Analyst")
        A.add_event(a, "2026-09-01", "applied", "", "<old>")
        A.save(apps, T.APPS)
        stub(monkeypatch, {"relevant": True, "undo_previous": False, "events": [
            {"app_id": "teva-analyst", "company": "Teva", "role": "Analyst", "type": "interviewing",
             "date": "2026-10-20", "note": "Interview Thu"}]})
        run_saved(mk(irt=f"<tracker-2026-10-18.1@{DOM}>"))
        assert [e["type"] for e in A.load(T.APPS)[0]["events"]] == ["applied", "interviewing"]

    def test_empty_role_company_only_id_and_display(self, env, monkeypatch):
        _, sent = env
        recent = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()  # fixed dates go "ghosted" after 30 days
        stub(monkeypatch, {"relevant": True, "undo_previous": False, "events": [
            {"app_id": "new", "company": "Initech", "role": "",
             "type": "acknowledged", "date": recent, "note": "Application received"}]})
        run_saved(mk(subject="Fwd: Thanks", to=T.ALIAS, body="Thanks for applying"))
        a = A.load(T.APPS)[0]
        assert a["id"] == "initech" and a["role"] == ""
        assert "Recorded: Acknowledged — Initech (role not stated): Application received." in sent[0].get_content()
        assert "initech | Initech (role not stated) | acknowledged" in T.app_list(A.load(T.APPS))

    def test_existing_prepared_app_acknowledged_adds_applied(self, env, monkeypatch):
        apps = []
        A.create(apps, "Globex", "Portfolio Analyst", package="output/Globex")
        A.save(apps, T.APPS)
        stub(monkeypatch, {"relevant": True, "undo_previous": False, "events": [
            {"app_id": "globex-portfolio-analyst", "company": "Globex", "role": "Portfolio Analyst",
             "type": "acknowledged", "date": "2026-10-15", "note": "We got it"}]})
        ledger, _ = run_saved(mk(subject="Fwd: We got it", to=T.ALIAS, body="We got it"))
        evs = A.load(T.APPS)[0]["events"]
        assert [(e["type"], e["date"], e["message_id"]) for e in evs] == [
            ("applied", "2026-10-15", "<m1@x>"), ("acknowledged", "2026-10-15", "<m1@x>")]
        assert ledger["<m1@x>"]["events"] == [["globex-portfolio-analyst", "applied"],
                                               ["globex-portfolio-analyst", "acknowledged"]]

    def test_irrelevant_unusable(self, env, monkeypatch):
        _, sent = env
        stub(monkeypatch, {"relevant": False, "undo_previous": False, "events": []})
        ledger, _ = run_saved(mk(to=T.ALIAS))
        assert ledger["<m1@x>"]["status"] == "unusable"
        assert T.UNUSABLE_ACK in sent[0].get_content()

    def test_ack_undo_removes_earlier_events(self, env, monkeypatch):
        tmp, sent = env
        stub(monkeypatch, {"relevant": True, "undo_previous": False, "events": [
            {"app_id": "new", "company": "Wrong Co", "role": "Role", "type": "acknowledged",
             "date": "2026-09-30", "note": ""}]})
        ledger, _ = run_saved(mk(mid="<orig@x>", to=T.ALIAS))
        ledger["<orig@x>"]["ack_id"] = ACK_ID
        assert len(A.load(T.APPS)[0]["events"]) == 2
        # correction: undo, then the right events
        calls = stub(monkeypatch, {"relevant": True, "undo_previous": True, "events": [
            {"app_id": "new", "company": "Right Co", "role": "Role", "type": "applied",
             "date": "2026-09-30", "note": ""}]})
        fix = mk(mid="<fix@x>", irt=ACK_ID)
        T.process(raw(fix), *T.classify(fix), ledger, A.load(T.APPS), False)
        apps = A.load(T.APPS)
        assert [a["id"] for a in apps] == ["right-co-role"]
        assert "You previously recorded: Recorded: Acknowledged" in calls[0]

    def test_ack_undo_keeps_package_app(self, env, monkeypatch):
        apps = []
        a = A.create(apps, "OurCrowd", "Analyst", package="output/OurCrowd")
        A.add_event(a, "2026-09-01", "applied", "", "<orig@x>")
        A.save(apps, T.APPS)
        ledger = {"<orig@x>": {"status": "done", "ack_id": ACK_ID, "ack_text": "t", "events": [["ourcrowd-analyst", "applied"]]}}
        stub(monkeypatch, {"relevant": True, "undo_previous": True, "events": []})
        fix = mk(mid="<fix@x>", irt=ACK_ID)
        T.process(raw(fix), *T.classify(fix), ledger, A.load(T.APPS), False)
        apps = A.load(T.APPS)
        assert apps[0]["events"] == [] and apps[0]["package"]


class TestFailures:
    def test_three_attempts_then_unusable(self, env, monkeypatch):
        tmp, sent = env
        m = mk(irt=f"<tracker-2026-10-18.1@{DOM}>")

        def boom(p, s):
            raise RuntimeError("haiku down")

        monkeypatch.setattr(T, "ask_haiku", boom)
        ledger = {}
        kind, tag, fid = T.classify(m)
        for i in range(3):
            T.run_items([("<m1@x>", kind, tag, fid, raw(m))], ledger, False)
            assert ledger["<m1@x>"]["attempts"] == i + 1
            assert ledger["<m1@x>"]["status"] == ("failed" if i < 2 else "unusable")
            assert len(sent) == (0 if i < 2 else 1)
        assert T.UNUSABLE_ACK in sent[0].get_content()
        lines = (tmp / "state" / "failures.jsonl").read_text().splitlines()
        assert len(lines) == 3 and json.loads(lines[0])["message_id"] == "<m1@x>"
        assert (tmp / "state" / "failed" / "m1_x.eml").exists()
        assert json.loads((tmp / "state" / "processed.json").read_text())["<m1@x>"]["status"] == "unusable"

    def test_one_failure_does_not_stop_others(self, env, monkeypatch):
        tmp, _ = env
        a = mk(mid="<a@x>", irt=f"<tracker-t.1@{DOM}>")
        b = mk(mid="<b@x>", irt=f"<tracker-t.1@{DOM}>")
        n = []

        def flaky(p, s):
            if "summary" in s["properties"]:
                return {"summary": "S"}
            n.append(1)
            if len(n) == 1:
                raise RuntimeError("x")
            return {"relevant": True, "undo_previous": False, "events": [
                {"app_id": "new", "company": "C", "role": "R", "type": "applied", "date": "2026-10-01", "note": ""}]}

        monkeypatch.setattr(T, "ask_haiku", flaky)
        ledger = {}
        c = T.classify(a)
        T.run_items([("<a@x>", *c, raw(a)), ("<b@x>", *c, raw(b))], ledger, False)
        assert ledger["<a@x>"]["status"] == "failed" and ledger["<b@x>"]["status"] == "done"


class TestAckOrdering:
    def test_process_ledger_saved_before_ack_and_no_duplicate(self, env, monkeypatch):
        tmp, sent = env
        stub(monkeypatch, {"relevant": True, "undo_previous": False, "events": [
            {"app_id": "new", "company": "C", "role": "R", "type": "applied", "date": "2026-10-01", "note": ""}]})
        m = mk(irt=f"<tracker-t.1@{DOM}>")
        seen = []

        def boom(msg):
            seen.append(json.loads((tmp / "state" / "processed.json").read_text())["<m1@x>"]["ack_id"])
            raise RuntimeError("smtp down")

        monkeypatch.setattr(T, "send_mail", boom)
        ledger, res = run_saved(m)
        assert seen and seen[0] == ledger["<m1@x>"]["ack_id"] and seen[0]
        assert ledger["<m1@x>"]["status"] == "done"
        fails = [json.loads(x) for x in (tmp / "state" / "failures.jsonl").read_text().splitlines()]
        assert [f["step"] for f in fails] == ["ack"]
        monkeypatch.setattr(T, "send_mail", sent.append)
        run_saved(m, ledger)
        assert sent == []

    def test_unusable_ack_ledger_first(self, env, monkeypatch):
        tmp, sent = env
        m = mk(irt=f"<tracker-t.1@{DOM}>")
        monkeypatch.setattr(T, "ask_haiku", lambda p, s: (_ for _ in ()).throw(RuntimeError("down")))
        seen = []

        def boom(msg):
            seen.append(json.loads((tmp / "state" / "processed.json").read_text())["<m1@x>"]["ack_id"])
            raise RuntimeError("smtp down")

        monkeypatch.setattr(T, "send_mail", boom)
        ledger = {}
        kind, tag, fid = T.classify(m)
        for _ in range(3):
            T.run_items([("<m1@x>", kind, tag, fid, raw(m))], ledger, False)
        assert seen and seen[0] == ledger["<m1@x>"]["ack_id"]
        monkeypatch.setattr(T, "send_mail", sent.append)
        T.run_items([("<m1@x>", kind, tag, fid, raw(m))], ledger, False)
        assert sent == []


class TestAlert:
    def test_alert_once_then_recovery(self, env, monkeypatch):
        tmp, sent = env
        T.raise_alert("IMAP login failed")
        T.raise_alert("IMAP login failed")
        assert len(sent) == 1
        assert sent[0]["To"] == T.SENDER and sent[0]["Subject"] == "Job tracker failing"
        assert "IMAP login failed" in sent[0].get_content()
        alert = json.loads((tmp / "state" / "alert.json").read_text())
        assert set(alert) == {"since", "error"}
        # successful empty check recovers
        monkeypatch.setattr(T, "fetch_candidates", lambda ledger: [])
        assert T.check(False) == 0
        assert len(sent) == 2 and sent[1]["Subject"] == "Job tracker recovered"
        assert not (tmp / "state" / "alert.json").exists()
        assert T.check(False) == 0 and len(sent) == 2
        assert not (tmp / "state" / "track.log").exists()

    def test_systemic_exits_nonzero_and_alerts(self, env, monkeypatch):
        tmp, sent = env

        def bad(ledger):
            raise T.Systemic("Keychain lookup failed")

        monkeypatch.setattr(T, "fetch_candidates", bad)
        assert T.check(False) == 2 and T.check(False) == 2
        assert len(sent) == 1

    def test_dry_run_no_alert(self, env, monkeypatch):
        tmp, sent = env
        monkeypatch.setattr(T, "fetch_candidates", lambda ledger: (_ for _ in ()).throw(T.Systemic("x")))
        assert T.check(True) == 2 and sent == []
        assert not (tmp / "state" / "alert.json").exists()


class TestLock:
    def test_check_exits_silently_when_locked(self, env, monkeypatch, capsys):
        import fcntl
        monkeypatch.setattr(sys, "argv", ["track.py", "--check"])
        monkeypatch.setattr(T, "fetch_candidates", lambda ledger: pytest.fail("ran while locked"))
        T.STATE.mkdir(parents=True)
        with open(T.STATE / "track.lock", "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            assert T.main() == 0
        out = capsys.readouterr()
        assert out.out == "" and out.err == ""

    def test_check_runs_when_free(self, env, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["track.py", "--check"])
        monkeypatch.setattr(T, "fetch_candidates", lambda ledger: [])
        assert T.main() == 0

    def test_replay_waits_for_lock_when_real(self, env, monkeypatch, capsys):
        import fcntl
        monkeypatch.setattr(sys, "argv", ["track.py", "--replay", "x.eml"])
        monkeypatch.setattr(T, "LOCK_WAIT", 0)
        monkeypatch.setattr(T, "replay", lambda p, d: pytest.fail("ran while locked"))
        T.STATE.mkdir(parents=True)
        with open(T.STATE / "track.lock", "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            assert T.main() == 1
        assert "track.lock" in capsys.readouterr().err

    def test_replay_dry_run_skips_lock(self, env, monkeypatch):
        import fcntl
        monkeypatch.setattr(sys, "argv", ["track.py", "--replay", "x.eml", "--dry-run"])
        monkeypatch.setattr(T, "replay", lambda p, d: 0)
        T.STATE.mkdir(parents=True)
        with open(T.STATE / "track.lock", "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            assert T.main() == 0

    def test_digest_times_out_when_locked(self, env, monkeypatch, capsys):
        import fcntl
        monkeypatch.setattr(sys, "argv", ["track.py", "--digest"])
        monkeypatch.setattr(T, "LOCK_WAIT", 0)
        T.STATE.mkdir(parents=True)
        with open(T.STATE / "track.lock", "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            assert T.main() == 1
        assert "track.lock" in capsys.readouterr().err


class TestDigestCatchUp:
    @pytest.fixture
    def setup(self, env, monkeypatch):
        tmp, sent = env
        apps = []
        A.add_event(A.create(apps, "Acme", "PM"), "2026-09-01", "applied", "", "<old>")
        A.save(apps, T.APPS)
        monkeypatch.setattr(T, "fetch_candidates", lambda ledger: [])
        T.STATE.mkdir(parents=True)

        def at(hhmm):
            h, m = hhmm

            class FakeDT(T._dt.datetime):
                @classmethod
                def now(cls, tz=None):
                    return cls(2026, 10, 20, h, m)
            monkeypatch.setattr(T._dt, "datetime", FakeDT)
        return sent, at

    def run(self, monkeypatch, *flags):
        monkeypatch.setattr(sys, "argv", ["track.py", *flags])
        return T.main()

    def test_check_after_digest_time_sends_once(self, setup, monkeypatch):
        sent, at = setup
        at((9, 0))
        assert self.run(monkeypatch, "--check") == 0
        assert len(sent) == 1
        assert self.run(monkeypatch, "--check") == 0
        assert len(sent) == 1

    def test_check_before_digest_time_sends_nothing(self, setup, monkeypatch):
        sent, at = setup
        at((7, 29))
        assert self.run(monkeypatch, "--check") == 0
        assert sent == []

    def test_check_when_already_sent_sends_nothing(self, setup, monkeypatch):
        sent, at = setup
        at((9, 0))
        A.save({"sent_at": "2026-10-20T07:31:00"}, T.STATE / "last_digest.json")
        assert self.run(monkeypatch, "--check") == 0
        assert sent == []

    def test_digest_when_already_sent_returns_zero(self, setup, monkeypatch, capsys):
        sent, at = setup
        at((9, 0))
        A.save({"sent_at": "2026-10-20T07:31:00"}, T.STATE / "last_digest.json")
        monkeypatch.setattr(T, "check", lambda dry: pytest.fail("ran check"))
        assert self.run(monkeypatch, "--digest") == 0
        assert sent == []
        assert "already sent today" in capsys.readouterr().out

    def test_catch_up_oserror_is_swallowed(self, setup, monkeypatch, capsys):
        sent, at = setup
        at((9, 0))

        def boom(msg):
            raise OSError("dns")
        monkeypatch.setattr(T, "send_mail", boom)
        assert self.run(monkeypatch, "--check") == 0
        assert "digest catch-up failed: dns" in capsys.readouterr().err
