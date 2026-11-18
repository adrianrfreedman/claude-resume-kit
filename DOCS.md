# Documentation

Detailed reference for claude-resume-kit. For the pitch and quick start, see [README.md](README.md). For the job scanner and tracker setup, see [job_scanner/README.md](job_scanner/README.md).

Contents: [Architecture](#architecture) · [Concepts](#concepts) · [Workflows](#workflows) · [Job scanner and tracker](#job-scanner-and-tracker) · [Customization](#customization) · [Key Design Decisions](#key-design-decisions) · [FAQ](#faq)

---

## Architecture

Tracked files are the tooling. Everything marked **(local)** is your data, created on your machine and gitignored.

```
claude-resume-kit/
├── README.md, DOCS.md, LICENSE
├── CLAUDE.example.md                  # Copy to CLAUDE.md (local): project rules, Active Sessions, KB corrections
├── config.md                          # (local) Your identity, provenance flags, role types, output rules
├── .claude/skills/                    # 10 skills, invoked as /skill-name
│   ├── setup-extract/                 # Source (paper, CV, LinkedIn export, write-up, code) → extraction
│   ├── setup-build-kb/                # Extractions → experience files, bundles, taxonomy
│   ├── make-resume/                   # JD → research → bullet plan → resume/CV (HTML → PDF)
│   ├── make-cl/                       # Session → cover letter (HTML → PDF + plain text)
│   ├── critique/                      # Independent review: 5 readers, 8 dimensions, tiered fixes
│   ├── edit-resume/                   # Apply critique or your feedback to the resume/CV/letter
│   ├── make-interview-prep/           # Standalone HTML page: likely questions, collapsed talking points
│   ├── make-package/                  # All of the above in one session, then optional email
│   ├── revise-package/                # Apply the candidate's emailed edits, reply in the same thread
│   └── scan-jobs/                     # Interactive wrapper over the job scanner scripts
├── resume_builder/
│   ├── templates/
│   │   ├── resume_template.html       # Resume/CV template (default)
│   │   ├── coverletter_template.html  # Cover letter template (default)
│   │   ├── send_email_template.html   # Package email body (used by /make-package, /revise-package)
│   │   ├── resume.cls, cv.cls         # Legacy LaTeX classes
│   │   ├── resume_template.tex, cv_template.tex, coverletter_template.tex   # Legacy LaTeX templates
│   │   └── GS.png, orcid.png          # Icons used by the LaTeX templates
│   ├── helpers/
│   │   ├── render_pdf.sh              # HTML → PDF via headless Chrome; prints the page count
│   │   └── char_count.py              # Legacy LaTeX only: rendered-character counter
│   ├── reference/                     # Rules the skills read
│   │   ├── shared_ops.md              # Startup, session files, folder layout, finalization
│   │   ├── resume_reference.md        # Resume/CV rules and section specs
│   │   ├── cl_reference.md            # Cover letter rules
│   │   ├── critical_rules.md          # Compact generation-time re-read
│   │   ├── session_file_template.md   # Session file format
│   │   └── critique_framework.md      # The critique protocol and output template
│   ├── support/
│   │   └── ai_fingerprint_rules.md    # Tracked: banned words, structural tells, post-generation checklist
│   │                                  # (local) skills_taxonomy.md, pub_metadata.md, ... from /setup-build-kb
│   ├── experience/                    # (local) One file per position, from /setup-build-kb
│   ├── bundles/                       # (local) One file per role type, from /setup-build-kb
│   └── examples/                      # Fictional worked examples (see below)
├── knowledge_base/                    # (local) Your raw material and extractions
│   ├── papers/                        # Drop PDFs, .tex, CVs, exports, write-ups here
│   ├── notes/                         # Any other reference material
│   └── extractions/                   # Written by /setup-extract
├── JDs/                               # Job descriptions; only example_jd.txt is tracked
├── output/                            # (local) One folder per application
└── job_scanner/                       # Optional, macOS: scanner, tracker, mail, sheet mirror
```

`resume_builder/examples/` holds a fictional researcher and a fictional backend engineer:

| Path | What it is |
|------|-----------|
| `example_config.md` | Academic-style `config.md` (every section filled in) |
| `example_config_industry.md` | Industry `config.md`: no publications, Projects instead |
| `example_session_file.md` | A finished session file |
| `extractions/`, `experience/`, `bundles/` | One example of each KB file type |
| `example_resume.pdf`, `example_cover_letter.pdf` | What the output looks like |
| `output/*.tex` | Legacy LaTeX output samples |

`job_scanner/` is summarised under [Job scanner and tracker](#job-scanner-and-tracker). Its personal files (`sources.yaml`, `companies.yaml`, `scoring_prompt.md`, `state/`, `digests/`, the installed `.plist` files) are local; the `.example` versions are tracked.

---

## Concepts

### Session Files

Every JD gets a session file, `output/<Folder>/session_<name>.md`. It records:

- JD analysis, requirement classification (direct / bridge / gap) and ATS keywords
- Company context and the reviewer persona used by the critique
- Role type and bundle selected, and the framing strategy
- The bullet plan: which achievements, in what order, at what length
- The cover letter plan
- Output files, critique summary, and a Status block saying what is done and what runs next

Every generation skill reads and updates it, and each re-reads it at the start of a phase, so work survives a `/clear` or a compaction. It is the single source of truth for an application. `/make-package` resumes from its Status.

### Experience Files

One file per position, built by `/setup-build-kb` from your extractions. Each achievement has:

- **Source** with citation (paper, write-up, repo or code)
- **Methods and tools** used
- **Quantitative results**
- **Pre-written bullet variants** (1-, 2- and 3-line)
- **Tags** for the role types it suits
- **Significance** context for cover letters

Resume bullets are sourced from these files and reframed for the target. They are never invented.

### Role-Type Bundles

One file per target audience, built by `/setup-build-kb` for the role types in your `config.md`. Each has five sections:

- **S1: Role Profile and Priority Matrix**: what this audience values, and which achievements rank where
- **S2: Summary Guide**: how to write the summary for this role type
- **S3: Achievement Reframing Map**: how to word each achievement for this audience
- **S4: Skills Guide**: which tools to bold, include, and group
- **S5: Cover Letter Guide**: opening hooks, paragraph templates, anti-patterns

### Provenance Flags

`config.md` holds a Provenance Flags table: each achievement's status (published, under review, internal, confidential) and your role in it. The skills check it before every output and will not:

- Claim unpublished work is published
- Claim internal tools are peer-reviewed
- Use full-ownership verbs ("built", "designed") for shared work
- Inflate author position or take credit for collaborators' results

A KB Corrections Log in the same file records errors you fixed, so they never come back. Both are checked again by the critique.

### The Critique System

`/critique` follows `resume_builder/reference/critique_framework.md`. The output has eight sections:

1. **Domain-Specialist Lens**: reviewer persona, JD vocabulary, gap ranking, competitive landscape
2. **Five-Perspective Read-Through**: ATS bot, recruiter (10 s), HR (30 s), hiring manager (2 min), technical reviewer (10 min)
3. **Eight-Dimension Scoring**: weighted, out of 100 (ATS 15, Summary 10, Skills 10, Bullets 25, Publications 10, Narrative 15, Visual 5, Credibility 10)
4. **Interview Likelihood**: per-reader estimates and a ceiling
5. **Tiered Improvements**: Tier 1 (worth 1 point or more), Tier 2, Tier 3 (cosmetic)
6. **Interview Bridge Points**: resume-to-interview talking points
7. **Cover Letter Critique**: six sub-checks, including package cohesion
8. **Post-Generation Verification**: mechanical and content checklists, including the AI fingerprint scan

Notes:

- **It reads the rendered PDF**, not just the HTML.
- **Publications are optional.** The dimension only applies when `config.md` FIXED Sections lists Publications. Otherwise it scores Projects / Open Source in their place, or is marked N/A and the other weights are rescaled.
- **Keyword-insertion guard.** A critique may suggest adding a keyword that names a duty you have not performed. The guard in `critique_framework.md` declines it.
- **Fresh context.** In `/make-package` both critiques run in a fresh-context subagent, so the reviewer has not seen the draft being written. Scores are reported as fresh-context.

---

## Workflows

All three start from the same place: `config.md` filled in and a knowledge base built. If you haven't done that, see Quick Start in [README.md](README.md): `/setup-extract` for each source, then `/setup-build-kb`.

### (a) One command: `/make-package`

```
/make-package JDs/acme_platform_engineer.txt
```

The argument can be a JD path, inline JD text, or an existing session file (to resume). Add `Send: email` or `Send: none` to pre-answer the send question.

It runs the existing skills in one session:

| # | Stage | Skill | Notes |
|---|-------|-------|-------|
| 1 | Resume | `/make-resume` | Research, framing, bullet plan, render |
| 2 | Critique, pass 1 | `/critique` | **Fresh-context subagent** |
| 3 | Edit | `/edit-resume` | Tier 1 findings only; skipped if none |
| 4 | Cover letter | `/make-cl` | |
| 5 | Critique, pass 2 | `/critique` | **Fresh-context subagent**, whole package |
| 6 | Edit | `/edit-resume` | Only if pass 2 found Tier 1 items |
| 7 | Interview prep | `/make-interview-prep` | |
| 8 | Finalization | `shared_ops.md` | Submission-named PDF copies |
| 9 | Send (optional) | `job_scanner/send_package.py` | Email to the candidate |

**Gates.** It keeps two human gates from `/make-resume`: (1) role type, bundle and framing, at the end of Phase 0; (2) the bullet plan, at the end of Phase 1. It also stops whenever a stage needs a decision from you: a provenance question, a factual gap, or a critique finding that needs a real-world action rather than an edit. Sending is never automatic: it asks once (Email or Don't send) unless `Send:` was given.

**Edits.** Tier 1 findings are applied; Tier 2 findings are written to the session file for you to weigh later. Keyword suggestions that fail the guard are declined and reported.

**Files written to `output/<Folder>/`:**

| File | What |
|------|------|
| `session_<name>.md` | Session file |
| `e2e_<name>_resume.html` / `.pdf` | Resume (`_cv` instead of `_resume` for a CV) |
| `e2e_<name>_cover_letter.html` / `.pdf` / `.txt` | Cover letter; `.txt` is for pasting into application forms |
| `critique_<name>.md` | Both critique passes |
| `interview_prep_<name>.html` | Interview-prep page, opened in a browser |
| `<Full Name> - CV - <Company>.pdf` | Copy of the resume/CV PDF; the file you attach |
| `<Full Name> - CL - <Company>.pdf` | Copy of the cover letter PDF; the file you attach |
| `send_<name>.html` / `.txt` | Email body and plain-text fallback (only if you send) |
| `replies/reply_*.md` | Your emailed replies, saved by `/revise-package` or the tracker |
| `send_<name>_rev<N>.html` / `.txt` | Revision emails (after `/revise-package`) |

The folder also holds a copy of the JD. Both resumes and CVs get a `- CV -` submission name.

**Report.** At the end it lists the files (submission PDFs first), both scores, Tier 1 items applied, Tier 2 items left open, gaps held open in the documents, and any acronyms dropped.

### (b) Step by step

Use this when you want to read each document before moving on, or to run one stage again.

```
/make-resume JDs/job.txt        → stops at: role + bundle + framing, bullet plan, finished resume
/make-cl output/<Folder>/session_<name>.md
/critique output/<Folder>/session_<name>.md
/edit-resume output/<Folder>/e2e_<name>_resume.html output/<Folder>/critique_<name>.md
/make-interview-prep output/<Folder>/session_<name>.md
```

- **Start a fresh session between steps** (`/clear`, then the next command). Each skill reads what it needs from the session file, and a critique run in the session that wrote the document reads its own work and scores it high. The skills print the next command to paste at each stop.
- After `/edit-resume`, run `/critique` again to re-score. The skill tells you when edits have made a critique stale.
- `/make-resume` also takes `Quick:` before the JD (take the bundle's HIGH-priority achievements, skip the two planning gates) and `Focus:`, `Emphasize:` or `Downplay:` after the path.
- `/make-cl` takes a session file; it reads the finished resume so the letter complements it.
- The skills stop at their own gates in this mode (resume done, cover letter done, critique done). `/make-package` drops these; the step-by-step skills keep them.

### (c) The email loop

Needs the Mail setup in `config.md` and the app password in Keychain; see [job_scanner/README.md](job_scanner/README.md).

1. **Package email.** At the end of `/make-package`, choose Email. It writes `send_<name>.html` and `.txt` from `send_email_template.html`: How to apply, Summary, Next steps, Critique (fresh-context scores, what was fixed, what is still your call, what is deliberately not claimed), and Interview prep. `send_package.py` sends it to the candidate (CC the sender) with the two submission PDFs, the plain-text letter and the interview-prep page attached. With `--company` and `--role` it also adds the package to the application tracker as "prepared".
2. **Reply.** Reply in your own words: "make the summary shorter", "I also used Kubernetes at X". Reply "applied" to record that you applied.
3. **`/revise-package output/<Folder>/session_<name>.md`.** It fetches new replies from Gmail, numbers each request and sorts it:

   | Kind | What happens |
   |------|-------------|
   | Wording or emphasis | Applied |
   | A fact about you (skill, date, duty, tool) | Applied, and recorded in `config.md` as confirmed by you |
   | Conflicts with Provenance Flags or the Corrections Log | Not applied; it asks |
   | A question | Answered in the reply email |
   | Unclear | Not applied; it asks, quoting the reply |

   Then it re-renders and reads the changed documents (resume stays 2 pages, letter stays 1 page), refreshes the submission PDFs, and emails the update **in the same thread**: What changed, Not changed (if any), Your questions (if any). Run it again after a second reply; it only picks up replies it hasn't fetched.
4. **If the tracker is installed,** it does step 3 for you. It spots a reply to a package email and runs `/revise-package` headless with `--unattended`, which never asks questions: anything that would need your decision goes in the email's Not changed section with the reason. If a render gate fails, nothing is sent and the tracker retries.

---

## Job scanner and tracker

`job_scanner/` is optional and macOS-only (launchd, Keychain). Setup, flags, cost and the sheet are in [job_scanner/README.md](job_scanner/README.md). Installing the scheduled jobs is in [job_scanner/launchd/README.md](job_scanner/launchd/README.md).

**What runs when** (default schedules; edit the plists to change them):

| Job | When | What it does |
|-----|------|--------------|
| Scanner | Sun and Wed 11:00 | `prefetch.py` → `score.py` → `digest.py` → `send_digest.py` |
| Tracker check | Every 5 minutes | Reads your mail over IMAP, records events, sends "got it" replies |
| Tracker digest | Daily 07:30 | A check, then the tracker digest email |

**What you get**

- **A ranked job digest by email.** Boards and company career pages are fetched in one pass, deduped against what you've seen, then each job description gets one headless Claude call that scores it against your role bundles. The digest lists Strong (85-100), Good (70-84) and Worth-a-look matches, plus a "Not scored" section and a cost summary. `/scan-jobs` runs the first three steps interactively; it never emails.
- **A tracker with no app to open.** You tell it things by email:
  - Reply "applied" to a package email, or "applied to #3" to a digest.
  - Forward a company's email to the `+jobs` alias.
  - Reply to the daily digest with news.

  Each message gets one Haiku call to work out what happened, and a threaded "got it" reply saying what was recorded. Replies that ask for edits to a package go through `/revise-package` (see (c) above).
- **A daily tracker digest.** What's new, an Upcoming interviews calendar (a four-week grid plus an agenda, from interview dates and times it picked up from your emails; interviews with no date are listed separately), then applications grouped by phase. After 30 days with no news, an application is marked Ghosted.
- **An optional Google Sheet mirror.** `sheet.py` pushes the applications and a timeline to a sheet through an Apps Script web app (`sheet_webapp.gs`). The digest links it when `config.md` has the Tracker sheet fields.

---

## Customization

### `config.md` (edit directly)

Start from `resume_builder/examples/example_config.md` (academic) or `example_config_industry.md` (industry). Every skill reads it.

| Section | What it controls |
|---------|-----------------|
| **Mail** | `Sender` (Gmail account that sends) and `Keychain service` (where its app password lives). Needed for emailing packages and for the scanner and tracker |
| **Tracker sheet** (optional) | `Sheet link` and `Sheet web app` (the Apps Script URL) for the Google Sheet mirror |
| **Personal Info** | Name, degree suffix, email, phone, location, links on every output |
| **Document Preferences** | Page counts, bullet line variants, skills layout |
| **Provenance Flags** | What you may claim for each achievement |
| **KB Corrections Log** | Errors that must never be re-introduced |
| **Role Types** | Target audiences and their bundles |
| **Role-Type Decision Tree** | How JD keywords map to a role type |
| **FIXED Sections** | Template sections that never change per JD (Education, Awards, Publications if you have them) |
| **Output Rules** | Package contents and page limits, and **Pipeline** |

**Pipeline** is `HTML` (the default) or `LaTeX (legacy)`. Every skill reads it and switches the steps marked "LaTeX pipeline only".

### HTML templates (default)

Edit `resume_template.html` and `coverletter_template.html` directly, or change what Claude copies for each job.

- **Accent colours:** `--accent` and `--accent-soft` at the top of the CSS. `/make-resume` tunes them to the target (the template comments suggest, for example, teal for medical and brown for biotech). Update the `.pub-tag` background to match, and match the cover letter's `--accent` to the resume.
- **Fonts, spacing, page size:** the CSS in the same file.
- **Sections:** each is a `<section>` with an `<h2>`. Delete or reorder them. Keep Selected Publications only if FIXED Sections lists Publications.
- **Add Projects or Open Source:** add a `<section>` after Experience and reuse the `.role` markup. It is a VARIABLE section: the skill writes it per JD.
- **FILL markers:** `FILL:` comments mark what Claude generates; content you've locked as FIXED is copied verbatim from config or your last resume.
- **Package email:** `send_email_template.html` has `{{…}}` placeholders and uses inline styles for email clients. Its accent follows the resume's.

### Legacy LaTeX templates

Used only when `Pipeline` is `LaTeX (legacy)`. You then need a LaTeX install (`pdflatex`), and the skills generate `.tex`, run `char_count.py` and compile.

- **Fonts, colours, spacing, page geometry:** the `.cls` files
- **Section order:** the `.tex` templates
- **FIXED content:** fill in education, awards, publications and header
- **Icons:** replace `GS.png` and `orcid.png`
- Character budgets in `resume_reference.md` are legacy-LaTeX figures. With HTML they are loose drafting intuition, not a gate.

### Knowledge base (built by skills, then editable)

| File | How to customize |
|------|-----------------|
| Experience files | Edit bullet text, add or remove achievements, adjust tags |
| Bundles | Change priority matrices, rewrite summary guides, add role types |
| Skills taxonomy | Add or remove skills, change groupings and bold rules |
| Publication metadata | Update citation counts, add publications (only if you list them) |

### Reference docs (advanced)

| File | What you'd change |
|------|-------------------|
| `resume_reference.md` | Page budgets, section specs |
| `cl_reference.md` | Cover letter paragraph templates, word count targets |
| `critical_rules.md` | Generation-time rules tables |
| `critique_framework.md` | Scoring weights, critique dimensions |
| `shared_ops.md` | Session workflow, file derivation, finalization |
| `support/ai_fingerprint_rules.md` | Banned words and structural tells |

### Skill prompts (advanced)

Each skill is a Markdown file at `.claude/skills/<name>/SKILL.md`. You can add or remove stops, change the number of web searches in Phase 0, change bullets per position, change the critique weights, or add a skill for your workflow. `make-package` is only sequencing: to change a stage, edit that stage's skill.

---

## Key Design Decisions

- **Accuracy > Relevance > Impact > ATS > Brevity.** The priority order for every generation decision.
- **Render and read, not predict.** Claude fills an HTML template, renders it with headless Chrome, and reads the PDF. The gate is what the page looks like: page count, orphaned headings, wrapped dates, how full the last page is. The earlier LaTeX pipeline predicted the layout from character counts, because it couldn't see the result. Counting characters against a prediction is a proxy for the page. Looking at the page is the check. Fixing a fit problem is an edit to the HTML and a re-render.
- **FLIPPED position format.** The bold line under each position title is a theme chosen for the JD, not a generic description. This is the strongest tailoring lever.
- **Structured provenance.** Every achievement is tracked from source through extraction and experience file to resume bullet.
- **Session files as state.** All decisions for a JD live in one file, so skills can recover from interruptions and a package can be resumed.
- **Anti-fabrication by design.** Provenance flags, verb discipline and a corrections log guard against overclaiming, including when a critique suggests a keyword for something you haven't done.
- **AI fingerprint avoidance.** A rules file (banned words, structural tells, a post-generation checklist) is loaded by the generation and critique skills.
- **One session for the package, fresh context for critiques.** A critique written in the session that wrote the document reads its own work and scores it high. `/make-package` keeps everything else in one session, because the resume, letter and edits all depend on your gate answers, and sends only the two critiques to fresh subagents that are given file paths, not opinions. The result is fewer commands and an independent score.
- **Config-driven identity.** Name, contact details, role types, provenance and output rules all live in `config.md` and the local KB. The skills and templates hold none of it, so one kit serves several candidates, each with their own clone, and the repo stays generic.
- **An email-driven tracker.** Tracking applications means keeping a spreadsheet up to date, and nobody does. The tracker reads the mail you already send and receive, files it, and replies to say what it recorded, so correcting it is a reply. There is no app to open. The optional sheet is a read-only mirror.

---

## FAQ

**Q: Do I need LaTeX?**
No. By default Claude generates HTML and renders it to PDF with Chrome. Set Pipeline to `LaTeX (legacy)` in `config.md` only if you want the old templates; you then need `pdflatex`.

**Q: I'm not an academic. Does this work for me?**
Yes. Sources can be a CV, a LinkedIn export, project write-ups, design docs or code, not only papers. `/setup-extract` asks what you did on each. For an industry profile, start from `resume_builder/examples/example_config_industry.md`: Publications are optional (they appear only if FIXED Sections lists them), and the critique scores Projects / Open Source in their place, or marks the dimension N/A.

**Q: What leaves my machine?**
- **The Claude Code conversation.** Your KB, config and drafts are read into Claude Code sessions and sent to Anthropic. `/make-resume` and `/critique` also run web searches on the company.
- **The job scanner's fetches** of public job pages (boards and company career pages). The scanner's headless Claude calls send each job description and your scoring prompt to Claude, and the tracker's send the text of your emails.
- **Gmail SMTP and IMAP**, for the mail features: sending digests and packages, and the tracker reading your mail.
- **The Google Sheet**, if you configure it: your application list goes to the Apps Script web app.

Your config, KB, outputs and scanner state are gitignored and stay on disk. There is no kit server.

**Q: Does it run on Windows or Linux?**
The resume pipeline needs Claude Code and Chrome or Chromium. `render_pdf.sh` is a bash script and looks for Chrome at its macOS path, then `google-chrome` or `chromium` on the PATH, so Linux works. Windows is untested; WSL is the likeliest route. `job_scanner/` is macOS-only: it uses launchd and the Keychain.

**Q: How many sources should I extract?**
Everything where your role is clear and the work is relevant: papers where you are first or co-first author plus key contributions, and the projects and jobs you'd put on a resume. Quality beats quantity: five well-extracted sources beat twenty shallow ones.

**Q: What if I don't have a Google Scholar or ORCID?**
Leave those fields out of `config.md` and delete the links from the template header. The framework adapts to what you have.

**Q: How do I add a new project or paper later?**
Run `/setup-extract` on it, then `/setup-build-kb` (or one component, e.g. `/setup-build-kb experience`) to update the experience files and bundles. Existing session files are not affected.

**Q: Can I use my own resume layout?**
Yes. Edit `resume_template.html` or replace it with your own. Keep the `FILL:` markers so the skills know what to generate, and keep the CSS compatible with `render_pdf.sh`: it prints through Chrome, so ordinary print CSS applies.

**Q: Can multiple people use the same kit?**
The framework is shared; the content is per person. Each person needs their own clone, with their own `config.md`, knowledge base and `CLAUDE.md`. For the scanner, give each clone its own launchd label prefix and schedule; see [job_scanner/launchd/README.md](job_scanner/launchd/README.md).

**Q: What Claude model should I use?**
The skills are written for Claude's most capable models. Less capable models may skip steps or write weaker output. The scanner is fixed: Sonnet for scoring, Haiku for the tracker's email classification.
