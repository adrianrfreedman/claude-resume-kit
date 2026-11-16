"""Daily tracker digest: render(apps, today, since, ledger) -> (subject, html, text).

Pure function; track.py --digest does the I/O. Email-safe: table layout, inline styles.
"""

from __future__ import annotations

import colorsys
import html as _h
from datetime import date, datetime, timedelta

import applications as A
from send_digest import ALIAS

SECTIONS = ["interviewing", "offer", "acknowledged", "applied", "prepared", "ghosted"]
CLOSED_DAYS = 30
CAL_WEEKS = 4  # week rows in the interview calendar grid
FULL_ROWS = 5  # rows per section shown in full; the rest are compact
INK, MUTED, RULE, ACCENT, WASH = "#1d2a2e", "#5b6b70", "#d5e1e3", "#0f5c6e", "#eef5f6"
SERIF = "Georgia,'Times New Roman',serif"
SANS = "-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"
FOOTER = ("Got news? Reply to this email in your own words, e.g. 'withdrew from Veeva' or "
          "'Roche called, interview next week', or forward any company email to "
          f"{ALIAS}.")
PHRASE = {
    "prepared": "package prepared", "applied": "applied", "acknowledged": "application received",
    "interviewing": "interview", "offer": "offer", "rejected": "rejected",
    "withdrawn": "withdrawn", "note": "note",
}
# (bold lead, text); None = the "got it" reply bullet
HOWTO = [
    ("Applied?", "Reply “applied” to the package email, or reply to a job-scan email with the job: "
                 "“applied to #3” or “applied to the Teva one”."),
    ("Heard from a company?", f"Forward the email to {ALIAS}. "
                              "Add a line on top if it’s unclear which job it’s about."),
    ("Any other news?", "Reply to this digest in your own words, e.g. “withdrew from Veeva” "
                        "or “Roche called, interview Tuesday”."),
    ("Changes to a CV or letter?", "Reply to that package’s email; the updated files come back in the same thread."),
    ("Interview booked?", "Reply with the date and time, or forward the invitation; it shows up in the calendar at the top."),
    None,
    ("Colours", "show days since you last heard anything: green is fresh, red is 30 days or more. "
                "After 30 days with no news, an application is marked Ghosted. Any news brings it back."),
]
GOT_IT = ("You’ll get a short “got it” reply within a few minutes saying what was recorded. "
          "If it’s wrong, reply to correct it.")

e = _h.escape


def age_hex(d: int, l: float = 0.42, s: float = 0.55) -> str:
    """Green (fresh) to red (30+ days)."""
    h = 130 * (1 - min(max(d, 0), 30) / 30)
    r, g, b = colorsys.hls_to_rgb(h / 360, l, s)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def days_label(d: int) -> str:
    return "today" if d == 0 else "1 day" if d == 1 else f"{d} days"


def short(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d:%b}"


def _dt(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s) if s else None
    except ValueError:
        return None


def _after(s: str | None, since: datetime) -> bool:
    t = _dt(s)
    return t is not None and t > since


def _new_events(app: dict, since: datetime) -> list[dict]:
    return [ev for ev in app["events"] if _after(ev.get("recorded"), since)]


def _forwarded_new(app: dict, since: datetime) -> bool:
    """Created this window by a forwarded email: all events new, no scan/package origin."""
    return (bool(app["events"]) and len(_new_events(app, since)) == len(app["events"])
            and not (app.get("scan_id") or app.get("package") or app.get("job_url")))


def _sentence(co: str, ev: dict) -> str:
    s = f"{co}: {PHRASE[ev['type']]}"
    note = (ev.get("note") or "").strip().rstrip(".")
    return f"{s}, {note}." if note else f"{s}."


def whats_new(apps: list[dict], since: datetime) -> list[str]:
    items = []  # (recorded, sentence)
    for app in apps:
        new = _new_events(app, since)
        if not new:
            continue
        if _forwarded_new(app, since):
            last = next((ev for ev in reversed(new) if ev["type"] != "applied"), new[-1])
            items.append((new[-1]["recorded"], f"{app['company']}: new, from a forwarded email ({PHRASE[last['type']]})."))
        else:
            items += [(ev["recorded"], _sentence(app["company"], ev)) for ev in new]
    return [s for _, s in sorted(items)]


def _days(app: dict, today: date) -> int:
    d = A.days_since(app, today)
    return max(d, 0) if d is not None else 0


def _summary(app: dict) -> str:
    if app.get("summary"):
        return app["summary"]
    ev = A.last_event(app)
    return (ev.get("note") or "") if ev else ""


def _closed_line(apps: list[dict], today: date) -> str:
    parts = []
    for app in apps:
        st = A.status(app, today)
        if st in A.CLOSED and _days(app, today) < CLOSED_DAYS:
            parts.append(f"{app['company']} ({st} {short(A.last_event(app)['date'])})")
    return "Closed: " + ", ".join(parts) if parts else ""


def _revised(apps, ledger, since) -> list[str]:
    by_pkg = {a.get("package"): a["company"] for a in apps if a.get("package")}
    out = []
    for ent in ledger.values():
        if (ent.get("kind") == "package" and ent.get("intent") in ("edits", "both")
                and ent.get("status") == "done" and _after(ent.get("time"), since)):
            pkg = ent.get("package") or ""
            out.append(by_pkg.get(pkg) or pkg.rsplit("/", 1)[-1] or "Package")
    return out


def _unusable(ledger, since) -> list[str]:
    return [ent.get("subject") or "(no subject)" for ent in ledger.values()
            if ent.get("status") == "unusable" and _after(ent.get("time"), since)]


def _groups(apps: list[dict], today: date, since: datetime) -> list[tuple[str, list[dict]]]:
    rows = []
    for app in apps:
        st = A.status(app, today)
        if st in SECTIONS:
            fwd = _forwarded_new(app, since)
            rows.append(dict(
                st=st, co=app["company"], role=app["role"], d=_days(app, today), summary=_summary(app),
                fwd=fwd, new=bool(_new_events(app, since)), pkg=app.get("package"),
            ))
    out = []
    for st in SECTIONS:
        items = sorted((r for r in rows if r["st"] == st), key=lambda r: (r["d"], r["co"].lower()))
        if items:
            out.append((st, items))
    return out


def _last_interview(app: dict) -> dict | None:
    return next((ev for ev in reversed(app["events"]) if ev["type"] == "interviewing"), None)


def upcoming_interviews(apps: list[dict], today: date) -> tuple[list[dict], list[dict]]:
    """(dated, undated): the latest interview slot per open app, from today on."""
    dated, undated = [], []
    for app in apps:
        st = A.status(app, today)
        if st in A.CLOSED:
            continue
        slots = [ev for ev in app["events"] if ev["type"] == "interviewing" and ev.get("when")]
        if slots:
            w = slots[-1]["when"]
            day = date.fromisoformat(w[:10])
            if day >= today:
                dated.append(dict(day=day, time=w[11:16], co=app["company"], role=app["role"],
                                  note=(slots[-1].get("note") or "").strip()))
        elif st == "interviewing":
            last = _last_interview(app)
            undated.append(dict(co=app["company"], role=app["role"], note=((last or {}).get("note") or "").strip()))
    dated.sort(key=lambda r: (r["day"], r["time"], r["co"].lower()))
    undated.sort(key=lambda r: r["co"].lower())
    return dated, undated


def _tags(r: dict) -> list[str]:
    if r["fwd"]:
        return ["New, from a forwarded email"]
    return ["New today"] if r["new"] else []


# ---------------------------------------------------------------- html

def _details_lines(r: dict) -> str:
    """Extra detail only (summary + tags); never the company/role."""
    lines = ""
    if r["summary"]:
        lines += f'<div style="font-size:13px;color:{MUTED};padding-top:2px;">{e(r["summary"])}</div>'
    for t in _tags(r):
        lines += f'<div style="font-size:12px;color:{ACCENT};padding-top:3px;">{e(t)}</div>'
    if r["st"] == "prepared" and r["pkg"]:
        lines += f'<div style="font-size:12px;color:{MUTED};padding-top:3px;">Package: {e(r["pkg"])}</div>'
    return lines


def _row_table(left: str, right: str, tint: str, pad: str, rpad: str) -> str:
    return (f'<tr><td style="padding:0 0 4px 0;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="background:{tint};"><tr>'
            f'<td valign="top" style="padding:{pad};">{left}</td>'
            f'<td width="64" align="right" valign="middle" style="width:64px;padding:{rpad};text-align:right;">{right}</td>'
            f'</tr></table></td></tr>\n')


def _row(r: dict) -> str:
    strong, tint = age_hex(r["d"]), age_hex(r["d"], l=0.93)
    lines = f'<div style="font-weight:bold;color:{INK};font-size:15px;">{e(A.who(r["co"], r["role"]))}</div>' + _details_lines(r)
    num = (f'<div style="font-family:{SERIF};font-size:26px;font-weight:bold;line-height:1.1;color:{strong};">{r["d"]}</div>'
           if r["d"] else "")
    unit = "today" if r["d"] == 0 else "day" if r["d"] == 1 else "days"
    return _row_table(lines, f'{num}<div style="font-size:11px;color:{MUTED};">{unit}</div>', tint,
                      "12px 14px", "12px 14px 12px 0")


def _row_compact(r: dict) -> str:
    strong, tint = age_hex(r["d"]), age_hex(r["d"], l=0.93)
    title = e(A.who(r["co"], r["role"]))
    body = _details_lines(r)
    if body:
        left = (f'<details><summary style="cursor:pointer;font-weight:bold;color:{INK};font-size:14px;">{title}</summary>'
                f'{body}</details>')
    else:
        left = f'<div style="font-weight:bold;color:{INK};font-size:14px;">{title}</div>'
    right = (f'<div style="font-family:{SERIF};font-size:18px;font-weight:bold;line-height:1.1;color:{strong};">{r["d"]}</div>'
             if r["d"] else f'<div style="font-size:12px;color:{MUTED};">today</div>')
    return _row_table(left, right, tint, "7px 14px", "7px 14px 7px 0")


def _section(st: str, items: list[dict]) -> str:
    head = (f'<tr><td style="padding:0 0 8px 0;"><div style="font-family:{SERIF};font-size:19px;color:{INK};'
            f'border-bottom:1px solid {RULE};padding-bottom:4px;">{st.capitalize()} '
            f'<span style="color:{MUTED};">{len(items)}</span></div></td></tr>\n')
    rows = "".join(_row(r) for r in items[:FULL_ROWS]) + "".join(_row_compact(r) for r in items[FULL_ROWS:])
    return (f'<tr><td style="padding:0 0 18px 0;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            f'{head}{rows}</table></td></tr>\n')


def _cell(inner: str, pad: str = "0 0 18px 0") -> str:
    return f'<tr><td style="padding:{pad};">{inner}</td></tr>\n'


def _agenda_when(r: dict) -> str:
    d = r["day"]
    return f"{d:%a} {d.day} {d:%b}" + (f", {r['time']}" if r["time"] else "")


def _cal_cell(day: date, today: date, items: list[dict]) -> str:
    label = f"{day.day} {day:%b}" if day.day == 1 else str(day.day)
    if day == today:
        num = f"font-weight:bold;color:{INK}"
    else:
        num = f"color:{'#b8c4c7' if day < today else MUTED}"
    bg = f"background:{WASH};" if day == today or items else ""
    inner = "".join(
        f'<div style="font-size:11px;font-weight:bold;color:{ACCENT};word-break:break-word;padding-top:2px;">'
        f'{e(it["time"] + " " if it["time"] else "")}{e(it["co"])}</div>' for it in items)
    return (f'<td valign="top" style="{bg}border:1px solid {RULE};padding:4px;height:44px;">'
            f'<div style="font-size:11px;{num};">{e(label)}</div>{inner}</td>')


def _calendar(today: date, dated: list[dict]) -> str:
    start = today - timedelta(days=(today.weekday() + 1) % 7)  # Sunday
    last = dated[-1]["day"]
    weeks = min(CAL_WEEKS, max(1, (last - start).days // 7 + 1))
    by_day = {}
    for r in dated:
        by_day.setdefault(r["day"], []).append(r)
    head = "".join(f'<td align="center" style="font-size:11px;color:{MUTED};padding:0 0 3px;">{n}</td>'
                   for n in ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"))
    rows = "".join(
        "<tr>" + "".join(_cal_cell(d, today, by_day.get(d, []))
                         for d in (start + timedelta(days=7 * w + i) for i in range(7))) + "</tr>"
        for w in range(weeks))
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="table-layout:fixed;border-collapse:collapse;"><tr>{head}</tr>{rows}</table>')


def _upcoming_html(today: date, dated: list[dict], undated: list[dict]) -> str:
    n = len(dated) + len(undated)
    head = (f'<div style="font-family:{SERIF};font-size:19px;color:{INK};border-bottom:1px solid {RULE};'
            f'padding-bottom:4px;margin-bottom:8px;">Upcoming interviews <span style="color:{MUTED};">{n}</span></div>')
    body = _calendar(today, dated) if dated else ""
    if dated:
        lines = ""
        for r in dated:
            note = f'<div style="font-size:13px;color:{MUTED};">{e(r["note"])}</div>' if r["note"] else ""
            lines += (f'<div style="padding-top:8px;font-size:15px;color:{INK};"><b>{e(_agenda_when(r))}</b> '
                      f'{e(A.who(r["co"], r["role"]))}{note}</div>')
        body += f'<div style="padding-top:2px;">{lines}</div>'
    if undated:
        names = ", ".join(A.who(r["co"], r["role"]) for r in undated)
        body += (f'<div style="font-size:13px;color:{MUTED};padding-top:10px;">No date recorded: {e(names)}. '
                 f'Reply with the date and time and it will appear here.</div>')
    return head + body


def _html(today, news, groups, closed, revised, unusable, dated=(), undated=(), sheet_url=None) -> str:
    b = _cell(f'<div style="font-family:{SERIF};font-size:26px;color:{INK};">Application tracker</div>'
              f'<div style="font-size:13px;color:{MUTED};padding-top:2px;">{today:%A} {today.day} {today:%B %Y}</div>', "0 0 20px 0")
    if sheet_url:
        b += _cell(f'<a href="{e(sheet_url, quote=True)}" style="font-size:14px;color:{ACCENT};">Open the tracker sheet</a>', "0 0 18px 0")
    if news:
        body = ('<ul style="margin:0;padding:0 0 0 18px;">'
                + "".join(f'<li style="padding:0 0 4px;font-size:15px;line-height:1.5;color:{INK};">{e(n)}</li>' for n in news)
                + '</ul>')
    else:
        body = f'<p style="margin:0;font-size:15px;line-height:1.5;color:{INK};">No news since the last digest.</p>'
    b += _cell(f'<div style="font-family:{SERIF};font-size:19px;color:{INK};padding-bottom:6px;">What’s new</div>{body}', "0 0 22px 0")
    if dated or undated:
        b += _cell(_upcoming_html(today, list(dated), list(undated)), "0 0 22px 0")
    b += "".join(_section(st, items) for st, items in groups)
    if closed:
        b += _cell(f'<div style="font-size:13px;color:{MUTED};">{e(closed)}</div>')
    if revised:
        lines = "".join(f'<div style="padding-top:4px;">{e(c)}: updated from your edits; the new files are in that email thread.</div>'
                        for c in revised)
        b += _cell(f'<div style="padding:14px 18px;background:{WASH};border-left:4px solid {ACCENT};">'
                   f'<div style="font-family:{SERIF};font-size:19px;color:{ACCENT};">Revised packages</div>{lines}</div>')
    if unusable:
        subs = "".join(f'<div style="padding-top:2px;">{e(s)}</div>' for s in unusable)
        b += _cell(f'<div style="font-size:13px;color:{INK};"><b>Couldn’t use</b>{subs}'
                   f'<div style="color:{MUTED};padding-top:6px;">Reply to this email with the company and role for any of these.</div></div>')
    b += _cell(f'<div style="border-top:1px solid {RULE};padding-top:10px;font-size:13px;color:{MUTED};">{e(FOOTER)}</div>', "4px 0 14px 0")
    items = "".join(
        f'<li style="margin:0 0 4px 0;">{"<b>" + e(it[0]) + "</b> " + e(it[1]) if it else e(GOT_IT)}</li>' for it in HOWTO)
    b += _cell(f'<details><summary style="font-size:13px;color:{MUTED};">How to use this</summary>'
               f'<ul style="margin:6px 0 0 0;padding-left:18px;font-size:13px;color:{MUTED};line-height:1.5;">{items}</ul></details>', "0")
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Application tracker</title></head>'
            f'<body style="margin:0;padding:0;background:#ffffff;">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#ffffff;"><tr>'
            f'<td align="center" style="padding:20px 12px;">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="max-width:600px;width:100%;font-family:{SANS};font-size:15px;line-height:1.45;color:{INK};">\n{b}'
            f'</table></td></tr></table></body></html>')


def _text(today, news, groups, closed, revised, unusable, dated=(), undated=(), sheet_url=None) -> str:
    L = [f"Application tracker, {today:%A} {today.day} {today:%B %Y}", ""]
    if sheet_url:
        L += [f"Tracker sheet: {sheet_url}", ""]
    L += ["What's new"]
    L += [f"- {n}" for n in news] if news else ["No news since the last digest."]
    if dated or undated:
        L += ["", "Upcoming interviews"]
        for r in dated:
            L.append(f"- {_agenda_when(r)}: {A.who(r['co'], r['role'])}" + (f": {r['note']}" if r["note"] else ""))
        if undated:
            names = ", ".join(A.who(r["co"], r["role"]) for r in undated)
            L.append(f"No date recorded: {names}. Reply with the date and time and it will appear here.")
    for st, items in groups:
        L += ["", f"{st.capitalize()} ({len(items)})"]
        for r in items:
            tag = "".join(f" [{t.lower()}]" for t in _tags(r))
            pkg = f" [package: {r['pkg']}]" if r["st"] == "prepared" and r["pkg"] else ""
            L.append(f"- {A.who(r['co'], r['role'])} ({days_label(r['d'])})" + (f": {r['summary']}" if r["summary"] else "") + tag + pkg)
    if closed:
        L += ["", closed]
    for c in revised:
        L += ["", f"Revised package: {c}: updated from your edits; the new files are in that email thread."]
    if unusable:
        L += ["", "Couldn't use:"] + [f"- {s}" for s in unusable]
        L.append("Reply to this email with the company and role for any of these.")
    L += ["", FOOTER, "", "How to use this"]
    L += [f"- {it[0]} {it[1]}" if it else f"- {GOT_IT}" for it in HOWTO]
    return "\n".join(L) + "\n"


def render(apps: list[dict], today: date, since: datetime, ledger: dict, sheet_url: str | None = None) -> tuple[str, str, str]:
    news = whats_new(apps, since)
    groups = _groups(apps, today, since)
    closed = _closed_line(apps, today)
    revised, unusable = _revised(apps, ledger, since), _unusable(ledger, since)
    dated, undated = upcoming_interviews(apps, today)
    n = len(news)
    upd = "no new updates" if n == 0 else f"{n} update" + ("" if n == 1 else "s")
    subject = f"Your applications, {today:%a} {today.day} {today:%b}: {upd}"
    return (subject, _html(today, news, groups, closed, revised, unusable, dated, undated, sheet_url),
            _text(today, news, groups, closed, revised, unusable, dated, undated, sheet_url))
