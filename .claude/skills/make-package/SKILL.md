---
description: Run the whole application package end to end — resume, critique, edits, cover letter, critique, interview prep — in one session
user-invocable: true
---

# /make-package

**User input:** `$ARGUMENTS` — a JD path (`JDs/foo.txt`), inline JD text, or a session file path to resume a part-built package. Optional `Send: email|none` anywhere in it pre-answers the Send step.

Runs the full pipeline in **this** session. Each leg is the existing skill, read and followed in full — this file adds sequencing and nothing else.

## Legs

| # | Leg | Read and follow | Argument |
|---|-----|-----------------|----------|
| 1 | Resume | `.claude/skills/make-resume/SKILL.md` | the JD |
| 2 | Critique (**subagent**) | `.claude/skills/critique/SKILL.md` | the session file |
| 3 | Edit | `.claude/skills/edit-resume/SKILL.md` | resume + critique file |
| 4 | Cover letter | `.claude/skills/make-cl/SKILL.md` | the session file |
| 5 | Critique (**subagent**) | `.claude/skills/critique/SKILL.md` | the session file |
| 6 | Edit | `.claude/skills/edit-resume/SKILL.md` | only if leg 5 found Tier 1 items |
| 7 | Interview prep | `.claude/skills/make-interview-prep/SKILL.md` | the session file |

Update the session file Status and the `CLAUDE.md` Active Sessions row after each leg, as each skill already instructs.

## Stops

Keep exactly the two human gates in `/make-resume`: **role type + bundle + framing** (end of Phase 0) and **the bullet plan** (end of Phase 1). Both are cheap to answer and catch a misaligned package before six legs of work land on top of it.

Drop every other mandatory stop in the chained skills, including the "copy this after /clear" hand-offs. Those exist to end a session; this skill continues instead. Announce each leg in one line as you start it.

Stop and ask outside the two gates only when a leg hits something the user must decide: a provenance question, a factual gap, or a critique finding that needs a real-world action rather than an edit.

## Edit legs

Apply Tier 1 findings only. Tier 2 goes in the session file for the user to weigh later. If a critique recommends a keyword naming a duty the user has not performed, the keyword-insertion guard in `critique_framework.md` applies — decline it and say so. Skip the leg when there are no Tier 1 items.

## Resuming

If `$ARGUMENTS` is a session file, or one already exists for this JD, read its Status and start at the first leg not yet done. Never re-run a completed leg.

## Critique legs run in a fresh subagent

A critique written in the session that wrote the documents reads its own work and scores it high. So legs 2 and 5 go to one `Agent` call each (general-purpose, no model override), and wait for its result before the edit leg. Give it only paths, never your own view of the documents:

> Working directory `<kit root>`. Read `.claude/skills/critique/SKILL.md` and follow it in full for `output/<Folder>/session_<name>.md` (Pass N). The output is HTML→PDF: read the `.html` and the rendered `.pdf`, ignore the `.tex`/`char_count.py`/`pdflatex` steps. Apply the keyword-insertion guard. Write/append `critique_<name>.md` and update the session file's Critique Summary and Status. Skip the skill's MANDATORY STOP. Return: dimension scores and total, Tier 1 items (current → proposed text, source in the experience files), Tier 2 items, guard-declined keywords, and any accuracy problem.

The main session still owns the edit legs and any question for the user; a provenance question the critique raises comes back to the user, not to the subagent. Report scores as fresh-context.

`ponytail: only the critiques are isolated — resume, letter and edits need the user's gate answers in context; interview prep could move to a subagent too if context gets tight.`

## Done

Run the **Finalization** steps in `resume_builder/reference/shared_ops.md` before reporting. The
critique-approval stop those steps normally hang off does not exist in this skill, so they would
otherwise never fire and the package would have no submission-named files.

That produces the two files that actually get attached:

```bash
cp e2e_<name>_[resume|cv].pdf "<Full Name> - CV - <Company>.pdf"
cp e2e_<name>_cover_letter.pdf "<Full Name> - CL - <Company>.pdf"
```

Then report: files written (naming the two submission PDFs first), both critique scores (fresh-context), Tier 1 items applied, Tier 2 items left open, gaps held open in the documents, and any
acronyms dropped.

## Send (optional)

Sending reaches the candidate, so it is never automatic. If `$ARGUMENTS` had `Send:`, use that; otherwise
ask once after the report (AskUserQuestion: Email · Don't send). `none` or
"Don't send" ends the skill.

1. Write the message twice:
   - `output/<Folder>/send_<name>.html` is the email body. Copy
     `resume_builder/templates/send_email_template.html` and fill every `{{…}}`. Set ACCENT to the
     resume's accent and WASH to a light tint of it. It has the sections **How to apply**,
     **Summary**, **Next steps**, **Critique** (fresh-context scores, what was fixed, what is still
     the candidate's call, what is deliberately not claimed) and **Interview prep** (question count, the 2–3 to
     rehearse first, the hardest one). Write in plain words for the candidate, not critique shorthand. Under the headline, link the job posting the package was built from (the URL in the session file or JD); if there was none, say "no posting link".
   - `output/<Folder>/send_<name>.txt` is a few plain lines: role, job posting link, how to apply, next steps. It is
     the fallback for mail clients that don't show HTML.
2. Run a dry run first, then send:
   ```bash
   python3 job_scanner/send_package.py output/<Folder> --subject "Application package: <Company> <Role>" \
     --body output/<Folder>/send_<name>.txt --html output/<Folder>/send_<name>.html --dry-run
   ```
   Then run it again without `--dry-run`, adding
   `--company "<Company>" --role "<Role>" --job-url "<posting URL>"`. This adds the package to
   the candidate's application tracker as "prepared".
   - It sends to the candidate with a CC to the sender, using the Gmail app password in the Keychain. It
     attaches `<Full Name> - CV - <Company>.pdf`, `<Full Name> - CL - <Company>.pdf`, the plain-text cover letter and the interview-prep page.
3. Report what was sent, and log it in the session file Status as `Sent: email <date>`.

When the candidate replies with edits, run `/revise-package output/<Folder>/session_<name>.md`.

