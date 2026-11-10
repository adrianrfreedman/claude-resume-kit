#!/usr/bin/env python3
"""Parallel prefetch for /scan-jobs.

Fetches every board query and company page, parses LinkedIn, AllJobs and
Drushim cards into candidates, dedupes against state/seen.jsonl, fetches JD
bodies for unseen candidates only, and writes state/candidates_<YYYY-MM-DD>.json.
raw_pages (capped at 3000 chars) is kept only for a board query page where no
card parsed.

Usage:
    python3 job_scanner/prefetch.py [--out PATH] [--deadline SEC]
        [--source ID] [--no-dedupe] [--max N]

Optional settings.title_exclude (list of case-insensitive regexes in
sources.yaml): unseen candidates whose title matches get triage
"title-exclude", no body fetch, and do not count toward --max.

Exit 0 even when sources fail; exit 1 only if the output cannot be written.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date, datetime
from itertools import zip_longest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dedupe import h, load_seen  # noqa: E402

HERE = Path(__file__).resolve().parent
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
WORKERS = 8
REQ_TIMEOUT = 20
RENDER_TIMEOUT = 60
PER_BOARD_CAP = 8
BODY_CAP = 4000
PAGE_CAP = 6000
RAW_PAGE_CAP = 3000
ALLJOBS_BASE = "https://www.alljobs.co.il"
DRUSHIM_BASE = "https://www.drushim.co.il"
LI_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LI_POSTING = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/"

LI_SEM = threading.Semaphore(2)
RENDER_SEM = threading.Semaphore(3)
LI_RETRY_SLEEP = 3.0


# --------------------------------------------------------------------------
# HTTP + text helpers
# --------------------------------------------------------------------------

def get(url, timeout=REQ_TIMEOUT):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def li_get(url):
    """LinkedIn GET: max 2 concurrent; one retry after a 429."""
    with LI_SEM:
        try:
            return get(url)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
        time.sleep(LI_RETRY_SLEEP)
        return get(url)


def status_of(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return "http %d" % exc.code
    if isinstance(exc, (socket.timeout, TimeoutError, subprocess.TimeoutExpired)):
        return "timeout"
    if isinstance(exc, urllib.error.URLError):
        r = exc.reason
        if isinstance(r, (socket.timeout, TimeoutError)) or "timed out" in str(r):
            return "timeout"
        return ("error: %s" % r)[:70]
    return ("error: %s" % type(exc).__name__)[:70]


def clean(s, cap=200):
    return re.sub(r"\s+", " ", html.unescape(str(s or ""))).strip()[:cap]


def strip_html(s, cap=PAGE_CAP):
    s = re.sub(r"<!--.*?-->", " ", s or "", flags=re.S)
    s = re.sub(r"<(script|style|noscript)\b.*?</\1\s*>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()[:cap]


class Deadline:
    def __init__(self, sec):
        self.end = time.monotonic() + sec

    def remaining(self):
        return max(0.0, self.end - time.monotonic())

    def expired(self):
        return self.remaining() <= 0


# --------------------------------------------------------------------------
# Parsers
# --------------------------------------------------------------------------

def cand(company, title, location, url, posted=None, source="", hint=None, **extra):
    c = {
        "company": clean(company), "title": clean(title),
        "location": clean(location) or "unknown", "url": (url or "").strip(),
        "posted": posted or None, "source": source, "parser_hint": hint,
    }
    c.update(extra)
    return c


def parse_linkedin_cards(page, source="linkedin_il"):
    """Guest-API HTML -> candidates. Strips the tracking query from the URL."""
    out = []
    for chunk in re.split(r"<li\b", page):
        m = re.search(r"<a\b[^>]*base-card__full-link[^>]*>", chunk)
        if not m:
            continue
        hm = re.search(r'href="([^"]+)"', m.group(0))
        if not hm:
            continue
        url = re.split(r"[?#]", html.unescape(hm.group(1)))[0]

        def grab(pat):
            g = re.search(pat, chunk, re.S)
            return strip_html(g.group(1), 200) if g else ""

        title = grab(r'<h3[^>]*base-search-card__title[^>]*>(.*?)</h3>')
        company = grab(r'<h4[^>]*base-search-card__subtitle[^>]*>(.*?)</h4>')
        loc = grab(r'<span[^>]*job-search-card__location[^>]*>(.*?)</span>')
        tm = re.search(r'<time\b[^>]*datetime="([^"]+)"', chunk)
        if title and url:
            out.append(cand(company, title, loc, url, tm.group(1) if tm else None, source))
    return out


def linkedin_job_id(url):
    m = re.search(r"-(\d+)/?(?:[?#]|$)", url or "") or re.search(r"/view/(\d+)", url or "")
    return m.group(1) if m else None


def parse_greenhouse(company, slug, text):
    d = json.loads(text)
    return [
        cand(company, j.get("title"), (j.get("location") or {}).get("name"),
             j.get("absolute_url"), None, "company:" + company, "greenhouse",
             _gh=(slug, j.get("id")))
        for j in d.get("jobs", [])[:PER_BOARD_CAP]
    ]


def parse_lever(company, text):
    d = json.loads(text)
    return [
        cand(company, j.get("text"), (j.get("categories") or {}).get("location"),
             j.get("hostedUrl"), None, "company:" + company, "lever")
        for j in d[:PER_BOARD_CAP]
    ]


def parse_comeet(company, url, page, hint="comeet"):
    # Comeet boards embed positions as JSON in a script tag, or as /co/<...> links.
    src, seen, out = "company:" + company, set(), []
    for m in re.finditer(r'"name"\s*:\s*"([^"]{4,120})"[^}]*?"location"\s*:\s*\{[^}]*?"name"\s*:\s*"([^"]{2,80})"', page):
        t, loc = m.group(1), m.group(2)
        if t in seen:
            continue
        seen.add(t)
        out.append(cand(company, t, loc, url, None, src, hint))
        if len(out) >= PER_BOARD_CAP:
            return out
    for m in re.finditer(r'href="(/co/[^"?#]+)"[^>]*>([^<]{4,120})<', page):
        u, t = m.group(1), m.group(2)
        if t in seen:
            continue
        seen.add(t)
        out.append(cand(company, t, "unknown", "https://www.comeet.com" + u, None, src, hint))
        if len(out) >= PER_BOARD_CAP:
            break
    return out


def parse_generic(company, url, page, hint="generic"):
    txt = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I)
    out = []
    for m in re.finditer(r'href="([^"?#]*(?:career|job|position|opening|vacanc)[^"?#]*)"[^>]*>([^<]{6,120})<', txt, re.I):
        u, t = m.group(1), clean(m.group(2))
        if len(t.split()) < 2 or t.lower() in ("careers", "open positions", "job openings", "view all jobs", "all jobs"):
            continue
        out.append(cand(company, t, "Israel", urllib.parse.urljoin(url, u), None, "company:" + company, hint))
        if len(out) >= PER_BOARD_CAP:
            break
    return out


def parse_render_links(rendered, base_url, company, hint="js_render"):
    """render.py output -> job-like links (path hint + anchor of >=2 words)."""
    m = re.search(r"=== LINKS ===\n(.*?)(?:\n=== TEXT ===|\Z)", rendered, re.S)
    out, seen = [], set()
    for line in (m.group(1) if m else "").splitlines():
        href, _, anchor = line.partition("\t")
        anchor = clean(anchor)
        path = urllib.parse.urlparse(href).path.lower()
        if not any(k in path for k in ("/co/", "/job", "/position", "/careers/")):
            continue
        if len(anchor.split()) < 2 or href in seen or href.rstrip("/") == base_url.rstrip("/"):
            continue
        seen.add(href)
        out.append(cand(company, anchor, "unknown", href, None, "company:" + company, hint))
        if len(out) >= PER_BOARD_CAP:
            break
    return out


def parse_alljobs_cards(page, source="alljobs"):
    """AllJobs search page -> candidates (one per `job-content-top` card).

    Skips closed jobs. Company is "unknown" when the card has none (hidden).
    Multi-city cards list their cities in a nested box; keep the first 4.
    """
    out, ids = [], set()
    for chunk in re.split(r'<div class="job-content-top">', page or "")[1:]:
        m = re.search(r'<a\b[^>]*href="[^"]*UploadSingle\.aspx\?JobID=(\d+)"[^>]*>(.*?)</a>', chunk, re.S)
        if not m or m.group(1) in ids or re.search(r'job-content-top-title[^"]*closed-job', chunk):
            continue
        jid, title = m.group(1), strip_html(m.group(2), 200)
        cm = re.match(r'(?:</div>)*\s*<div class="T14">(.*?)</div>', chunk[m.end():], re.S)
        company = strip_html(cm.group(1), 100) if cm else ""
        lm = re.search(r'job-content-top-location(?:-ltr)?">(.*?)(?=job-content-top-type|job-content-top-acord)', chunk, re.S)
        cities = re.findall(r'<a\b[^>]*>([^<]+)</a>', lm.group(1)) if lm else []
        loc = ", ".join(clean(c) for c in cities[:4])
        if not title:
            continue
        ids.add(jid)
        out.append(cand(company or "unknown", title, loc, "%s/Search/UploadSingle.aspx?JobID=%s" % (ALLJOBS_BASE, jid),
                        None, source))
    return out


def parse_drushim_cards(page, source="drushim"):
    """Drushim search page -> candidates (one per `job-card-item` article)."""
    out, paths = [], set()
    for chunk in re.split(r"<article\b", page or "")[1:]:
        chunk = chunk.split("</article>")[0]
        hm = re.search(r'href="(/job/[^"?#]+)"', chunk)
        tm = re.search(r'<h3\b[^>]*job-card-title[^>]*>(.*?)</h3>', chunk, re.S)
        if not hm or not tm or hm.group(1) in paths:
            continue
        cm = re.search(r'class="[^"]*companyName">(.*?)</span>', chunk, re.S)
        rows = re.split(r'class="[^"]*job-card-meta-module[^"]*__row"', chunk)
        row = rows[1] if len(rows) > 1 else ""  # first meta row = location
        items = re.findall(r'class="[^"]*job-card-meta-tooltip[^"]*__item"[^>]*>(.*?)</span>', row, re.S)
        if not items:
            lm = re.search(r'class="[^"]*job-card-meta-module[^"]*__text"[^>]*>(.*?)</span>', row, re.S)
            items = [lm.group(1)] if lm else []
        paths.add(hm.group(1))
        out.append(cand(strip_html(cm.group(1), 100) if cm else "unknown", strip_html(tm.group(1), 200),
                        ", ".join(strip_html(i, 60) for i in items[:4]), DRUSHIM_BASE + hm.group(1), None, source))
    return out


# --------------------------------------------------------------------------
# Listing jobs: each returns (candidates, raw_page_text_or_None)
# --------------------------------------------------------------------------

def linkedin_url(keywords, location, tpr):
    return "%s?keywords=%s&location=%s&f_TPR=%s&start=0" % (
        LI_SEARCH, urllib.parse.quote(keywords, safe=""),
        urllib.parse.quote(location, safe=""), urllib.parse.quote(tpr, safe=""))


def board_url(src, q):
    t, base = src.get("type"), src["base_url"]
    if t == "drushim":  # <base>/<q>/ (path-style; ?q= returns 404)
        return "%s/%s/" % (base.rstrip("/"), urllib.parse.quote(q, safe=""))
    if t == "alljobs":  # <base>?freetxt=<q>&region=<codes, comma-joined>
        regions = ",".join(str(r) for r in src.get("region_codes") or [])
        u = "%s?freetxt=%s" % (base, urllib.parse.quote(q, safe=""))
        return u + ("&region=" + regions if regions else "")
    # glassdoor/wellfound/ycs: <base>?q=<q>, best effort
    return "%s?q=%s" % (base, urllib.parse.quote(q, safe=""))


def page_text(raw, src_type, cap=RAW_PAGE_CAP):
    """Tag-stripped board page, capped. AllJobs: skip the nav block before the first card."""
    text = strip_html(raw, 10 ** 7)
    if src_type == "alljobs":
        m = re.search(r"לפני \d+ ", text)
        if m and m.start() > 200:
            text = text[max(0, m.start() - 80):]
    return text[:cap]


def board_listing(raw, src_type, sid, cap):
    """Board page -> (cards, None); raw page text only when no card parsed."""
    parse = {"alljobs": parse_alljobs_cards, "drushim": parse_drushim_cards}.get(src_type)
    rows = parse(raw, sid)[:cap] if parse else []
    return (rows, None) if rows else ([], page_text(raw, src_type))


def source_jobs(src, cap):
    """-> list of (meta, fn)."""
    sid, t = src["id"], src.get("type")
    queries = list(src.get("queries") or []) + list(src.get("queries_he") or []) + list(src.get("queries_en") or [])
    jobs = []
    for q in queries:
        if t == "linkedin":
            url = linkedin_url(q, src.get("location_param", "Israel"), src.get("f_TPR", "r604800"))
            fn = (lambda url=url, sid=sid: (parse_linkedin_cards(li_get(url), sid)[:cap], None))
        else:
            url = board_url(src, q)
            fn = (lambda url=url, t=t, sid=sid: board_listing(get(url), t, sid, cap))
        jobs.append(({"id": sid, "query": q, "url": url}, fn))
    return jobs


def slug_of(co):
    return co.get("slug") or (co.get("careers_url") or "").rstrip("/").rsplit("/", 1)[-1]


def company_job(co, li_tpr):
    name, hint, url = co["name"], co.get("parser_hint") or "generic", co.get("careers_url") or ""
    slug = slug_of(co)
    src = "company:" + name
    if hint == "greenhouse":
        url = "https://boards-api.greenhouse.io/v1/boards/%s/jobs" % slug
        fn = lambda: (parse_greenhouse(name, slug, get(url)), None)
    elif hint == "lever":
        url = "https://api.lever.co/v0/postings/%s?mode=json" % slug
        fn = lambda: (parse_lever(name, get(url)), None)
    elif hint in ("comeet", "comeet_url"):
        if hint == "comeet":
            url = "https://www.comeet.com/jobs/%s/" % slug
        fn = lambda: (parse_comeet(name, url, get(url), hint), None)
    elif hint == "js_render":
        fn = lambda: (render_company(name, url), None)
    elif hint == "linkedin_only":
        url = linkedin_url(name, "Israel", li_tpr)

        def fn():
            rows = parse_linkedin_cards(li_get(url), src)
            rows = [r for r in rows if name.lower() in r["company"].lower()]
            for r in rows:
                r["parser_hint"] = "linkedin_only"
            return rows, None
    else:  # workday / generic
        fn = lambda: (parse_generic(name, url, get(url), hint), None)
    return {"id": src, "query": None, "url": url}, fn


def render_company(name, url):
    render = str(HERE / "render.py")
    with RENDER_SEM:
        r = subprocess.run([sys.executable, render, url], capture_output=True, text=True, timeout=RENDER_TIMEOUT)
    if r.returncode != 0:
        raise RuntimeError("render exit %d" % r.returncode)
    return parse_render_links(r.stdout, url, name)


# --------------------------------------------------------------------------
# Dedupe
# --------------------------------------------------------------------------

def _ids(s):
    return set(re.findall(r"\d{7,}", s or ""))


def load_ledger(path):
    """seen.jsonl -> (url_hashes, content_hashes, ids).

    Older runs wrote ids (li_123, aj_456) and raw "company|title" strings
    instead of sha1, so also index the ledger's urls and numeric ids.
    """
    urls, contents = load_seen(str(path))
    ids = set()
    try:
        with open(str(path)) as f:
            for line in f:
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(o, dict):
                    continue
                u = o.get("url") or ""
                if u.startswith("http"):
                    urls.add(h(u))
                ids |= _ids(u) | _ids(o.get("url_hash") or o.get("hash") or "")
    except FileNotFoundError:
        pass
    return urls, contents, ids


def mark_seen(cands, urls, contents, ids=(), dedupe=True):
    """Hash, flag seen, collapse in-run content duplicates (keep first)."""
    out, run, ids = [], set(), set(ids)
    for c in cands:
        c["url_hash"] = h(c["url"])
        raw = c["company"] + "|" + c["title"]
        c["content_hash"] = h(raw)
        if c["content_hash"] in run:
            continue
        run.add(c["content_hash"])
        c["seen"] = bool(dedupe and (
            c["url_hash"] in urls or c["content_hash"] in contents
            or raw.lower() in contents or (_ids(c["url"]) & ids)))
        out.append(c)
    return out


def compile_title_exclude(patterns):
    out = []
    for p in patterns or []:
        try:
            out.append(re.compile(str(p), re.I))
        except re.error as e:
            log("WARN bad title_exclude %r: %s" % (p, e))
    return out


def triage_titles(cands, rx):
    """Set c["triage"]: "title-exclude" for unseen titles matching rx, else "ok"."""
    for c in cands:
        hit = not c["seen"] and any(r.search(c["title"]) for r in rx)
        c["triage"] = "title-exclude" if hit else "ok"


def round_robin(cands):
    groups = {}
    for c in cands:
        groups.setdefault(c["source"], []).append(c)
    return [c for row in zip_longest(*groups.values()) for c in row if c]


# --------------------------------------------------------------------------
# JD bodies
# --------------------------------------------------------------------------

def fetch_body(c):
    url, gh = c["url"], c.get("_gh")
    if "linkedin.com" in url:
        jid = linkedin_job_id(url)
        if not jid:
            return None
        m = re.search(r'<div[^>]*show-more-less-html__markup[^>]*>(.*?)</div>', li_get(LI_POSTING + jid), re.S)
        return strip_html(m.group(1), BODY_CAP) if m else None
    if not gh:
        g = re.search(r"greenhouse\.io/([^/?#]+)/jobs/(\d+)", url)
        gh = g.groups() if g else None
    if gh and gh[1]:
        d = json.loads(get("https://boards-api.greenhouse.io/v1/boards/%s/jobs/%s" % (gh[0], gh[1])))
        return strip_html(html.unescape(d.get("content") or ""), BODY_CAP) or None
    raw = get(url)
    if "alljobs.co.il" in url:  # drop the ~1k chars of nav before the job block
        i = raw.find("job-content-top-title")
        raw = raw[i:] if i >= 0 else raw
    return strip_html(raw, BODY_CAP) or None


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def _guarded(fn, deadline):
    if deadline.expired():
        return "deadline", None
    try:
        return "ok", fn()
    except Exception as e:  # never raise out of a worker
        return status_of(e), None


def run_jobs(ex, fns, deadline):
    futs = [ex.submit(_guarded, fn, deadline) for fn in fns]
    wait(futs, timeout=deadline.remaining())
    res, hit = [], False
    for f in futs:
        if f.done():
            res.append(f.result())
        else:
            f.cancel()
            res.append(("deadline", None))
            hit = True
    return res, hit


def interleave(groups):
    return [j for row in zip_longest(*groups) for j in row if j is not None]


def load_yaml(path):
    try:
        with open(str(path)) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def build(root, out_path, deadline_sec, only_source, dedupe, max_bodies):
    global UA
    t0 = time.monotonic()
    deadline = Deadline(deadline_sec)
    srcs = load_yaml(root / "sources.yaml")
    settings = srcs.get("settings") or {}
    UA = settings.get("user_agent") or UA
    cap = int(settings.get("max_jds_per_source") or 25)
    max_bodies = int(max_bodies if max_bodies is not None else settings.get("max_total_jds") or 120)

    groups, li_tpr = [], "r604800"
    for s in srcs.get("sources") or []:
        if s.get("type") == "linkedin":
            li_tpr = s.get("f_TPR", li_tpr)
        if s.get("enabled", True) is False or (only_source and s.get("id") != only_source):
            continue
        groups.append(source_jobs(s, cap))
    if not only_source or only_source == "companies":
        for co in load_yaml(root / "companies.yaml").get("companies") or []:
            if co.get("enabled", True) is False or co.get("parser_hint") == "disabled":
                continue
            groups.append([company_job(co, li_tpr)])
    jobs = interleave(groups)

    sources, raw_pages, cands = [], [], []
    ex = ThreadPoolExecutor(max_workers=WORKERS)
    try:
        res, hit = run_jobs(ex, [fn for _, fn in jobs], deadline)
        t_list = time.monotonic() - t0
        for (meta, _), (status, val) in zip(jobs, res):
            rows, page = val if val else ([], None)
            entry = dict(meta, status=status, n=len(rows))
            if page is not None:
                entry["chars"] = len(page)
                raw_pages.append({"source": meta["id"], "query": meta["query"], "url": meta["url"], "text": page})
            sources.append(entry)
            cands.extend(rows)
            q = ' "%s"' % meta["query"] if meta["query"] else ""
            detail = "n=%d" % len(rows) if page is None else "chars=%d" % len(page)
            log(("OK %s%s %s" % (meta["id"], q, detail)) if status == "ok" else ("FAIL %s%s %s" % (meta["id"], q, status)))

        urls, contents, ids = load_ledger(root / "state" / "seen.jsonl")
        cands = round_robin(mark_seen(cands, urls, contents, ids, dedupe))

        triage_titles(cands, compile_title_exclude(settings.get("title_exclude")))
        todo = [c for c in cands if not c["seen"] and c["triage"] == "ok"][:max_bodies]
        todo_ids = set(id(c) for c in todo)
        for c in cands:
            c["description"] = None
            c["description_status"] = (
                "skipped-seen" if c["seen"] else
                "skipped-title" if c["triage"] == "title-exclude" else
                "pending" if id(c) in todo_ids else "skipped-max")
        bres, bhit = run_jobs(ex, [(lambda c=c: fetch_body(c)) for c in todo], deadline)
        hit = hit or bhit
        for c, (status, body) in zip(todo, bres):
            if status == "ok":
                c["description"], c["description_status"] = (body, "ok") if body else (None, "no body")
            else:
                c["description_status"] = status
    finally:
        ex.shutdown(wait=False, cancel_futures=True)

    out = {
        "run": datetime.now().isoformat(timespec="seconds"),
        "deadline_hit": bool(hit),
        "no_dedupe": not dedupe,
        "duration_sec": round(time.monotonic() - t0, 1),
        "sources": sources,
        "candidates": [{k: v for k, v in c.items() if not k.startswith("_")} for c in cands],
        "raw_pages": raw_pages,
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    n_unseen = sum(1 for c in cands if not c["seen"])
    n_excl = sum(1 for c in cands if c["triage"] == "title-exclude")
    n_body = sum(1 for c in cands if c["description_status"] == "ok")
    n_fail = sum(1 for s in sources if s["status"] != "ok")
    print("prefetch: %d candidates (%d unseen, %d title-excluded), %d bodies ok/%d tried, %d/%d sources failed, %.1fs (listings %.1fs)%s -> %s" % (
        len(cands), n_unseen, n_excl, n_body, len(todo), n_fail, len(sources), time.monotonic() - t0, t_list,
        ", DEADLINE HIT" if hit else "", out_path))
    return out


def main(argv=None, root=None):
    root = Path(root) if root else HERE
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out", help="output path (default state/candidates_<date>.json)")
    p.add_argument("--deadline", type=float, default=240, help="global deadline in seconds")
    p.add_argument("--source", help="restrict to one source id ('companies' for company pages only)")
    p.add_argument("--no-dedupe", action="store_true", help="mark everything unseen")
    p.add_argument("--max", type=int, help="max JD bodies to fetch (default settings.max_total_jds)")
    a = p.parse_args(argv)
    out = a.out or str(root / "state" / ("candidates_%s.json" % date.today().isoformat()))
    try:
        build(root, out, a.deadline, a.source, not a.no_dedupe, a.max)
    except Exception as e:  # output unwritable or config unreadable
        log("FATAL %s: %s" % (type(e).__name__, e))
        return 1
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)  # do not wait on in-flight requests after a deadline
