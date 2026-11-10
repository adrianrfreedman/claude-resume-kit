---
description: Read the candidate's email reply to a sent package, apply the requested edits, and email the updated package back in the same thread
user-invocable: true
---

# /revise-package

**User input:** `$ARGUMENTS` is a session file path (`output/<Folder>/session_<name>.md`) or a company
name. If it is empty, use the most recent Active Sessions row whose Status has a `Sent:` line.

Optional flags:

- **`--reply <path>`**: use this already-saved reply file (and any attachments saved beside it with
  the same stem). **Skip step 1's fetch.**
- **`--unattended`**: run with no human present (the tracker uses this).
  - Never call AskUserQuestion.
  - Requests that would go to the user (provenance conflicts, KB corrections, unclear wording) are
    **held back**. Each goes in the email's **Not changed** section with the reason in plain words.
    For an unclear one, add a question back to the candidate.
  - Every other rule still applies, including the render gates.
  - If a render gate fails (the resume isn't 2 pages, or the letter isn't 1 page), don't send. Exit
    with a clear failure message, so the tracker logs it and retries.
- **`--no-send`**: do everything except the real send. Run the `send_package.py ... --dry-run` step
  and stop there. This is for testing.

Runs in the kit root. Each step reuses an existing skill's rules;
this file adds sequencing only.

## 1. Fetch

With `--reply`, skip the fetch: read that reply file and its attachments, then go to step 2.

Read the session file. Take the email subject from the last `Sent:` line, or rebuild it as
`Application package: <Company> <Role>`.

```bash
python3 job_scanner/fetch_replies.py output/<Folder> --subject "<subject>" --since <date of first Sent>
```

- **"No new replies."** Say so and stop.
- **Otherwise:** read every new `output/<Folder>/replies/reply_*.md`, oldest first, and any
  attachments saved beside them. Skip any reply whose front matter has `intent: applied`; those are
  "I applied" messages, not edits. An annotated PDF is a list of edits too: read its markup.

## 2. Turn the reply into an edit list

Number each request. Sort each into one of five kinds:

| Kind | Action |
|---|---|
| Wording or emphasis | Apply. |
| A fact about the candidate (a skill, a date, a duty, a tool) | Apply. The candidate is the source. Record it in `config.md` as "confirmed by the candidate, <date>", like the Excel line. |
| Conflicts with `config.md` Provenance Flags or the KB Corrections Log (for example, a claim of presenting at ASCO) | Don't apply. Ask the user. |
| A question | Answer it in the reply email; no edit. |
| Unclear | Ask the user, quoting the reply word for word. Never guess the meaning. |

Ask every question for the user in one AskUserQuestion, then continue. With `--unattended`, don't ask:
hold those requests back (see the flag above).

## 3. Apply

Follow `.claude/skills/edit-resume/SKILL.md` for the rules: provenance, verb discipline, the
AI-fingerprint scan, and the render gates. Its MANDATORY STOP does not apply here, because the candidate's
reply is the approval. Then:

- Re-render each changed document and Read the PDF. The resume stays 2 pages. The letter stays
  1 page and 250–300 words, unless the reply asked for something longer; if so, say that in the email.
- Update `e2e_<name>_cover_letter.txt` if the letter changed.
- If a changed fact appears on the interview-prep page, change it there too.
- Re-copy `<Full Name> - CV - <Company>.pdf` and `<Full Name> - CL - <Company>.pdf` (the Finalization step in
  `resume_builder/reference/shared_ops.md`).
- Log `### Edit N (<date>): from the candidate's reply`, with each request mapped to what was done.

## 4. Email the update in the same thread

Write `output/<Folder>/send_<name>_rev<N>.html` from `resume_builder/templates/send_email_template.html`:

- Keep **How to apply**.
- Replace Summary with **What changed**: one line per request, in the reply's words, then what was done.
- Add **Not changed** when anything was held back, with the reason in plain words.
- Add **Your questions** when the reply asked any.
- Drop Critique and Interview prep unless a change touched them.

Write the plain-text twin `send_<name>_rev<N>.txt`. Run a dry run, then send:

```bash
python3 job_scanner/send_package.py output/<Folder> --subject "<subject>" \
  --body output/<Folder>/send_<name>_rev<N>.txt --html output/<Folder>/send_<name>_rev<N>.html \
  --reply output/<Folder>/replies/<latest reply>.md --dry-run
```

With `--no-send`, stop here. Otherwise run it again without `--dry-run`. Send without a further stop:
the reply asked for this. The one exception is when a step 2 question for the user is still open; then
don't send.

## 5. Log

Append `Sent: revision <N> <date> (reply to <reply file>)` to the session Status, and update the
Active Sessions row in `CLAUDE.md`. Report to the user: the requests, what was applied, what was held
back, and that the email went. With `--no-send`, skip the `Sent:` line and the row update, and say no
email went.

The candidate can reply again; running `/revise-package` again picks up only replies not already fetched.
