#!/usr/bin/env python3
"""Parallel JD scoring for /scan-jobs.

Reads state/candidates_<date>.json (from prefetch.py), scores each scorable
candidate with one MCP-free headless `claude -p` call, and writes
state/scores_<date>.json. The scan session then only ranks and writes the digest.

Scorable = seen false, triage "ok", description_status "ok".

Usage:
    python3 job_scanner/score.py [--candidates PATH] [--out PATH]
        [--concurrency 6] [--model sonnet] [--deadline 600] [--limit N]

Exit 0 even when JDs fail; exit 1 only if the output cannot be written.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NO_MCP = HERE / "launchd" / "no-mcp.json"
HEADING = "## Per-JD Input"
CALL_TIMEOUT = 120
RETRY_NOTE = "Output strict JSON only."
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
DEFAULT_TEMPLATE = (
    "COMPANY: {company}\nTITLE: {title}\nLOCATION: {location}\n"
    "REMOTE_POLICY: {remote_policy}\nPOSTED: {posted_date}\nURL: {url}\n\n"
    "DESCRIPTION:\n{description}"
)


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# Prompt
# --------------------------------------------------------------------------

def split_prompt(text):
    """scoring_prompt.md -> (system prompt, per-JD template).

    System = everything above the `## Per-JD Input` heading. Template = the
    first fenced block under it (else the rest of the section).
    """
    i = text.find(HEADING)
    if i < 0:
        return text.strip(), DEFAULT_TEMPLATE
    system, tail = text[:i].rstrip(), text[i + len(HEADING):]
    m = re.search(r"```[^\n]*\n(.*?)```", tail, re.S)
    return system, (m.group(1) if m else tail).strip("\n")


def fill_template(template, c):
    vals = {
        "company": c.get("company"), "title": c.get("title"), "location": c.get("location"),
        "remote_policy": "unknown", "posted_date": c.get("posted") or "unknown",
        "url": c.get("url"), "description": c.get("description"),
    }

    def sub(m):  # single pass: braces inside a description are never re-expanded
        key = re.match(r"\w+", m.group(1))
        k = key.group(0) if key else ""
        return str(vals[k]) if k in vals else m.group(0)

    return re.sub(r"\{([^{}\n]+)\}", sub, template)


def user_message(template, c):
    return fill_template(template, c) + "\n\nOutput strict JSON only, no prose."


# --------------------------------------------------------------------------
# claude call + parse
# --------------------------------------------------------------------------

def parse_result(text):
    """Model text -> dict with an int score, or None. Strips ``` fences."""
    s = (text or "").strip()
    m = re.match(r"^```[a-zA-Z]*\s*\n?(.*?)\n?```\s*$", s, re.S)
    if m:
        s = m.group(1).strip()
    try:
        o = json.loads(s)
    except ValueError:
        return None
    if not isinstance(o, dict):
        return None
    try:
        o["score"] = int(round(float(o["score"])))
    except (KeyError, TypeError, ValueError):
        return None
    return o


def claude_cmd(model, system, user, no_mcp=NO_MCP):
    return [
        "claude", "-p", "--model", model, "--output-format", "json",
        "--no-session-persistence", "--tools", "",
        "--strict-mcp-config", "--mcp-config", str(no_mcp),
        "--setting-sources", "", "--system-prompt", system, user,
    ]


def call_claude(model, system, user, timeout, root=ROOT):
    """One headless call -> envelope dict. Raises on timeout / bad envelope."""
    r = subprocess.run(
        claude_cmd(model, system, user), stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=timeout, cwd=str(root))
    try:
        env = json.loads(r.stdout)
    except ValueError:
        raise RuntimeError("exit %s, non-JSON output: %s" % (r.returncode, (r.stderr or r.stdout)[:120]))
    if not isinstance(env, dict) or env.get("is_error") or r.returncode != 0:
        raise RuntimeError(str(env.get("result") if isinstance(env, dict) else env)[:120] or "claude error")
    return env


class Deadline:
    def __init__(self, sec):
        self.end = time.monotonic() + sec

    def remaining(self):
        return max(0.0, self.end - time.monotonic())

    def expired(self):
        return self.remaining() <= 0


def _finish(item, usage, status):
    item["status"] = status
    item["_usage"] = usage
    return item


def score_one(c, model, system, template, deadline, root=ROOT):
    """-> item dict, or None if the deadline passed before it started."""
    if deadline.expired():
        return None
    item = {k: c.get(k) for k in ("url_hash", "content_hash", "company", "title", "url", "location", "source")}
    item.update(status="error", score=None, location_tier=None, remote_flexibility=None,
                best_bundle=None, rationale=None, red_flags=None, cost_usd=0.0)
    usage = dict.fromkeys(USAGE_KEYS, 0)
    user = user_message(template, c)
    raw = ""
    for attempt in range(2):
        if attempt and deadline.expired():
            return _finish(item, usage, "timeout")
        try:
            env = call_claude(model, system, user if attempt == 0 else user + "\n\n" + RETRY_NOTE,
                              max(1.0, min(CALL_TIMEOUT, deadline.remaining())), root)
        except subprocess.TimeoutExpired:
            return _finish(item, usage, "timeout")
        except Exception as e:  # never raise out of a worker
            item["error"] = ("%s: %s" % (type(e).__name__, e))[:200]
            return _finish(item, usage, "error")
        item["cost_usd"] += float(env.get("total_cost_usd") or 0)
        for k in USAGE_KEYS:
            usage[k] += int((env.get("usage") or {}).get(k) or 0)
        raw = env.get("result") or ""
        o = parse_result(raw)
        if o:
            for k in ("location_tier", "remote_flexibility", "best_bundle", "rationale", "red_flags"):
                item[k] = o.get(k)
            item["score"] = o["score"]
            return _finish(item, usage, "ok")
    item["raw"] = str(raw)[:500]
    return _finish(item, usage, "parse-failed")


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def scorable(c):
    return (c.get("seen") is False and c.get("triage") == "ok"
            and c.get("description_status") == "ok" and bool(c.get("description")))


def line(item):
    name = "%s — %s" % (item["company"], item["title"])
    if item["status"] == "ok":
        return "OK  %d %s ($%.4f)" % (item["score"], name, item["cost_usd"])
    return "FAIL %s %s" % ({"parse-failed": "parse", "timeout": "timeout"}.get(item["status"], "error"), name)


def build(root, cand_path, out_path, concurrency, model, deadline_sec, limit):
    t0 = time.monotonic()
    deadline = Deadline(deadline_sec)
    data = json.loads(Path(cand_path).read_text(encoding="utf-8"))
    todo = [c for c in data.get("candidates") or [] if scorable(c)]
    if limit is not None:
        todo = todo[:limit]
    system, template = split_prompt((root / "job_scanner" / "scoring_prompt.md").read_text(encoding="utf-8"))

    def work(c):
        it = score_one(c, model, system, template, deadline, root)
        if it is not None:
            log(line(it))
        return it

    # ponytail: first call runs alone so the system prompt is cached before the pool fans out.
    results = [work(todo[0])] if todo else []
    ex = ThreadPoolExecutor(max_workers=max(1, concurrency))
    try:
        results += list(ex.map(work, todo[1:]))  # in-flight calls end by the deadline (timeout is capped to it)
    finally:
        ex.shutdown(wait=True)
    items = [r for r in results if r is not None]
    hit = len(items) < len(todo) or any(r["status"] == "timeout" for r in items) and deadline.expired()

    usage = dict.fromkeys(USAGE_KEYS, 0)
    for it in items:
        for k, v in it.pop("_usage").items():
            usage[k] += v
    n_ok = sum(1 for it in items if it["status"] == "ok")
    cost = round(sum(it["cost_usd"] for it in items), 6)
    for it in items:
        it["cost_usd"] = round(it["cost_usd"], 6)
    out = {
        "run": datetime.now().isoformat(timespec="seconds"), "model": model,
        "deadline_hit": bool(hit), "n_scorable": len(todo), "n_scored": n_ok,
        "n_failed": len(items) - n_ok, "cost_usd": cost, "usage": usage,
        "duration_sec": round(time.monotonic() - t0, 1), "items": items,
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("score: %d/%d scored, %d failed, $%.4f, %.1fs%s -> %s" % (
        n_ok, len(todo), len(items) - n_ok, cost, time.monotonic() - t0,
        ", DEADLINE HIT" if hit else "", out_path))
    return out


def main(argv=None, root=None):
    root = Path(root) if root else ROOT
    today = date.today().isoformat()
    state = root / "job_scanner" / "state"
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--candidates", help="default state/candidates_<date>.json")
    p.add_argument("--out", help="default state/scores_<date>.json")
    p.add_argument("--concurrency", type=int, default=6)
    p.add_argument("--model", default="sonnet")
    p.add_argument("--deadline", type=float, default=600, help="global deadline in seconds")
    p.add_argument("--limit", type=int, help="score at most N JDs")
    a = p.parse_args(argv)
    try:
        build(root, a.candidates or state / ("candidates_%s.json" % today),
              a.out or state / ("scores_%s.json" % today),
              a.concurrency, a.model, a.deadline, a.limit)
    except Exception as e:  # unreadable input or unwritable output
        log("FATAL %s: %s" % (type(e).__name__, e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
