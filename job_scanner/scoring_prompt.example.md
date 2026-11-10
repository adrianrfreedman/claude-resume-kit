# Job Fit Scoring Prompt

> Copy to `scoring_prompt.md` and replace every `<placeholder>`. This prompt is read once per scan and prepended to every per-JD scoring call. The profile + bundles section is stable across calls and benefits from prompt caching.

---

## Candidate Profile (cached prefix)

**Name:** <Full Name>
**Current role:** <Title> at <Employer>, <City>.
**Location:** <City, Country>.
**Languages:** <languages and levels>.

**Background:**
- <years and core discipline; strongest skills>
- <current role in one or two lines, with scale or numbers>
- <earlier roles, one line each>
- <education>
- <habit or theme that defines the candidate's work>

**Looking for:**
- <target seniority and role types>
- <target employer types and domains>
- <preferred locations; what else is acceptable>
- Not interested in: <role types to avoid>.

---

## Target Role Bundles

### Bundle 1 — <Name> (TIER 1, primary)
Target employers: <employer types>.
Example roles: <role titles>.
Strengths to surface: <evidence from the profile that matches this bundle>.

### Bundle 2 — <Name> (TIER 2)
Target employers: <employer types>.
Example roles: <role titles>.
Strengths to surface: <evidence>.
**Differentiator vs Bundle 1:** <how to choose between the two when a role fits both>.

<Add or remove bundles as needed; keep `best_bundle` in the output format in sync.>

---

## Location Tier Rules

Compute `location_tier` from the JD's stated location and remote policy:

| Tier | Definition |
|------|------------|
| **1** | <home city> |
| **2** | <nearby cities; remote with acceptable timezone overlap> |
| **3** | <far but acceptable locations> |
| **0** | <unacceptable: e.g. on-site in another country> → **exclude** (set `score = 0`) |

**Remote-flexibility expectation scales with distance from <home city>:**
- Tier 1 / 2: full in-office is fine.
- Tier 3: at least 2-3 days WFH, or a shuttle. If the JD demands full in-office at tier 3, drop the score by 15-25 points and add a `red_flag`.

---

## Seniority Floor

Floor is **<level>** and up: <list of acceptable titles>.

Roles below the floor → **cap the score at 30** and add `below_seniority_floor`. Untitled postings: decide from the years of experience and scope in the JD.

---

## Hard Drops (set `score = 0`, name the reason in `red_flags`)

- <role type> (`<flag_name>`).
- <role type> (`<flag_name>`).
- <language, clearance or authorisation requirements the candidate cannot meet> (`<flag_name>`).

---

## Scoring Rubric (0-100)

Components, weights, and how to compute:

| Component | Weight | Notes |
|-----------|--------|-------|
| **Role fit vs bundles** | 40 | Match to a bundle per the example roles and strengths above. Surface `best_bundle`. |
| **Seniority match** | 20 | Full at or above the floor and target level. Below the floor = capped at 30 overall. |
| **Skills and domain alignment** | 15 | Core skills and domains = full. Primary skills the candidate lacks (see gaps) = low. |
| **Location** | 15 | Tier 1 = full, tier 2 = ~80%, tier 3 = ~40%, tier 0 = 0. |
| **Flexibility signal** | 10 | "Hybrid", "flexible", "remote-friendly", explicit WFH days = boost. Full on-site at tier 3 = penalty. |

**Cross-check JD requirements against the candidate's actual profile.**

Listing cards often hide the real requirements. Before locking a score ≥70, read the "Requirements" / "Must have" / "Qualifications" sections of the full JD and compare them to what the candidate actually has. Identify *gaps*: required things they do not have.

The candidate has:
- <skills, tools, domains, credentials>

The candidate does NOT have:
- <known gaps; be honest>

**Penalty logic — cumulative, not rigid:**

For each "must-have" requirement in the JD that the candidate clearly doesn't satisfy, count it as one *gap*. Apply this scale to the otherwise-computed score:

- **0 gaps** — score unchanged.
- **1 gap** — small penalty (3-8 points); note the gap in `red_flags`.
- **2 gaps** — meaningful penalty (15-25 points); the role drops a bucket.
- **3+ gaps** — heavy penalty (30+ points); usually drops below 50.

**Special cases that override the cumulative scale:**

- <e.g. a primary skill or language the role requires and the candidate lacks: penalty and flag name>.
- <e.g. relocation required: `score = 0`, flag name>.

**When uncertain** (the JD body wasn't fully fetched, or requirements are vague): do not assume the role is clear. Add `verify <skill/seniority/location>` to `red_flags` and apply a small uncertainty penalty (3-5 points). The candidate would rather see flagged roles than miss them.

**Score brackets:**
- **85-100 Strong:** Clear bundle match, senior enough, good location, no hidden disqualifiers.
- **70-84 Good:** Solid fit, possibly weaker on one dimension.
- **50-69 Worth-a-look:** Adjacent fit or compensating strengths.
- **<50 Drop.**

---

## Output Format (strict JSON, no prose)

```json
{
  "score": 0-100,
  "location_tier": 0-3,
  "remote_flexibility": "low | med | high | unknown",
  "best_bundle": "bundle_1 | bundle_2 | neither",
  "rationale": "≤60 words on why this score",
  "red_flags": ["array of short strings, may be empty"]
}
```

---

## Per-JD Input (variable, appended at runtime)

```
COMPANY: {company}
TITLE: {title}
LOCATION: {location}
REMOTE_POLICY: {remote_policy or "unknown"}
POSTED: {posted_date or "unknown"}
URL: {url}

DESCRIPTION:
{description}
```
