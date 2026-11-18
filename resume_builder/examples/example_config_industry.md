# Configuration (industry example)

> Fictional backend/platform engineer. Copy to `config.md` and edit. Every skill reads this file.

---

## Mail (job scanner and tracker)

- **Sender:** you@example.com
- **Keychain service:** job-scanner-gmail

---

## Tracker sheet (optional)

- **Sheet link:** https://docs.google.com/spreadsheets/d/<sheet-id>
- **Sheet web app:** https://script.google.com/macros/s/<deployment-id>/exec

---

## Personal Info

- **Name:** Sam Rivera
- **Degree suffix:**
- **Email:** sam.rivera@example.com
- **Phone:** +1 5550100123
- **Location:** Austin, TX 78701
- **LinkedIn:** linkedin.com/in/samrivera-example
- **GitHub:** github.com/samrivera-example
- **Website:**

---

## Document Preferences

- **Resume pages:** 2
- **Resume bullet variant:** 2L (all variable bullets are 2-line)
- **Skills config (resume):** 4-3-2-2-2 (13 lines, 5 groups)
- **Immigration line:** No

---

## Provenance Flags

Track what you can and cannot claim. Skills check this table before every output.

| Item | Status | Correct Framing |
|------|--------|----------------|
| Order-routing migration for a Fortune 500 retailer | confidential client | "a Fortune 500 retailer" -- never name the client |
| Internal deploy-preview tool | built, never shipped to production | "prototyped" -- never say "launched" or "in production" |
| Platform cost savings | revenue and spend figures under NDA | ranges only ("six figures annually") -- never exact numbers |

---

## KB Corrections Log

Verified errors to never re-introduce. Add entries as you catch mistakes.

| Correction | Details |
|-----------|---------|
| Kubernetes migration credit | Led with two other engineers. Use "Led migration with a team of 3", never "Led migration" alone. |
| Deploy pipeline speedup | 22 min to 9 min (not 22 to 6). Confirmed in the CI dashboard export. |

---

## Role Types

Define the role types you're targeting. Each gets a bundle during setup.

| Role Name | Target Employers | Tier | Bundle File |
|-----------|-----------------|------|-------------|
| Senior Backend Engineer | Product companies, Series A to late-stage startups | 1 | bundle_senior_backend.md |
| Platform / Infrastructure Engineer | Cloud-native companies, SRE and platform teams | 1 | bundle_platform_infra.md |
| Engineering Lead | Growth-stage startups, teams of 5-15 | 2 | bundle_engineering_lead.md |

**Tier guide:** 1 = strongest evidence, full portfolio | 2 = strong with targeted emphasis | 3 = viable with careful framing

---

## Role-Type Decision Tree

Customize this to map JD keywords to your role types.

| If JD mentions... | Primary profile | Secondary (hybrid) |
|-------------------|----------------|-------------------|
| Python, Go, microservices, REST, PostgreSQL, backend | Senior Backend Engineer | Platform / Infrastructure Engineer |
| Kubernetes, Terraform, AWS, SRE, observability, CI/CD | Platform / Infrastructure Engineer | Senior Backend Engineer |
| tech lead, engineering manager, mentoring, hiring, roadmap | Engineering Lead | Senior Backend Engineer |
| seed, Series A, founding engineer, 0-to-1 | Engineering Lead | Senior Backend Engineer |
| LLM, RAG, ML platform, model serving | Senior Backend Engineer | Platform / Infrastructure Engineer |

---

## FIXED Sections

List template sections that should NEVER be modified during generation.
These are copied verbatim from your template every time.

- Education
- Header block (name, contact, links)

---

## Output Rules

- **Email in all outputs:** sam.rivera@example.com
- **Resume package:** 2 pages + 1-page cover letter
- **Pipeline:** HTML
  - `HTML` (default): documents are HTML rendered to PDF with headless Chrome (`render_pdf.sh`); the gate is reading the PDF.
  - `LaTeX (legacy)`: `.tex` templates, `char_count.py` and `pdflatex`; needs a LaTeX install.
