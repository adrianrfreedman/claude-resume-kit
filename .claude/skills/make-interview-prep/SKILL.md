---
description: Generate an interview-prep page (likely questions + collapsed talking points) from a finished session file
user-invocable: true
---

# /make-interview-prep

**User input:** `$ARGUMENTS`

Parse `$ARGUMENTS`:
- Session file path (e.g., `output/Acme/session_acme_engineer.md`) → read that session file
- Session name (e.g., `acme_engineer`) → find it via the derivation protocol in `shared_ops.md`
- Empty → check `CLAUDE.md` Active Sessions for the most recent package

Output: `output/<FolderName>/interview_prep_<name>.html` — a standalone HTML page, opened in a browser, not compiled.

---

## Safety Rules (ALWAYS ENFORCED)

**Accuracy > Relevance > Impact > ATS > Brevity**

- Every figure quoted in a talking point must be traceable to `resume_builder/experience/` or `config.md` Provenance Flags. This document is what the candidate will say **out loud** — an inflated number here is worse than an inflated number on the page.
- Never coach a claim the resume does not support. If a bullet says "produced the validation set", the prep page says "produced", and says so explicitly as a warning.
- Read `config.md` Provenance Flags before writing any card about a publication.

---

## Startup

1. Read `CLAUDE.md` — Active Sessions and KB Corrections
2. Read `config.md` — Provenance Flags, personal info
3. Read the session file, specifically: **JD Analysis** (gaps), **Company Context**, **Critique Context** (reviewer persona, competitive landscape), **Framing Strategy**
4. Read the finished resume and, if it exists, the cover letter — the prep page must cover what those documents actually claim
5. If a critique exists (`critique_<name>.md`), read it: the **predicted first interview question**, the **gap ranking**, and any **Interview Bridge Points** are the raw material for this page

**Recovery check:** if the resume Status is not DONE, stop and say so. This skill depends on a finished document.

---

## Phase 1: Build the question set

Target **18-22 questions** in these groups. Drop a group only if the session file makes it irrelevant; never pad one to hit a number.

| Group | What goes in it |
|---|---|
| Opening moves | "Tell me about yourself", "why us", plus any **career-timeline** question the resume creates (a break, a pivot, a relocation) |
| The role itself | One question per named duty in the JD. If the posting lists five duties, this group has roughly five questions. |
| Domain-specific | The technical spine of the role — the methods, tools or judgment calls the reviewer persona works with daily |
| The gaps | One question per **Serious** gap in the critique's gap ranking. These get the most preparation, not the least. |
| Shape of the role | Commitment, salary, what a year from now looks like |
| Questions for the interviewer | One card, 4-6 questions, each with a line on what the answer reveals |

**Sourcing rule:** every question must be derivable from the JD, the resume, or the critique. No generic interview-question filler ("where do you see yourself in five years") unless the session file gives it a reason to be there.

## Phase 2: Write the talking points

Each question is one collapsed card. Inside:

- **3-5 bullets**, in speaking order. Not a script — the points to hit, and the sequence.
- Lead the first bullet with the **framing**, not the fact. The facts are already on the resume; the card supplies the angle.
- At least one bullet per card carries a **specific number, name or date** from the experience files. Concrete beats fluent.
- Where a card has an obvious follow-up, pre-load it in an `.avoid` block labelled **Prepare the follow-up**.
- Where there is a phrase that will sink the answer, put it in an `.avoid` block labelled **Do not say**, and say why.
- For the two or three highest-stakes cards, add one `.say` block: a single sentence in the candidate's own register, ready to lift verbatim. Use these sparingly — a page of scripted lines reads as a page of scripted lines.

**Gap cards get a fixed shape:** concede in one sentence using the correct technical term, name the genuine overlap, name precisely what is still to learn, then offer the nearest real adjacency. Concede first. A gap answer that opens with the mitigation reads as evasion.

**Verb-discipline warnings are mandatory** wherever the resume hedges. Contributing-author work, tools validated rather than built, programmes joined rather than led: each gets an explicit "never say X" warning, because a technical reviewer will check the author list.

## Phase 3: Build the page

Read `resume_builder/support/ai_fingerprint_rules.md` — the banned words apply to this page too.

**Before writing the HTML, load the `artifact-design` skill** and produce a short design plan (color, type, layout). Requirements that do not change:

- **Collapsed by default.** Native `<details>`/`<summary>` — the question is the summary, the talking points are hidden until the question has been answered aloud. No JavaScript beyond an optional open-all toggle.
- **Standalone document.** Full `<!doctype html>`, `<head>`, fonts via a Google Fonts `<link>` with a real fallback stack. It is opened from disk, not published.
- **Light and dark.** Token-level `:root`, `@media (prefers-color-scheme: dark)`, and `:root[data-theme="dark"]`. Never define a color only inside a media block.
- **Tie it to the package.** Carry the resume's accent color so the two documents read as one piece of work.
- **Print rule:** `details { break-inside: avoid; }` and hide the toggle button.

**Close with an acronym expansion table** listing every short form that was expanded out of the resume, with the long form to say aloud. This is the single most-used part of the page — see the acronym rule in `config.md` / user memory.

## Phase 4: Verify

- [ ] Every number on the page traced to an experience file — check each one, do not assume
- [ ] Every hedged resume claim has a matching verb-discipline warning
- [ ] Every **Serious** gap from the critique has its own card
- [ ] Question count 18-22, and no card with fewer than 3 bullets
- [ ] Opens in a browser with all cards collapsed; the toggle opens and closes them
- [ ] Renders correctly in both themes
- [ ] Spelling convention matches the resume (American or British — do not mix)

**Update the session file** — add the page to Output Files, Status: `Interview Prep: DONE`.

### >>>>>> MANDATORY STOP <<<<<<
Present: question count by group, which gaps got cards, and any question likely to be uncomfortable.
**You MUST wait for the user's explicit text response before continuing.**
