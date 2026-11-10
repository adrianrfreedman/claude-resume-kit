# claude-resume-kit

Most AI resume tools work the same way: paste resume + paste JD, get a rewrite. They don't know which of your papers is published vs. under review. They don't know you only ran the simulations, not the experiments. They'll upgrade "contributed to" into "developed" without blinking.

This is different. You extract your papers, codebases, and reports once — the system asks structured questions about each one. After that, every new application is just pointing it at a JD. It picks the right achievements, frames them for the audience, enforces accuracy, and generates LaTeX you compile locally.

Built for researchers and engineers with lots of source material (papers, code, reports) who apply to many positions across different employer types.

## About this fork

This is a fork of [claude-resume-kit](https://github.com/ARPeeketi/claude-resume-kit) by Akhil Reddy Peeketi (MIT). The extraction, knowledge-base, resume, cover-letter and critique skills are his work. This fork adds:

- **HTML → PDF output** via headless Chrome (`resume_builder/templates/resume_template.html`, `resume_builder/helpers/render_pdf.sh`). The LaTeX pipeline described below is kept as legacy.
- **`/make-package`**: resume, cover letter and interview prep in one run, with two fresh-context critique passes, optionally emailed to the candidate.
- **`/make-interview-prep`** and **`/revise-package`** (applies the edits the candidate emails back and replies in the same thread).
- **`job_scanner/`**: a scheduled job scanner (Israeli and remote boards plus company career pages, scored by Claude) and an email-driven application tracker. See [`job_scanner/README.md`](job_scanner/README.md).

---

## What makes this different

**Knowledge base, not a rewriter.** You extract once. Every application draws from verified source material — not a pasted resume that gets "improved."

**Anti-fabrication by design.** Provenance flags on every achievement (published / under review / internal). Verb discipline rules prevent overclaiming. A corrections log ensures fixed errors don't reappear.

**AI fingerprint avoidance.** Banned-word lists, structural anti-patterns, and a 12-item post-generation scan so output reads as human-written.

**Multi-perspective critique.** Five reader personas (ATS bot through technical reviewer) score your resume across 8 dimensions in a fresh context window.

**LaTeX output, locally compiled.** No data leaves your machine beyond the Claude Code conversation.

---

## Example Output

Here's what the system generates for the included fictional researcher (Dr. Jordan Chen, computational biologist) applying to a tenure-track faculty position:

- [Example Resume (PDF)](resume_builder/examples/example_resume.pdf) — 2-page resume with JD-tailored bullets, skills, and publications
- [Example Cover Letter (PDF)](resume_builder/examples/example_cover_letter.pdf) — 1-page academic cover letter with specific hooks
- [Example Session File](resume_builder/examples/example_session_file.md) — the decision log that produced this output
- [Source .tex files](resume_builder/examples/output/) — the LaTeX source Claude generated

All example data is in `resume_builder/examples/` — extraction, experience file, bundle, config, and session file.

---

## What you actually do

**One-time setup (~10 min per paper):**
1. Drop your papers/reports into `knowledge_base/papers/`
2. Run `/setup-extract` on each — Claude reads it and asks you questions about your contributions and publication status
3. Run `/setup-build-kb` — synthesizes everything into your knowledge base

**Per application (~15-20 min):**
1. Drop the JD into `JDs/`
2. Run `/make-resume JDs/target_job.txt` — approve the bullet plan, get a `.tex` file
3. Run `/make-cl` for a cover letter
4. Run `/critique` for a scored review with specific fixes

Each step uses a **separate Claude Code session** for best quality (fresh context = less bias).

---

## Prerequisites

- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** CLI installed and authenticated
- **Google Chrome or Chromium**: resumes and letters are HTML rendered to PDF with headless Chrome (`resume_builder/helpers/render_pdf.sh`). `pdfinfo` (poppler) is optional, for exact page counts.
- **Your source material**: papers, code, reports or project write-ups to extract from
- For the optional job scanner and tracker: **macOS** (launchd, Keychain), Python 3 with PyYAML, and a Gmail account with an app password

---

## Try it first (5 minutes)

The repo ships a complete example knowledge base for a fictional researcher, Dr. Jordan Chen, plus a matching job description. Copy it into place in a throwaway clone and run the resume pipeline:

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

It analyses the JD, plans which bullets to use, asks you to confirm the plan, then writes the resume as HTML and renders it to PDF under `output/<Folder>/`. Delete the demo clone when you're done; your real setup starts from a fresh one.

---

## Full Setup

### 1. Clone and configure

```bash
git clone https://github.com/adrianrfreedman/claude-resume-kit.git
cd claude-resume-kit
cp resume_builder/examples/example_config.md config.md
cp CLAUDE.example.md CLAUDE.md
```

Edit `config.md`: Personal Info, Document Preferences, Provenance Flags (what is published, under review or internal), Role Types and the FIXED Sections (education, awards, publications). `resume_builder/examples/example_config.md` is a filled-in example. `config.md`, `CLAUDE.md` and everything you add under `knowledge_base/`, `resume_builder/{experience,bundles,support}/`, `JDs/` and `output/` are gitignored, so your data stays local.

### 2. Extract your source material

Put papers (PDF or `.tex`) in `knowledge_base/papers/` and anything else (code write-ups, reports, notes) in `knowledge_base/notes/`, then, one file at a time:

```
/setup-extract knowledge_base/papers/my_paper.pdf
```

Claude reads the file, asks what exactly you did on it, and writes a structured extraction to `knowledge_base/extractions/`.

### 3. Build your knowledge base

```
/setup-build-kb
```

This turns the extractions into one experience file per position, a bundle per target role type, and support files (skills taxonomy and the like).

### 4. Generate for a job

Save the job description to `JDs/`, then run the whole package in one session:

```
/make-package JDs/target_job.txt
```

It writes the resume, has a fresh-context subagent critique it and applies the fixes, writes the cover letter, critiques again (fixing anything critical), then builds an interview-prep page. It stops to ask you at the same gates the individual skills do. Everything lands in `output/<Folder>/`, including submission copies named `<Full Name> - CV - <Company>.pdf` and `<Full Name> - CL - <Company>.pdf`.

To run the steps one at a time instead (`<session>` is `output/<Folder>/session_<name>.md`):

```
/make-resume JDs/target_job.txt
/critique <session>
/edit-resume <resume file> <critique file>
/make-cl <session>
/make-interview-prep <session>
```

### 5. Optional: job scanner and application tracker (macOS)

`job_scanner/` scans job boards and company career pages twice a week, scores each posting against your bundles with Claude and emails a ranked digest. The tracker reads your replies and forwarded company emails to keep a list of your applications, and sends a daily summary. `/make-package` can also email the finished package. Setup is in [`job_scanner/README.md`](job_scanner/README.md); the scheduled jobs are installed with [`job_scanner/launchd/README.md`](job_scanner/launchd/README.md).

---

## How It Works

```
Your Papers --> /setup-extract --> Extractions --> /setup-build-kb --> Knowledge Base
                                                                          |
Job Description --> /make-resume --> Tailored Resume/CV (.tex)            |
                        |              v                                  |
                   /make-cl --> Cover Letter (.tex)                       |
                        |              v                                  |
                   /critique --> 8-Part Score + AI Scan + Fixes           |
                        |              v                                  |
                   /edit-resume --> Refined Package                       |
```

| Skill | Purpose | Input | Output |
|-------|---------|-------|--------|
| `/setup-extract` | Extract structured data from a paper | Paper path | `knowledge_base/extractions/*.md` |
| `/setup-build-kb` | Build KB from extractions | All extractions | `resume_builder/{experience,bundles,support}/` |
| `/make-resume` | Generate tailored resume or CV | JD path | `output/<Folder>/e2e_*.tex` + session file |
| `/make-cl` | Generate matching cover letter | Session file | `output/<Folder>/*_cover_letter.tex` |
| `/edit-resume` | Edit resume/CV/CL from feedback | Session + feedback | Updated `.tex` files |
| `/critique` | Independent quality review | Session file | `output/<Folder>/critique_*.md` |

---

## Documentation

For architecture details, customization tables, the full critique system breakdown, key design decisions, and FAQ, see **[DOCS.md](DOCS.md)**.

---

## Contributing

Issues and PRs welcome. When contributing:
- Example files use the fictional Dr. Jordan Chen — keep examples in that persona
- Reference docs should stay domain-agnostic
- Test skill changes against the example data before submitting

---

## License

MIT — see [LICENSE](LICENSE).
