#!/usr/bin/env python3
"""Render the scan digest from prefetch + score output (no Claude session).

Reads state/candidates_<date>.json and state/scores_<date>.json and writes:
  digests/digest_<date>.md      ranked digest (Strong / Good / Worth-a-look,
                                Not scored, Dropped, Cost summary, Prefetch)
  digests/digest_<date>.json    sidecar [{n, scan_id, company, title, url, score}]
  state/seen.jsonl              one line per unseen candidate reviewed (append)
  state/runs/run_<ts>.log       summary JSON (append)

A second run on the same date keeps the earlier files as digest_<date>_run1.*,
continues numbering from the sidecar's max n and appends to its entries.

Usage:
    python3 job_scanner/digest.py [--candidates PATH] [--scores PATH]
        [--date YYYY-MM-DD] [--dry-run]

--dry-run writes nothing and prints the Markdown.
Exit 0; exit 1 on an unreadable candidates file or a write failure.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date as _date, datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dedupe import load_seen  # noqa: E402

HERE = Path(__file__).resolve().parent
STRONG, GOOD = 85, 70
DEFAULT_THRESHOLD = 50
USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
SECTIONS = (("Strong matches (85-100)", STRONG, 101), ("Good matches (70-84)", GOOD, STRONG))
PRICING_NOTE = (
    "_Scores file: tokens and cost come from `scores_<date>.json` (`usage`, `cost_usd`, as billed by "
    "score.py). Pricing reference (Sonnet 4.6): $3/M input, $15/M output, $3.75/M cache write, "
    "$0.30/M cache read._")


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------

def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_threshold(sources_path):
    try:
        s = yaml.safe_load(Path(sources_path).read_text(encoding="utf-8")) or {}
        return int((s.get("settings") or {}).get("min_score_to_email") or DEFAULT_THRESHOLD)
    except (OSError, ValueError, TypeError, yaml.YAMLError):
        return DEFAULT_THRESHOLD


def tier_of(item):
    try:
        return int(item.get("location_tier"))
    except (TypeError, ValueError):
        return 99


def classify(cands_data, scores_data, threshold):
    """-> dict: matches (ranked), dropped, not_scored, excluded, unseen, scored."""
    by_url = {}
    for it in (scores_data or {}).get("items") or []:
        if it.get("status") == "ok" and isinstance(it.get("score"), int):
            by_url[it.get("url_hash")] = it
    failed = {it.get("url_hash"): it.get("status") for it in (scores_data or {}).get("items") or []
              if it.get("status") != "ok"}
    cands = cands_data.get("candidates") or []
    unseen = [c for c in cands if not c.get("seen")]
    scored, matches, dropped, not_scored, excluded = [], [], [], [], []
    for c in unseen:
        if c.get("triage") == "title-exclude":
            excluded.append(c)
            continue
        it = by_url.get(c.get("url_hash"))
        if it is None:
            status = ("score " + failed[c["url_hash"]]) if c.get("url_hash") in failed else (
                c.get("description_status") if c.get("description_status") != "ok" else "not scored")
            not_scored.append(dict(c, _status=status))
            continue
        row = dict(it, content_hash=c.get("content_hash"), url_hash=c.get("url_hash"))
        scored.append(row)
        (matches if it["score"] >= threshold and tier_of(it) != 0 else dropped).append(row)
    matches.sort(key=lambda r: (-r["score"], tier_of(r)))
    dropped.sort(key=lambda r: -r["score"])
    return {"cands": cands, "unseen": unseen, "scored": scored, "matches": matches,
            "dropped": dropped, "not_scored": not_scored, "excluded": excluded}


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------

def cell(s):
    return re.sub(r"\s+", " ", str(s if s is not None else "")).replace("|", "\\|").strip()


def text_of(v, default):
    if isinstance(v, (list, tuple)):
        v = "; ".join(str(x) for x in v if x)
    v = str(v).strip() if v is not None else ""
    return v if v and v.lower() not in ("none", "null") else default


def entry_md(n, r):
    return "\n".join([
        "### %d. %s — %s · score %d/100" % (n, r.get("title"), r.get("company"), r["score"]),
        "- **Location:** %s (tier %s) · **Remote:** %s" % (
            text_of(r.get("location"), "unknown"), r.get("location_tier") if r.get("location_tier") is not None else "?",
            text_of(r.get("remote_flexibility"), "unknown")),
        "- **Best bundle:** %s" % text_of(r.get("best_bundle"), "unknown"),
        "- **Why:** %s" % text_of(r.get("rationale"), "n/a"),
        "- **Red flags:** %s" % text_of(r.get("red_flags"), "none"),
        "- **Link:** %s" % r.get("url"),
    ])


def prefetch_line(cands_data, n_excluded):
    srcs = cands_data.get("sources") or []
    bad = Counter("%s %s" % (s.get("id"), s.get("status")) for s in srcs if s.get("status") != "ok")
    sec = cands_data.get("duration_sec")
    return "**Prefetch:** %s · sources failed: %d/%d%s · title-excluded: %d%s" % (
        ("%.1fs" % sec) if isinstance(sec, (int, float)) else "n/a",
        sum(bad.values()), len(srcs),
        (" (%s)" % ", ".join("%s ×%d" % kv for kv in sorted(bad.items()))) if bad else "",
        n_excluded, " · deadline hit" if cands_data.get("deadline_hit") else "")


def render(sel, cands_data, scores_data, date_str, threshold, start_n=0, run_no=1):
    """-> (markdown, sidecar entries for the numbered matches)."""
    srcs = cands_data.get("sources") or []
    n_sources = len({s.get("id") for s in srcs if s.get("status") == "ok"})
    title = "# Job digest — %s%s" % (date_str, " (run %d)" % run_no if run_no > 1 else "")
    out = [title, "",
           "**Sources scanned:** %d · **JDs reviewed:** %d · **New since last run:** %d · **Matches (≥%d):** %d" % (
               n_sources, len(sel["cands"]), len(sel["unseen"]), threshold, len(sel["matches"])),
           "", "---"]
    sidecar, n = [], start_n
    buckets = [(h, [r for r in sel["matches"] if lo <= r["score"] < hi]) for h, lo, hi in SECTIONS]
    buckets.append(("Worth-a-look (%d-%d)" % (threshold, GOOD - 1),
                    [r for r in sel["matches"] if r["score"] < GOOD]))
    for i, (head, rows) in enumerate(buckets):
        out += ["", "## " + head, ""]
        if not rows:
            out.append("_None this run._")
        for r in rows:
            n += 1
            out += [entry_md(n, r), ""]
            sidecar.append({"n": n, "scan_id": r["url_hash"], "company": r.get("company"),
                            "title": r.get("title"), "url": r.get("url"), "score": r["score"]})
        if i == 0:
            out += ["", "**Numbering:** `N` is continuous across Strong, Good and Worth-a-look "
                    "(1, 2, 3, …); it does not restart per section. Dropped table rows get no numbers."]
        out += ["", "---"]
    out += ["", "## Not scored", ""]
    if sel["not_scored"]:
        out += ["Listings the scripts could not score (retried next run, not in the ledger).", "",
                "| Status | Role | Company | Link |", "|--------|------|---------|------|"]
        out += ["| %s | %s | %s | %s |" % (cell(c["_status"]), cell(c.get("title")), cell(c.get("company")),
                                           cell(c.get("url"))) for c in sel["not_scored"]]
    else:
        out.append("_None._")
    out += ["", "---", "", "## Dropped (<%d) — new this run" % threshold, ""]
    if sel["dropped"]:
        out += ["| Role | Company | Score |", "|------|---------|-------|"]
        out += ["| %s | %s | %d |" % (cell(r.get("title")), cell(r.get("company")), r["score"]) for r in sel["dropped"]]
    else:
        out.append("_None._")
    u = (scores_data or {}).get("usage") or {}
    g = lambda k: int(u.get(k) or 0)  # noqa: E731
    out += ["", "---", "", "## Cost summary", "",
            "| Metric | Value |", "|--------|-------|",
            "| JDs scored | %d |" % int((scores_data or {}).get("n_scored") or len(sel["scored"])),
            "| Input tokens (non-cached) | %s |" % format(g("input_tokens"), ","),
            "| Input tokens (cache write) | %s |" % format(g("cache_creation_input_tokens"), ","),
            "| Input tokens (cache read) | %s |" % format(g("cache_read_input_tokens"), ","),
            "| Output tokens | %s |" % format(g("output_tokens"), ","),
            "| **Total cost (USD)** | **$%.4f** |" % float((scores_data or {}).get("cost_usd") or 0),
            "", PRICING_NOTE, "", "---", "", prefetch_line(cands_data, len(sel["excluded"])), ""]
    return "\n".join(out), sidecar


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------

def ledger_lines(sel, cands_data, date_str, seen_path):
    """One ledger entry per unseen candidate reviewed; skips hashes already present."""
    if cands_data.get("no_dedupe"):
        return []
    urls, contents = load_seen(str(seen_path))
    out = []
    for c in sel["excluded"]:
        out.append({"url_hash": c["url_hash"], "content_hash": c["content_hash"], "url": c["url"],
                    "company": c["company"], "title": c["title"], "first_seen": date_str,
                    "score": 0, "triage": "title-exclude"})
    for r in sel["scored"]:
        out.append({"url_hash": r["url_hash"], "content_hash": r["content_hash"], "url": r["url"],
                    "company": r["company"], "title": r["title"], "first_seen": date_str, "score": r["score"]})
    return [o for o in out if o["url_hash"] not in urls and o["content_hash"] not in contents]


def archive_previous(digests, date_str):
    """Move an existing digest_<date>.{md,json} to _run<k>; -> (next run number, previous max n)."""
    md, js = digests / ("digest_%s.md" % date_str), digests / ("digest_%s.json" % date_str)
    if not md.exists() and not js.exists():
        return 1, 0, []
    k = 1
    while any((digests / ("digest_%s_run%d.%s" % (date_str, k, e))).exists() for e in ("md", "json")):
        k += 1
    prev = []
    if js.exists():
        try:
            prev = json.loads(js.read_text(encoding="utf-8"))
        except ValueError:
            prev = []
    for p, e in ((md, "md"), (js, "json")):
        if p.exists():
            p.rename(digests / ("digest_%s_run%d.%s" % (date_str, k, e)))
    return k + 1, max([int(e.get("n") or 0) for e in prev] or [0]), prev


def summary_of(sel, cands_data, scores_data, run_id):
    d = [x.get("duration_sec") for x in (cands_data, scores_data or {})]
    return {"run_id": run_id, "n_total": len(sel["cands"]), "n_new": len(sel["unseen"]),
            "n_scored": len(sel["scored"]), "n_matches": len(sel["matches"]),
            "total_cost_usd": float((scores_data or {}).get("cost_usd") or 0),
            "duration_sec": round(sum(d), 1) if all(isinstance(x, (int, float)) for x in d) else None}


def build(cand_path, scores_path, date_str, threshold, seen_path, digests_dir, runs_dir, dry_run=False, now=None):
    now = now or datetime.now()
    cands_data = load_json(cand_path)
    try:
        scores_data = load_json(scores_path)
    except (OSError, ValueError):
        scores_data = None
        log("WARN no usable scores file %s: nothing will be scored" % scores_path)
    sel = classify(cands_data, scores_data, threshold)
    digests, run_no, start_n, prev = Path(digests_dir), 1, 0, []
    if not dry_run:
        run_no, start_n, prev = archive_previous(digests, date_str)
    else:
        md0 = digests / ("digest_%s.json" % date_str)
        if md0.exists():
            try:
                prev = json.loads(md0.read_text(encoding="utf-8"))
                start_n, run_no = max([int(e.get("n") or 0) for e in prev] or [0]), 2
            except ValueError:
                pass
    md, sidecar = render(sel, cands_data, scores_data, date_str, threshold, start_n, run_no)
    run_id = now.strftime("%Y-%m-%d_%H%M%S")
    summary = summary_of(sel, cands_data, scores_data, run_id)
    lines = ledger_lines(sel, cands_data, date_str, seen_path)
    if dry_run:
        return md, summary
    digests.mkdir(parents=True, exist_ok=True)
    (digests / ("digest_%s.md" % date_str)).write_text(md, encoding="utf-8")
    (digests / ("digest_%s.json" % date_str)).write_text(
        json.dumps(prev + sidecar, ensure_ascii=False, indent=1), encoding="utf-8")
    if lines:
        Path(seen_path).parent.mkdir(parents=True, exist_ok=True)
        with open(str(seen_path), "a", encoding="utf-8") as f:
            f.writelines(json.dumps(o, ensure_ascii=False) + "\n" for o in lines)
    Path(runs_dir).mkdir(parents=True, exist_ok=True)
    with open(str(Path(runs_dir) / ("run_%s.log" % run_id)), "a", encoding="utf-8") as f:
        f.write(json.dumps(summary) + "\n")
    return md, summary


def main(argv=None, root=None):
    root = Path(root) if root else HERE
    state = root / "state"
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--candidates", help="default state/candidates_<date>.json")
    p.add_argument("--scores", help="default state/scores_<date>.json")
    p.add_argument("--date", default=_date.today().isoformat(), help="YYYY-MM-DD (default today)")
    p.add_argument("--dry-run", action="store_true", help="write nothing; print the Markdown")
    a = p.parse_args(argv)
    try:
        md, summary = build(
            a.candidates or state / ("candidates_%s.json" % a.date),
            a.scores or state / ("scores_%s.json" % a.date),
            a.date, load_threshold(root / "sources.yaml"), state / "seen.jsonl",
            root / "digests", state / "runs", a.dry_run)
    except Exception as e:  # unreadable candidates or unwritable output
        log("FATAL %s: %s" % (type(e).__name__, e))
        return 1
    if a.dry_run:
        print(md)
    else:
        print("digest: %d new, %d scored, %d matches, $%.4f -> %s" % (
            summary["n_new"], summary["n_scored"], summary["n_matches"], summary["total_cost_usd"],
            root / "digests" / ("digest_%s.md" % a.date)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
