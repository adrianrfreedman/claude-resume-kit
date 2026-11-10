"""digest: buckets, numbering, ledger, cost, not-scored. Files in tmp_path, no network."""

import json
from datetime import datetime

import digest

DATE = "2026-11-01"
NOW = datetime(2026, 11, 1, 10, 30, 0)


def cand(n, title=None, seen=False, triage="ok", desc="ok", **kw):
    c = {"company": "Co%d" % n, "title": title or "Role %d" % n, "location": "Tel Aviv",
         "url": "https://x.test/%d" % n, "url_hash": "u%d" % n, "content_hash": "c%d" % n,
         "seen": seen, "triage": triage, "description_status": desc,
         "description": "body" if desc == "ok" else None, "source": "linkedin_il"}
    c.update(kw)
    return c


def item(n, score, tier=1, **kw):
    it = {"url_hash": "u%d" % n, "content_hash": "c%d" % n, "company": "Co%d" % n, "title": "Role %d" % n,
          "url": "https://x.test/%d" % n, "location": "Tel Aviv", "source": "linkedin_il", "status": "ok",
          "score": score, "location_tier": tier, "remote_flexibility": "high",
          "best_bundle": "translational", "rationale": "fits well", "red_flags": [], "cost_usd": 0.01}
    it.update(kw)
    return it


def scores(items, **kw):
    d = {"model": "sonnet", "n_scored": sum(1 for i in items if i["status"] == "ok"), "cost_usd": 0.0421,
         "usage": {"input_tokens": 1000, "output_tokens": 2500, "cache_creation_input_tokens": 4000,
                   "cache_read_input_tokens": 120000}, "duration_sec": 40.0, "items": items}
    d.update(kw)
    return d


def cands_file(cands, **kw):
    d = {"run": "x", "deadline_hit": False, "duration_sec": 100.0,
         "sources": [{"id": "linkedin_il", "status": "ok"}, {"id": "alljobs", "status": "ok"},
                     {"id": "drushim", "status": "http 403"}],
         "candidates": cands, "raw_pages": []}
    d.update(kw)
    return d


class Env:
    """tmp_path layout + run helper."""

    def __init__(self, tmp_path):
        self.root = tmp_path
        self.state = tmp_path / "state"
        self.digests = tmp_path / "digests"
        self.state.mkdir()
        self.cp, self.sp = self.state / "c.json", self.state / "s.json"
        self.seen = self.state / "seen.jsonl"
        self.runs = self.state / "runs"

    def write(self, cands, items, **kw):
        self.cp.write_text(json.dumps(cands_file(cands)))
        self.sp.write_text(json.dumps(scores(items, **kw)))

    def run(self, threshold=50, dry_run=False, now=NOW):
        return digest.build(self.cp, self.sp, DATE, threshold, self.seen, self.digests, self.runs, dry_run, now)

    def sidecar(self, name="digest_%s.json" % DATE):
        return json.loads((self.digests / name).read_text())

    def ledger(self):
        return [json.loads(x) for x in self.seen.read_text().splitlines()] if self.seen.exists() else []


class TestBuckets:
    def _md(self, tmp_path, pairs, threshold=50):
        e = Env(tmp_path)
        e.write([cand(n) for n, _ in pairs], [item(n, s) for n, s in pairs])
        return e.run(threshold)[0]

    def test_boundaries(self, tmp_path):
        md = self._md(tmp_path, [(1, 85), (2, 84), (3, 70), (4, 69), (5, 50), (6, 49)])
        strong, rest = md.split("## Strong matches (85-100)")[1].split("## Good matches (70-84)")
        good, worth = rest.split("## Worth-a-look (50-69)")
        worth = worth.split("## Not scored")[0]
        assert "Role 1 " in strong and "Role 2" not in strong
        assert "Role 2 " in good and "Role 3 " in good and "Role 4" not in good
        assert "Role 4 " in worth and "Role 5 " in worth
        assert "### 6." not in md

    def test_continuous_numbering(self, tmp_path):
        md = self._md(tmp_path, [(1, 90), (2, 75), (3, 60)])
        assert [l.split(".")[0] for l in md.splitlines() if l.startswith("### ")] == ["### 1", "### 2", "### 3"]

    def test_below_threshold_table_no_numbers(self, tmp_path):
        md = self._md(tmp_path, [(1, 80), (2, 49), (3, 20)])
        dropped = md.split("## Dropped (<50)")[1].split("## Cost summary")[0]
        assert "| Role 2 | Co2 | 49 |" in dropped and "| Role 3 | Co3 | 20 |" in dropped
        assert "Role 1" not in dropped and "### " not in dropped
        assert dropped.index("Role 2") < dropped.index("Role 3")  # score desc

    def test_custom_threshold(self, tmp_path):
        md = self._md(tmp_path, [(1, 80), (2, 65)], threshold=70)
        assert "**Matches (≥70):** 1" in md and "## Dropped (<70)" in md
        assert "| Role 2 | Co2 | 65 |" in md

    def test_tier_zero_dropped_and_tie_order(self, tmp_path):
        e = Env(tmp_path)
        e.write([cand(n) for n in (1, 2, 3)], [item(1, 80, tier=2), item(2, 80, tier=1), item(3, 95, tier=0)])
        md = e.run()[0]
        assert md.index("Role 2") < md.index("Role 1")
        assert "| Role 3 | Co3 | 95 |" in md

    def test_header_and_entry_fields(self, tmp_path):
        e = Env(tmp_path)
        e.write([cand(1), cand(2, seen=True)], [item(1, 72, red_flags=["gap A", "gap B"])])
        md = e.run()[0]
        assert md.startswith("# Job digest — 2026-11-01\n")
        assert "**Sources scanned:** 2 · **JDs reviewed:** 2 · **New since last run:** 1 · **Matches (≥50):** 1" in md
        assert "### 1. Role 1 — Co1 · score 72/100" in md
        assert "- **Location:** Tel Aviv (tier 1) · **Remote:** high" in md
        assert "- **Red flags:** gap A; gap B" in md
        assert "- **Link:** https://x.test/1" in md
        assert "## Strong matches (85-100)\n\n_None this run._" in md

    def test_prefetch_line(self, tmp_path):
        e = Env(tmp_path)
        e.write([cand(1), cand(2, triage="title-exclude", desc="skipped-title")], [item(1, 60)])
        md = e.run()[0]
        assert "**Prefetch:** 100.0s · sources failed: 1/3 (drushim http 403 ×1) · title-excluded: 1" in md


class TestNumbering:
    def test_second_run_continues(self, tmp_path):
        e = Env(tmp_path)
        e.write([cand(1), cand(2)], [item(1, 90), item(2, 60)])
        e.run()
        first_md = (e.digests / ("digest_%s.md" % DATE)).read_text()
        e.write([cand(3), cand(4)], [item(3, 75), item(4, 55)])
        md = e.run(now=datetime(2026, 11, 1, 14, 0, 0))[0]
        assert md.startswith("# Job digest — 2026-11-01 (run 2)")
        assert "### 3. Role 3" in md and "### 4. Role 4" in md and "### 1." not in md
        assert [s["n"] for s in e.sidecar()] == [1, 2, 3, 4]
        assert [s["scan_id"] for s in e.sidecar()] == ["u1", "u2", "u3", "u4"]
        assert (e.digests / ("digest_%s_run1.md" % DATE)).read_text() == first_md
        assert [s["n"] for s in e.sidecar("digest_%s_run1.json" % DATE)] == [1, 2]

    def test_third_run_gets_run2_archive(self, tmp_path):
        e = Env(tmp_path)
        for i in (1, 2, 3):
            e.write([cand(i)], [item(i, 80)])
            e.run()
        assert (e.digests / ("digest_%s_run1.md" % DATE)).exists()
        assert (e.digests / ("digest_%s_run2.md" % DATE)).exists()
        assert [s["n"] for s in e.sidecar()] == [1, 2, 3]
        assert (e.digests / ("digest_%s.md" % DATE)).read_text().startswith("# Job digest — 2026-11-01 (run 3)")

    def test_sidecar_shape(self, tmp_path):
        e = Env(tmp_path)
        e.write([cand(1)], [item(1, 77)])
        e.run()
        assert e.sidecar() == [{"n": 1, "scan_id": "u1", "company": "Co1", "title": "Role 1",
                                "url": "https://x.test/1", "score": 77}]

    def test_dry_run_writes_nothing(self, tmp_path):
        e = Env(tmp_path)
        e.write([cand(1)], [item(1, 77)])
        md, _ = e.run(dry_run=True)
        assert "### 1. Role 1" in md
        assert not e.digests.exists() and not e.seen.exists() and not e.runs.exists()


class TestLedger:
    def test_one_line_per_unseen_incl_excluded(self, tmp_path):
        e = Env(tmp_path)
        e.write([cand(1), cand(2), cand(3, triage="title-exclude", desc="skipped-title"), cand(4, seen=True)],
                [item(1, 88), item(2, 12), item(4, 90)])
        e.run()
        rows = {r["url_hash"]: r for r in e.ledger()}
        assert set(rows) == {"u1", "u2", "u3"}
        assert rows["u1"] == {"url_hash": "u1", "content_hash": "c1", "url": "https://x.test/1", "company": "Co1",
                              "title": "Role 1", "first_seen": DATE, "score": 88}
        assert rows["u2"]["score"] == 12
        assert rows["u3"]["score"] == 0 and rows["u3"]["triage"] == "title-exclude"

    def test_seen_never_appended(self, tmp_path):
        e = Env(tmp_path)
        e.seen.write_text(json.dumps({"url_hash": "u1", "content_hash": "c1"}) + "\n")
        e.write([cand(1), cand(2)], [item(1, 80), item(2, 80)])
        e.run()
        assert [r["url_hash"] for r in e.ledger()] == ["u1", "u2"]

    def test_not_scored_not_ledgered(self, tmp_path):
        e = Env(tmp_path)
        e.write([cand(1, desc="http 429"), cand(2, desc="skipped-max"), cand(3)], [item(3, 60)])
        e.run()
        assert [r["url_hash"] for r in e.ledger()] == ["u3"]

    def test_no_dedupe_run_skips_ledger(self, tmp_path):
        e = Env(tmp_path)
        e.write([cand(1)], [item(1, 80)])
        e.cp.write_text(json.dumps(cands_file([cand(1)], no_dedupe=True)))
        e.run()
        assert not e.seen.exists()

    def test_run_log_summary(self, tmp_path):
        e = Env(tmp_path)
        e.write([cand(1), cand(2, seen=True), cand(3)], [item(1, 80), item(3, 10)])
        e.run()
        log = (e.runs / "run_2026-11-01_103000.log").read_text().strip().splitlines()
        o = json.loads(log[-1])
        assert o == {"run_id": "2026-11-01_103000", "n_total": 3, "n_new": 2, "n_scored": 2, "n_matches": 1,
                     "total_cost_usd": 0.0421, "duration_sec": 140.0}

    def test_duration_null_without_timings(self, tmp_path):
        e = Env(tmp_path)
        e.write([cand(1)], [item(1, 80)], duration_sec=None)
        assert e.run()[1]["duration_sec"] is None


class TestCost:
    def test_table_from_usage(self, tmp_path):
        e = Env(tmp_path)
        e.write([cand(1), cand(2)], [item(1, 80), item(2, 60)])
        md = e.run()[0]
        cost = md.split("## Cost summary")[1]
        assert "| JDs scored | 2 |" in cost
        assert "| Input tokens (non-cached) | 1,000 |" in cost
        assert "| Input tokens (cache write) | 4,000 |" in cost
        assert "| Input tokens (cache read) | 120,000 |" in cost
        assert "| Output tokens | 2,500 |" in cost
        assert "| **Total cost (USD)** | **$0.0421** |" in cost
        assert "$3/M input, $15/M output, $3.75/M cache write, $0.30/M cache read" in cost

    def test_missing_scores_file(self, tmp_path):
        e = Env(tmp_path)
        e.write([cand(1)], [])
        e.sp.unlink()
        md, summary = e.run()
        assert "| **Total cost (USD)** | **$0.0000** |" in md
        assert "| not scored | Role 1 |" in md.split("## Not scored")[1].split("## Dropped")[0]
        assert summary["n_scored"] == 0 and summary["total_cost_usd"] == 0.0


class TestNotScored:
    def test_listed_with_status_and_link(self, tmp_path):
        e = Env(tmp_path)
        e.write([cand(1, desc="http 429"), cand(2, desc="timeout"), cand(3), cand(4), cand(5, desc="skipped-max"),
                 cand(6, title="A | B", desc="timeout")],
                [item(3, 70), dict(item(4, 0), status="parse-failed", score=None)])
        md = e.run()[0]
        sec = md.split("## Not scored")[1].split("## Dropped")[0]
        assert "| http 429 | Role 1 | Co1 | https://x.test/1 |" in sec
        assert "| timeout | Role 2 | Co2 | https://x.test/2 |" in sec
        assert "| score parse-failed | Role 4 | Co4 | https://x.test/4 |" in sec
        assert "| skipped-max | Role 5 |" in sec
        assert "Role 3" not in sec
        assert "| A \\| B |" in sec

    def test_title_excluded_and_seen_not_listed(self, tmp_path):
        e = Env(tmp_path)
        e.write([cand(1, triage="title-exclude", desc="skipped-title"), cand(2, seen=True, desc="skipped-seen")], [])
        sec = e.run()[0].split("## Not scored")[1].split("## Dropped")[0]
        assert "_None._" in sec and "Role" not in sec

    def test_cell_escapes_pipe(self):
        assert digest.cell("A | B\nC") == "A \\| B C"

    def test_main_exit_codes(self, tmp_path):
        e = Env(tmp_path)
        e.write([cand(1)], [item(1, 60)])
        argv = ["--candidates", str(e.cp), "--scores", str(e.sp), "--date", DATE]
        assert digest.main(argv + ["--dry-run"], root=tmp_path) == 0
        assert digest.main(argv, root=tmp_path) == 0
        assert (tmp_path / "digests" / ("digest_%s.md" % DATE)).exists()
        assert digest.main(["--candidates", str(tmp_path / "nope.json"), "--date", DATE], root=tmp_path) == 1
