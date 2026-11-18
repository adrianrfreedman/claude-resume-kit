# claude-resume-kit

**Tailored resumes that never claim more than you did.**

Most AI resume tools do one trick: paste your resume, paste a job ad, get back a rewrite. The rewrite sounds great, and it's quietly wrong. "Contributed to" becomes "led". The paper under review becomes "published". The simulations you ran become the whole project.

This kit works the other way round. You teach Claude your career once: your papers, code, reports, old CVs. It asks what *you* actually did on each. After that, every application is one command. It picks the evidence that fits the job, frames it for that reader, checks every claim against the source, and hands you a resume, a cover letter and an interview-prep page. Each one has been critiqued by a fresh pair of eyes before you see it.

> Built on [claude-resume-kit](https://github.com/ARPeeketi/claude-resume-kit) by Akhil Reddy Peeketi. See [Credits](#credits) for what this fork adds.

---

## One job, one command

```
/make-package JDs/acme_platform_engineer.txt
```

When it finishes, `output/Acme/` holds:

- **The resume**, written for this job and rendered to PDF
- **The cover letter**, hooked to something specific about the company
- **An interview-prep page**: about twenty questions drawn from the job ad and your gaps, talking points for each, and what to ask them
- **Two rounds of critique** by fresh-context reviewers, with the fixes already applied
- **A session log** of every framing decision, so you can see why each bullet is there
- **Submission copies** named `<Full Name> - CV - Acme.pdf` and `<Full Name> - CL - Acme.pdf`

It stops at each decision that matters, such as the bullet plan and the framing, and waits for your OK. If you like, it emails the whole package to the candidate. Reply with changes in plain English and `/revise-package` applies them and sends the new version back in the same thread.

---

## Why it's different

**It knows your career, not just your last resume.** Every application draws on a knowledge base built from your source material, not a pasted document that gets "improved" each time.

**It won't inflate.** Every achievement carries a provenance flag (published, under review, internal, confidential). Verb rules stop "helped with" turning into "built". A corrections log makes sure a mistake you fixed once never comes back.

**It doesn't read like AI.** Banned-word lists, structural tells and a 12-point scan after every draft keep the "spearheaded a robust, cutting-edge synergy" out.

**It gets a second opinion.** Five reader personas, from the ATS bot to the technical reviewer, score the resume on eight dimensions. They run in a fresh context, so they never see how the draft was made.

**Your data stays yours.** Your config, knowledge base and outputs are gitignored and stay on your machine. Nothing leaves it except the Claude Code conversation.

---

## And it doesn't stop at the resume

The optional `job_scanner/` (macOS) turns the kit into a job-search assistant that runs in the background:

- **Twice a week** it scans job boards and company career pages, scores each posting against your profile, and emails you a ranked shortlist.
- **Reply "applied to #3"**, or forward a recruiter's email, and the tracker records it. You get a "got it" back within minutes.
- **Every morning** a digest shows where each application stands, what's gone quiet, and your interviews coming up.
- **A Google Sheet** mirrors the tracker, one row per role with its current phase. Share it with whoever's cheering you on.

Setup is in [`job_scanner/README.md`](job_scanner/README.md).

---

## Try it in five minutes

The repo ships a complete example knowledge base for a fictional researcher, Dr. Jordan Chen, plus a matching job ad. Copy it into place in a throwaway clone:

```bash
git clone https://github.com/adrianrfreedman/claude-resume-kit.git resume-kit-demo
cd resume-kit-demo
cp resume_builder/examples/example_config.md config.md
cp CLAUDE.example.md CLAUDE.md
cp resume_builder/examples/experience/*.md resume_builder/experience/
cp resume_builder/examples/bundles/*.md resume_builder/bundles/
claude
```

Then, inside Claude Code:

```
/make-resume JDs/example_jd.txt
```

It reads the job ad, proposes which bullets to use, waits for your OK, then writes the resume and renders it to PDF under `output/<Folder>/`. When you're done, delete the demo clone. Your real setup starts from a fresh one.

Want to see the output first? Here's what it produced for Dr. Chen applying to a faculty post: [resume](resume_builder/examples/example_resume.pdf), [cover letter](resume_builder/examples/example_cover_letter.pdf), and the [session log](resume_builder/examples/example_session_file.md) behind them.

---

## Not an academic?

Good: it works the same for industry roles. Only the inputs and the config change.

| | Academic | Industry |
|---|---|---|
| Inputs | Papers, reports | CV, LinkedIn export, one write-up per job or project, repos |
| Role Types | Academic, Industry R&D | e.g. Senior Backend Engineer, Platform Engineer, Engineering Lead |
| Role-Type Decision Tree | Maps JD terms like faculty, NSF, biotech | Maps JD terms like Kubernetes, SRE, tech lead, Series A |
| FIXED Sections | Education, Publications, Honors, header | Education + header only |
| Provenance Flags | Paper status (published, under review) | Confidential client names, unshipped work, NDA metrics |
| Template headings | Experience, Selected Publications | Experience, optional Projects / Open Source |

Start from `resume_builder/examples/example_config_industry.md`.

---

## Set it up for real

**You'll need:** [Claude Code](https://docs.anthropic.com/en/docs/claude-code), installed and logged in. You'll also need Google Chrome or Chromium, which renders the HTML templates to PDF. `pdfinfo` from poppler is optional and gives exact page counts. The LaTeX templates are still included if you prefer them. The job scanner additionally needs macOS, Python 3 with PyYAML, and a Gmail app password.

### 1. Clone and configure

```bash
git clone https://github.com/adrianrfreedman/claude-resume-kit.git
cd claude-resume-kit
cp resume_builder/examples/example_config.md config.md   # or example_config_industry.md
cp CLAUDE.example.md CLAUDE.md
```

Fill in `config.md`:
- your details and page preferences
- the role types you're targeting
- provenance flags: what's published, under review, internal or confidential
- the FIXED sections, which are copied verbatim every time (education, and publications if you have them)

`config.md`, `CLAUDE.md`, and everything you add under `knowledge_base/`, `resume_builder/{experience,bundles,support}/`, `JDs/` and `output/` are gitignored.

### 2. Feed it your career

Put papers (PDF or `.tex`) in `knowledge_base/papers/`. Put everything else in `knowledge_base/notes/`: CV, LinkedIn export, project write-ups, notes on your repos. Then, one file at a time:

```
/setup-extract knowledge_base/papers/my_paper.pdf
```

Claude reads it, asks what exactly *you* did (and the publication status, for a paper), and writes a structured extraction to `knowledge_base/extractions/`. Allow about ten minutes per source. This is the step that makes everything after it honest.

### 3. Build the knowledge base

```
/setup-build-kb
```

It turns the extractions into three things:
- one experience file per position
- a bundle per target role type
- supporting files, such as your skills taxonomy

### 4. Apply

Save the job ad in `JDs/` and run the whole package:

```
/make-package JDs/target_job.txt
```

Or drive each step yourself. Here `<session>` is `output/<Folder>/session_<name>.md`, and each step works best in a fresh Claude Code session:

```
/make-resume JDs/target_job.txt
/critique <session>
/edit-resume <resume file> <critique file>
/make-cl <session>
/make-interview-prep <session>
```

### 5. Optional: put the search on autopilot

Set up the job scanner and tracker with [`job_scanner/README.md`](job_scanner/README.md), then install the scheduled jobs with [`job_scanner/launchd/README.md`](job_scanner/launchd/README.md).

---

## How it fits together

```
papers · CVs · repos ──/setup-extract──▶ extractions ──/setup-build-kb──▶ knowledge base
                                                                               │
job ad ──/make-package─────────────────────────────────────────────────────────┤
           ├─ /make-resume           resume (HTML → PDF)                        │
           ├─ /critique → fixes      fresh-context review                       │
           ├─ /make-cl               cover letter                               │
           ├─ /critique → fixes      second pass                                │
           └─ /make-interview-prep   prep page                                  │
                    │
                    ▼
             email to the candidate ── reply with changes ──/revise-package──▶ new version, same thread
```

| Skill | What it does | Input | Output |
|-------|--------------|-------|--------|
| `/setup-extract` | Pull structured facts from one source | Paper, CV, write-up or code | `knowledge_base/extractions/*.md` |
| `/setup-build-kb` | Turn extractions into the knowledge base | All extractions | `resume_builder/{experience,bundles,support}/` |
| `/make-package` | Everything below, critiqued twice, optionally emailed | Job ad | `output/<Folder>/` |
| `/make-resume` | Tailored resume or CV | Job ad | Resume + session file |
| `/make-cl` | Matching cover letter | Session file | Cover letter |
| `/critique` | Independent scored review | Session file | `critique_*.md` |
| `/edit-resume` | Apply feedback to resume or letter | Session + feedback | Updated files |
| `/make-interview-prep` | Questions, stories, what to ask | Session file | `interview_prep_*.html` |
| `/revise-package` | Apply edits emailed back, reply in thread | The reply | Updated package |
| `/scan-jobs` | Run the job scanner now (no email) | `job_scanner/` config | Ranked digest |

For architecture, customisation, the critique system and the FAQ, see **[DOCS.md](DOCS.md)**.

---

## Credits

This is a fork of [claude-resume-kit](https://github.com/ARPeeketi/claude-resume-kit) by Akhil Reddy Peeketi (MIT). The extraction, knowledge-base, resume, cover-letter and critique skills are his work. This fork adds:

- **HTML → PDF output** through headless Chrome (`resume_builder/templates/resume_template.html`, `resume_builder/helpers/render_pdf.sh`). The original LaTeX templates are kept.
- **`/make-package`**, **`/make-interview-prep`** and **`/revise-package`**: the one-command package, the prep page, and edits by email.
- **Non-academic profiles**, with an industry example config.
- **`job_scanner/`**: the scheduled job scanner (Israeli and remote boards plus company career pages), the email-driven application tracker, and its Google Sheet mirror.

---

## Contributing

Issues and PRs welcome:
- Keep examples in the fictional Dr. Jordan Chen persona, or the industry example's Sam Rivera.
- Reference docs should stay domain-agnostic.
- Test skill changes against the example data before submitting.

## License

MIT. See [LICENSE](LICENSE).
