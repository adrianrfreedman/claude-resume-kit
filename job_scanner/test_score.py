"""score: prompt split, parse, run, deadline. subprocess mocked, no network."""

import json
import subprocess
import time
from pathlib import Path

import score

PROMPT = """# Profile
Be a scorer.

## Output Format
JSON.

## Per-JD Input (variable, appended at runtime)

```
COMPANY: {company}
TITLE: {title}
LOCATION: {location}
REMOTE_POLICY: {remote_policy or "unknown"}
POSTED: {posted_date or "unknown"}
URL: {url}

DESCRIPTION:
{description}
```
"""

GOOD = {"score": 87, "location_tier": 1, "remote_flexibility": "med",
        "best_bundle": "translational", "rationale": "fits", "red_flags": []}


def cand(title="Senior Backend Engineer", **kw):
    c = {"company": "Wix", "title": title, "location": "Tel Aviv", "url": "https://w.com/" + title,
         "posted": None, "source": "linkedin_il", "url_hash": "u" + title, "content_hash": "c" + title,
         "seen": False, "triage": "ok", "description_status": "ok", "description": "Build {things}."}
    c.update(kw)
    return c


def envelope(result, cost=0.003):
    return json.dumps({
        "type": "result", "is_error": False, "result": result, "total_cost_usd": cost,
        "usage": {"input_tokens": 600, "output_tokens": 80,
                  "cache_creation_input_tokens": 10, "cache_read_input_tokens": 5}})


class Proc:
    def __init__(self, out, code=0):
        self.stdout, self.stderr, self.returncode = out, "", code


def setup_root(tmp_path, cands):
    (tmp_path / "job_scanner" / "state").mkdir(parents=True)
    (tmp_path / "job_scanner" / "scoring_prompt.md").write_text(PROMPT)
    cp = tmp_path / "cands.json"
    cp.write_text(json.dumps({"candidates": cands}))
    return cp


class TestPromptSplit:
    def test_split(self):
        system, template = score.split_prompt(PROMPT)
        assert system.endswith("JSON.")
        assert "Per-JD Input" not in system
        assert template.startswith("COMPANY: {company}")
        assert "```" not in template

    def test_no_heading(self):
        system, template = score.split_prompt("just a prompt")
        assert system == "just a prompt"
        assert "{description}" in template

    def test_fill(self):
        _, template = score.split_prompt(PROMPT)
        msg = score.user_message(template, cand(posted="2026-10-30"))
        assert "COMPANY: Wix\nTITLE: Senior Backend Engineer\nLOCATION: Tel Aviv\n" in msg
        assert "REMOTE_POLICY: unknown\nPOSTED: 2026-10-30\n" in msg
        assert "DESCRIPTION:\nBuild {things}." in msg
        assert msg.endswith("\n\nOutput strict JSON only, no prose.")

    def test_posted_unknown(self):
        _, template = score.split_prompt(PROMPT)
        assert "POSTED: unknown" in score.fill_template(template, cand())


class TestParse:
    def test_plain(self):
        assert score.parse_result(json.dumps(GOOD))["score"] == 87

    def test_fenced(self):
        assert score.parse_result("```json\n%s\n```" % json.dumps(GOOD))["location_tier"] == 1
        assert score.parse_result("```\n%s\n```" % json.dumps(GOOD))["score"] == 87

    def test_garbage(self):
        assert score.parse_result("I think it is a good fit") is None
        assert score.parse_result("[1, 2]") is None
        assert score.parse_result('{"rationale": "no score"}') is None
        assert score.parse_result("") is None

    def test_garbage_is_parse_failed(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: Proc(envelope("nope " * 200)))
        _, t = score.split_prompt(PROMPT)
        it = score.score_one(cand(), "sonnet", "sys", t, score.Deadline(60))
        assert it["status"] == "parse-failed"
        assert it["score"] is None
        assert len(it["raw"]) == 500

    def test_retry_then_ok(self, monkeypatch):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            return Proc(envelope("prose" if len(calls) == 1 else json.dumps(GOOD)))

        monkeypatch.setattr(subprocess, "run", run)
        _, t = score.split_prompt(PROMPT)
        it = score.score_one(cand(), "sonnet", "sys", t, score.Deadline(60))
        assert it["status"] == "ok" and it["score"] == 87
        assert len(calls) == 2
        assert calls[1][-1].endswith("Output strict JSON only.")
        assert it["cost_usd"] == 0.006


class TestRun:
    def test_one_scorable_one_seen(self, tmp_path, monkeypatch):
        cp = setup_root(tmp_path, [cand(), cand("Seen Role", seen=True),
                                   cand("Excluded", triage="title-exclude"),
                                   cand("No Body", description_status="timeout", description=None)])
        seen_cmds = []

        def run(cmd, **kw):
            seen_cmds.append((cmd, kw))
            return Proc(envelope("```json\n%s\n```" % json.dumps(GOOD)))

        monkeypatch.setattr(subprocess, "run", run)
        out = tmp_path / "scores.json"
        assert score.main(["--candidates", str(cp), "--out", str(out)], root=tmp_path) == 0
        d = json.loads(out.read_text())
        assert d["n_scorable"] == 1 and d["n_scored"] == 1 and d["n_failed"] == 0
        assert d["deadline_hit"] is False and d["model"] == "sonnet"
        assert len(d["items"]) == 1
        it = d["items"][0]
        assert it["status"] == "ok" and it["score"] == 87 and it["best_bundle"] == "translational"
        assert it["url_hash"] == "uSenior Backend Engineer" and it["company"] == "Wix"
        assert d["cost_usd"] == 0.003
        assert d["usage"] == {"input_tokens": 600, "output_tokens": 80,
                              "cache_creation_input_tokens": 10, "cache_read_input_tokens": 5}
        cmd, kw = seen_cmds[0]
        assert cmd[:2] == ["claude", "-p"]
        assert "--strict-mcp-config" in cmd and "--setting-sources" in cmd
        assert cmd[cmd.index("--tools") + 1] == ""
        assert cmd[cmd.index("--system-prompt") + 1].endswith("JSON.")
        assert cmd[cmd.index("--mcp-config") + 1].endswith("no-mcp.json")
        assert kw["stdin"] == subprocess.DEVNULL and kw["timeout"] <= 120

    def test_cost_summed_and_failures(self, tmp_path, monkeypatch):
        cp = setup_root(tmp_path, [cand("A"), cand("B"), cand("C")])

        def run(cmd, **kw):
            if "TITLE: B" in cmd[-1]:
                raise subprocess.TimeoutExpired(cmd, 1)
            if "TITLE: C" in cmd[-1]:
                return Proc("not json", 1)
            return Proc(envelope(json.dumps(GOOD), 0.002))

        monkeypatch.setattr(subprocess, "run", run)
        out = tmp_path / "scores.json"
        score.main(["--candidates", str(cp), "--out", str(out), "--concurrency", "1"], root=tmp_path)
        d = json.loads(out.read_text())
        assert {i["title"]: i["status"] for i in d["items"]} == {"A": "ok", "B": "timeout", "C": "error"}
        assert d["n_scored"] == 1 and d["n_failed"] == 2 and d["cost_usd"] == 0.002

    def test_limit(self, tmp_path, monkeypatch):
        cp = setup_root(tmp_path, [cand("A"), cand("B"), cand("C")])
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: Proc(envelope(json.dumps(GOOD))))
        out = tmp_path / "scores.json"
        score.main(["--candidates", str(cp), "--out", str(out), "--limit", "2"], root=tmp_path)
        assert json.loads(out.read_text())["n_scorable"] == 2

    def test_unreadable_candidates(self, tmp_path):
        setup_root(tmp_path, [])
        assert score.main(["--candidates", str(tmp_path / "missing.json")], root=tmp_path) == 1


class TestDeadline:
    def test_deadline_zero(self, tmp_path, monkeypatch):
        cp = setup_root(tmp_path, [cand("A"), cand("B")])

        def run(cmd, **kw):
            raise AssertionError("no call expected")

        monkeypatch.setattr(subprocess, "run", run)
        out = tmp_path / "scores.json"
        t0 = time.monotonic()
        assert score.main(["--candidates", str(cp), "--out", str(out), "--deadline", "0"], root=tmp_path) == 0
        assert time.monotonic() - t0 < 1
        d = json.loads(out.read_text())
        assert d["deadline_hit"] is True and d["items"] == [] and d["n_scorable"] == 2

    def test_partial(self, tmp_path, monkeypatch):
        cp = setup_root(tmp_path, [cand("A"), cand("B"), cand("C")])

        def run(cmd, **kw):
            time.sleep(0.6)
            return Proc(envelope(json.dumps(GOOD)))

        monkeypatch.setattr(subprocess, "run", run)
        out = tmp_path / "scores.json"
        score.main(["--candidates", str(cp), "--out", str(out), "--concurrency", "1",
                    "--deadline", "1"], root=tmp_path)
        d = json.loads(out.read_text())
        assert d["deadline_hit"] is True
        assert 1 <= len(d["items"]) < 3


class TestExamplePrompt:
    def test_split_prompt_accepts_example(self):
        text = (Path(__file__).parent / "scoring_prompt.example.md").read_text(encoding="utf-8")
        system, template = score.split_prompt(text)
        assert "## Scoring Rubric" in system and "Per-JD Input" not in system
        assert template.startswith("COMPANY: {company}") and "{description}" in template
