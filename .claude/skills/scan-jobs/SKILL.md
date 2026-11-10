---
name: scan-jobs
description: Interactive wrapper over the job-scanner scripts for the candidate named in config.md. Runs prefetch.py (boards + company pages), score.py (Sonnet per JD) and digest.py (ranked Markdown digest, sidecar, ledger), then reads the digest back. Never emails; send_digest.py does that.
---

# /scan-jobs — Job Scanner (interactive wrapper)

The scan is four Python scripts: `prefetch.py` → `score.py` → `digest.py` → `send_digest.py`. The launchd job (`launchd/run-scan.sh`) runs all four with no Claude session. `/scan-jobs` runs the first three through Bash and reads the result. The scripts do all fetching, scoring and digest writing.

## Rules

- **Never score inline.** `score.py` scores; this session does not.
- **Never spawn subagents.**
- **Never fetch JD bodies or listing pages by hand** (no WebFetch of boards or postings). `prefetch.py` does it.
- A listing the scripts could not score goes in the digest's "Not scored" section and is retried next run. Do not work around it.
- **Never email** (Step 6).

## Inputs

- `job_scanner/sources.yaml` — board configs; `settings.min_score_to_email` (default 50) is the digest threshold
- `job_scanner/companies.yaml` — curated company career pages
- `job_scanner/scoring_prompt.md` — system prompt for per-JD scoring (above `## Per-JD Input`) + per-JD template
- `config.md` (repo root) — the candidate's identity + email
- every `resume_builder/bundles/bundle_*.md`

## State

- `job_scanner/state/seen.jsonl` — dedupe ledger, written by `digest.py`: `{"url_hash", "content_hash", "url", "company", "title", "first_seen", "score"}` (title-excluded ones add `"triage": "title-exclude"`, `"score": 0`).
- `job_scanner/state/candidates_<YYYY-MM-DD>.json` — prefetch output.
- `job_scanner/state/scores_<YYYY-MM-DD>.json` — score output.
- `job_scanner/state/runs/run_<timestamp>.log` — run summary JSON, written by `digest.py`.
- `job_scanner/digests/digest_<YYYY-MM-DD>.md` and `.json` — digest and sidecar (the tracker resolves "#3" from the sidecar). A second run on the same date moves the first to `digest_<date>_run1.*` and continues numbering.

## Flags

Pass through to the script that owns them:

- `--no-dedupe` (prefetch) — ignore `seen.jsonl`; digest then does not write the ledger.
- `--max <N>` (prefetch) — cap JD bodies fetched/scored (default `settings.max_total_jds`).
- `--source <id>` (prefetch) — one source id (`companies` = company pages only).
- `--limit <N>` (score) — score at most N JDs; handy for smoke tests.
- `--dry-run` (digest) — print the digest, write nothing (no files, no ledger, no run log).

---

## Pipeline

### Step 1 — Bootstrap
Read `config.md`, then run Steps 2-4. You do not need the bundles or the scoring prompt in context; the scripts read them.

### Step 2 — Prefetch
Run `python3 job_scanner/prefetch.py` via Bash (one call, pass through `--source`, `--no-dedupe`, `--max`). It fetches every board query and company page, parses LinkedIn, AllJobs and Drushim cards into candidates, dedupes against `seen.jsonl`, applies `settings.title_exclude`, fetches JD bodies for unseen candidates and writes `state/candidates_<today>.json`. It exits 0 even when sources fail.

### Step 3 — Score
Run `python3 job_scanner/score.py` via Bash (one call, pass through `--limit`; allow a long Bash timeout, up to 10 min). It makes one MCP-free headless Sonnet call per scorable JD and writes `state/scores_<today>.json` with scores, cost and usage.

### Step 4 — Digest
Run `python3 job_scanner/digest.py` via Bash (pass through `--dry-run`). It ranks matches (Strong 85-100, Good 70-84, Worth-a-look threshold-69), writes the digest and sidecar, a "Not scored" section, a "Dropped" table, the cost summary and a prefetch line, appends the ledger and the run log. Exit 1 means no candidates file or a write failure: report it and stop.

### Step 5 — Read and summarize
Read `job_scanner/digests/digest_<today>.md` and tell the user the headline: matches, top entries, anything in "Not scored", failed sources. Only if it adds something (a standout match, a deadline, a repeat posting of a package already built), prepend a short "What's new" paragraph directly under the header line. Change nothing else in the file.

### Step 6 — DO NOT email the digest from inside this skill

**The skill never sends email.** Email is handled out-of-band:

- **Cron / launchd path:** `launchd/run-scan.sh` runs `python3 job_scanner/send_digest.py <digest>` after `digest.py`. This is the authoritative path for autonomous runs.
- **Interactive path:** if the user wants the digest emailed after an ad-hoc `/scan-jobs` invocation, they run `python3 job_scanner/send_digest.py job_scanner/digests/digest_<date>.md` themselves.

This split exists because earlier versions of this skill sent the email inline AND the wrapper sent it again, producing duplicate emails. Do not re-introduce inline sending under any flag; if sending behavior needs to change, update `send_digest.py` or the wrapper, not this skill.

---

## Error handling

- Source failures, rate limits and login walls (LinkedIn is best-effort) are recorded by prefetch in the candidates file and the digest's Prefetch line. Do not retry by hand.
- `score.py` failure or `deadline_hit: true`: unscored JDs show up under "Not scored". Re-run `score.py` then `digest.py` only if the user asks; a second digest run the same day becomes "run 2".
- A whole source returning zero listings two runs in a row: mention it to the user; they can disable it in `sources.yaml`.

## Non-goals

This skill does NOT:
- Apply to jobs.
- Generate resumes or cover letters (use `/make-resume` and `/make-cl` for that on top matches).
- Track application status.
