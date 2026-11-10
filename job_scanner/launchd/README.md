# Scheduled jobs (launchd)

Three macOS launchd jobs run the scanner and the tracker. No Claude session stays open; the wrappers call the Python scripts, which call `claude -p` per item.

| Job | Template | Runs | Does |
|-----|----------|------|------|
| `<you>.job-scanner` | `job-scanner.plist.example` | Sun + Wed 11:00 | `run-scan.sh`: prefetch → score → digest → email |
| `<you>.job-tracker.check` | `job-tracker.check.plist.example` | every 5 min | `run-tracker.sh check`: read mail, update `state/applications.json`, reply "got it" |
| `<you>.job-tracker.digest` | `job-tracker.digest.plist.example` | daily 07:30 | `run-tracker.sh digest`: a check, then the tracker digest email |

## Before you install

Each of these must work from a plain terminal first. The jobs fail silently otherwise.

1. `config.md` has `Name`, `Email` and the **Mail** section (`Sender`, optional `Keychain service`).
2. `job_scanner/sources.yaml`, `companies.yaml` and `scoring_prompt.md` exist (copy the `.example` files).
3. The Gmail app password is in the Keychain (see [One-time setup](../README.md#one-time-setup)):
   ```bash
   security find-generic-password -a <sender> -s <keychain service> -w >/dev/null && echo ok
   ```
4. `claude` and `python3` resolve from `~/.zshrc` (the wrappers source it), `claude` is logged in, and that `python3` has PyYAML:
   ```bash
   zsh -c 'source ~/.zshrc; which claude python3; python3 -c "import yaml"'
   ```
5. A manual run passes: `/scan-jobs --dry-run --max 10` in Claude Code, and
   ```bash
   python3 job_scanner/track.py --check --dry-run
   ```

## Install

From the kit root. Set `PREFIX` to a label prefix of your own (your first name is fine; it must differ per clone on one Mac).

```bash
PREFIX=you
KIT="$(pwd)"
mkdir -p job_scanner/state/runs job_scanner/state/tracker   # launchd won't create log dirs
for j in job-scanner job-tracker.check job-tracker.digest; do
  sed -e "s|/path/to/claude-resume-kit|$KIT|g" -e "s|/Users/you|$HOME|g" -e "s|you\.job-|$PREFIX.job-|g" \
    job_scanner/launchd/$j.plist.example > ~/Library/LaunchAgents/$PREFIX.$j.plist
  plutil -lint ~/Library/LaunchAgents/$PREFIX.$j.plist
  launchctl bootstrap gui/$UID ~/Library/LaunchAgents/$PREFIX.$j.plist
done
```

To install only the scanner or only the tracker, trim the `for` list.

Check they're loaded:

```bash
launchctl list | grep "$PREFIX.job-"
launchctl print gui/$UID/$PREFIX.job-scanner | grep -E 'state|last exit'
```

## Run now, logs

```bash
launchctl kickstart -k gui/$UID/$PREFIX.job-scanner        # or .job-tracker.check / .job-tracker.digest
tail -f job_scanner/state/runs/launchd_*.log               # scanner
tail -f job_scanner/state/tracker/track.log                # tracker
```

launchd's own stdout/stderr go to `state/runs/launchd.{out,err}.log` and `state/tracker/launchd.{check,digest}.{out,err}.log`. A non-zero `last exit code` with an empty log usually means a missing log directory or a wrong path in the plist.

## Change the schedule

Edit `StartCalendarInterval` (scanner, digest) or `StartInterval` in seconds (check) in `~/Library/LaunchAgents/$PREFIX.<job>.plist`, then reload:

```bash
launchctl bootout gui/$UID/$PREFIX.job-scanner
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/$PREFIX.job-scanner.plist
```

Two clones sending from one Gmail account: give them different times so the sends don't overlap.

## Uninstall

```bash
for j in job-scanner job-tracker.check job-tracker.digest; do
  launchctl bootout gui/$UID/$PREFIX.$j
  rm ~/Library/LaunchAgents/$PREFIX.$j.plist
done
```

## Notes

- **Sleep:** a calendar job missed while the Mac sleeps runs once on wake. The 5-minute check just resumes. Nothing runs while the Mac is off.
- **Moving the kit:** the plists hold absolute paths. Uninstall, move, install again.
- **Pulling updates:** the installed plists are copies; `git pull` doesn't touch them. Reinstall only if a `.plist.example` changed.
