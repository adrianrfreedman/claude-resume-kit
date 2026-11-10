# job_scanner

Autonomous job scanner. Scrapes Israeli + remote boards and curated company career pages, scores each posting against the candidate's role bundles with Claude Sonnet 4.6, writes a ranked Markdown digest, and emails it (with a bottom-line cost summary).

## Files

| Path | Purpose |
|------|---------|
| `../.claude/skills/scan-jobs/SKILL.md` | Interactive `/scan-jobs` wrapper: runs the scripts below via Bash and reads the digest back. |
| `sources.yaml` | Job board configs (LinkedIn IL, AllJobs, Drushim, Glassdoor IL, Wellfound, YCS). Personal, gitignored; copy from `sources.example.yaml`. |
| `companies.yaml` | Curated company career pages. Personal, gitignored; copy from `companies.example.yaml`. |
| `prefetch.py` | Parallel fetch, card parsing (LinkedIn, AllJobs, Drushim) + dedupe + JD bodies; writes `state/candidates_YYYY-MM-DD.json`. |
| `score.py` | Parallel scoring: one MCP-free headless Sonnet call per JD; writes `state/scores_YYYY-MM-DD.json`. |
| `digest.py` | Renders `digests/digest_YYYY-MM-DD.md` + `.json` sidecar from the candidates and scores files; appends `state/seen.jsonl` and the run log. |
| `send_digest.py` | Emails the digest. |
| `scoring_prompt.md` | Cached system prompt: profile + bundles + scoring rubric. Personal, gitignored; copy from `scoring_prompt.example.md`. |
| `state/seen.jsonl` | Dedupe ledger (created on first run). |
| `state/candidates_YYYY-MM-DD.json` | Prefetch output: candidates, per-source status, raw board pages (only for a query page where no card parsed). |
| `state/scores_YYYY-MM-DD.json` | Score output: per-JD score/tier/bundle/rationale, total cost and usage. |
| `state/runs/` | Per-run logs (`run_<ts>.log` summary JSON from `digest.py`, `launchd_<ts>.log` from the wrapper). |
| `digests/digest_YYYY-MM-DD.md` / `.json` | Output digest and sidecar (`n`, `scan_id`, `company`, `title`, `url`, `score`); a second run the same day keeps the first as `_run1`. |
| `launchd/*.plist.example` | launchd manifests (scanner Sun + Wed 11:00; tracker check and digest). Install with [`launchd/README.md`](launchd/README.md); `.plist` copies in `launchd/` are gitignored. |
| `launchd/run-scan.sh` | Wrapper script invoked by launchd. |
| `launchd/no-mcp.json` | Empty MCP config (`{"mcpServers":{}}`) used to keep MCP connectors out of headless calls. |

## Pipeline

Four scripts, run in order. The launchd job (`launchd/run-scan.sh`) runs all four back to back with no Claude session; Claude is only used per JD inside `score.py`.

1. `prefetch.py` does all fetching and dedupe in one parallel pass (8 threads, 20 s per request, 240 s global deadline): LinkedIn guest-API cards, AllJobs and Drushim cards (parsed into candidates with a job URL, title, company, city), company ATS pages, then JD bodies for unseen candidates only. `raw_pages` (3000 chars) is kept only for a board query where no card parsed. Writes `state/candidates_<date>.json`.
2. `score.py` scores each scorable JD in a parallel headless Sonnet call (MCP disabled: ~600 tokens and ~$0.003 per JD instead of ~266k tokens) into `state/scores_<date>.json`.
3. `digest.py` ranks matches (threshold `settings.min_score_to_email`, default 50), writes `digests/digest_<date>.md` and the `.json` sidecar the tracker reads, lists unscored listings under "Not scored" (retried next run), and appends `state/seen.jsonl` and `state/runs/run_<ts>.log`. `--dry-run` prints the digest and writes nothing.
4. `send_digest.py` emails the digest.

Failures never stop the run; JDs that could not be scored show up in the digest's "Not scored" section. Flags: prefetch `--out`, `--deadline`, `--source`, `--no-dedupe`, `--max`; score `--candidates`, `--out`, `--concurrency`, `--model`, `--deadline`, `--limit`; digest `--candidates`, `--scores`, `--date`, `--dry-run`.

Optional `settings.title_exclude` in `sources.yaml` is a list of case-insensitive regexes; unseen candidates whose title matches get `triage: "title-exclude"`, no body fetch, and do not use the `--max` budget (see `sources.example.yaml`). `digest.py` ledgers them with `score: 0`.

An interactive `/scan-jobs` runs the first three via Bash, so allow `Bash(python3 ./job_scanner/prefetch.py *)`, `Bash(python3 ./job_scanner/score.py *)` and `Bash(python3 ./job_scanner/digest.py *)` in `.claude/settings.local.json`. In that allowlist, `Write(./job_scanner/**)` rules are ignored by Claude Code; only `Edit(./job_scanner/**)` counts (it covers writes too).

## One-time setup

### 1. Generate a Gmail app password and store it in Keychain

The scanner emails digests via Gmail SMTP using an app password (the Claude.ai Gmail MCP is draft-only; it can't actually send). Mail goes out from the `Sender` account in `config.md`, To the candidate (`Email`), CC the sender.

1. In the sender's Google account (`<sender>`), go to **Security → 2-Step Verification → App passwords** and generate a new app password named **job-scanner**. Copy the 16-character string.
2. Store it in macOS Keychain (so it never lives on disk):
   ```bash
   security add-generic-password \
       -a <sender> \
       -s <keychain service> \
       -w '<16-char-app-password>'
   ```
3. Smoke-test the sender against an existing digest:
   ```bash
   cd /path/to/claude-resume-kit
   python3 job_scanner/send_digest.py job_scanner/digests/digest_<date>.md
   ```
   You should see "Sent digest …" and the email should arrive at `<candidate email>` (CC `<sender>`).

### 2. Test interactively

From the repo root, in a Claude Code session:

```
/scan-jobs --dry-run --max 10
```

Confirm the digest prints (`--dry-run` writes nothing; drop it to write the files) and the cost summary is sensible.

### 3. First live run

```
/scan-jobs --max 20
```

Confirm email arrives at `<candidate email>` (CC `<sender>`).

### 4. Install the scheduled jobs

See [`launchd/README.md`](launchd/README.md): scanner, tracker check and tracker digest, with install, logs, schedule changes and uninstall.

## Application tracker

`track.py` reads the candidate's mail (config.md Name/Email) over IMAP (read-only), keeps `state/applications.json` up to date and sends a daily digest. Tagged Message-IDs use `<first>-job-scanner.local`, so two clones on one Gmail account ignore each other's threads.

- **Four kinds of incoming mail:** replies to a scan digest (`scan`), replies to an application package (`package`), replies to a tracker "got it" (`ack`) or digest (`tracker`), and anything sent to the `+jobs` alias (`alias`). Each relevant message gets one Haiku call (`claude -p`).
- **"Got it" replies:** every processed message gets a threaded reply saying what was recorded. Reply to correct it.
- **Digest:** 07:30 daily, To the candidate, CC the sender. Runs a check first, then sends.
- **Locking:** `state/tracker/track.lock`. `--check` exits silently if another run holds it; `--digest` waits up to 10 minutes, then exits 1. `--dry-run` skips the lock; a real `--replay` waits like `--digest`. An empty real `--check` prints and writes nothing.

**Reply-To / From:** mail goes out From the sender's account with `Reply-To: <sender local part>+jobs@<sender domain>` (the alias, derived from `Sender`). Gmail rewrites an unverified From address to the account's own. Optional: add the alias under Gmail Settings > Accounts > "Send mail as" and verify it, so From shows as intended.

Install, logs and uninstall: [`launchd/README.md`](launchd/README.md).

**State** (`state/`, `state/tracker/`):

- `applications.json`: the application store.
- `tracker/processed.json`: ledger of handled message IDs.
- `tracker/failures.jsonl`: one line per failed message (3 attempts, then given up).
- `tracker/failed/*.eml`: raw failed messages, for `--replay`.

**Manual runs:**

```bash
python3 job_scanner/track.py --check --dry-run            # classify + intended changes; writes/sends nothing
python3 job_scanner/track.py --replay failed/<id>.eml [--dry-run]   # one .eml through the pipeline, ignoring the ledger
python3 job_scanner/track.py --digest --dry-run           # writes state/tracker/digest_<date>.{html,txt}
python3 job_scanner/track.py --digest --preview-to-sender # sends to the sender only, no check, leaves last_digest.json alone
```

Tests: `uvx --with pyyaml pytest job_scanner/ -q`

## Setup

1. Copy `sources.example.yaml` to `sources.yaml` and `companies.example.yaml` to `companies.yaml`; fill in your own.
2. Copy `scoring_prompt.example.md` to `scoring_prompt.md` and fill in the placeholders (gitignored).
3. Fill the **Mail** section of `config.md` (`Sender`, optional `Keychain service`, default `job-scanner-gmail`); the recipient and From name come from `Name` and `Email`. CC the sender is dropped when the recipient is the sender.
4. Add the app password: `security add-generic-password -a <sender> -s <keychain service> -w`.
5. Install the scheduled jobs: [`launchd/README.md`](launchd/README.md).

## Tuning

- **Add/remove a company:** edit `companies.yaml`.
- **Add a search query:** edit `sources.yaml` → the source's `queries` list.
- **Change the schedule:** edit the `StartCalendarInterval` in the plist, then reload (see [`launchd/README.md`](launchd/README.md#change-the-schedule)).
- **Lower the email noise:** raise `min_score_to_email` in `sources.yaml`.
- **Disable a flaky source:** set `enabled: false` on that source.

## Cost expectations

Expect roughly:
- Light run (~10 JDs): ~$0.04
- Typical run (~25 JDs): ~$0.10
- Heavy run (~50 JDs): ~$0.30

Daily cadence ≈ $1–$5/month. Every digest includes a precise cost summary in its footer.
