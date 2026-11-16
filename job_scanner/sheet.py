#!/usr/bin/env python3
"""Mirror the application tracker into a Google Sheet via an Apps Script web app (stdlib only).

`python3 sheet.py` forces a push: the setup check.
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import applications as A  # noqa: E402
import tracker_digest as D  # noqa: E402
from send_digest import CONFIG_PATH, _config_field  # noqa: E402

_text = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.is_file() else ""
SHEET_LINK = _config_field(_text, "Sheet link")
WEB_APP = _config_field(_text, "Sheet web app")
HASH_FILE = Path(__file__).resolve().parent / "state" / "tracker" / "sheet.sha256"

ORDER = D.SECTIONS + ["rejected", "withdrawn"]
PHASE_BG = {
    "interviewing": "#d9ead3", "offer": "#ffe599", "acknowledged": "#d0e0e3", "applied": "#cfe2f3",
    "prepared": "#eeeeee", "ghosted": "#fce5cd", "rejected": "#f4cccc", "withdrawn": "#d9d9d9",
}
HEAD_BG, CLOSED_BG, WHITE = "#eef5f6", "#f3f3f3", "#ffffff"
APP_HEAD = ["Phase", "Company", "Role", "Applied", "Last heard", "Days quiet", "Latest", "Summary"]
TL_HEAD = ["Date", "Company", "Role", "Event", "Note"]


def _safe(s: str) -> str:
    """Stop data text from being read as a formula."""
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


def _role(app: dict) -> str:
    role = app.get("role") or ""
    url = app.get("job_url")
    if not url:
        return _safe(role) if role else "(role not stated)"
    q = lambda s: s.replace('"', '""')  # noqa: E731
    return f'=HYPERLINK("{q(url)}","{q(role or "(role not stated)")}")'


def _latest(app: dict) -> str:
    ev = next((x for x in reversed(app["events"]) if x["type"] != "prepared"), None)
    return _safe(ev.get("note") or D.PHRASE[ev["type"]]) if ev else ""


def _applications(apps: list[dict], today: date) -> dict:
    rows = []
    for app in apps:
        st = A.status(app, today)
        last = A.last_event(app)
        applied = next((x["date"] for x in app["events"] if x["type"] == "applied"), "")
        d = A.days_since(app, today)
        rows.append((st, last["date"] if last else "", [
            st.capitalize(), _safe(app["company"]), _role(app), applied, last["date"] if last else "",
            d if d is not None else "", _latest(app), _safe(D._summary(app)),
        ]))
    rows.sort(key=lambda r: r[1], reverse=True)  # newest first, then stable phase order
    rows.sort(key=lambda r: ORDER.index(r[0]))
    values, bgs = [APP_HEAD], [[HEAD_BG] * len(APP_HEAD)]
    for st, _, row in rows:
        closed = st in A.CLOSED
        bg = [CLOSED_BG if closed else WHITE] * len(row)
        bg[0] = PHASE_BG[st]
        if not closed and row[5] != "":
            bg[5] = D.age_hex(row[5], l=0.85, s=0.7)
        values.append(row)
        bgs.append(bg)
    return {"values": values, "backgrounds": bgs}


def _timeline(apps: list[dict]) -> dict:
    rows = [[x["date"], _safe(a["company"]), _role(a), D.PHRASE[x["type"]], _safe(x.get("note") or "")]
            for a in apps for x in reversed(a["events"])]
    rows.sort(key=lambda r: r[0], reverse=True)
    return {"values": [TL_HEAD] + rows}


def tabs(apps: list[dict], today: date) -> dict:
    return {"Applications": _applications(apps, today), "Timeline": _timeline(apps)}


def push(apps: list[dict], today: date, force: bool = False, hash_file: Path = HASH_FILE) -> bool:
    if WEB_APP is None:
        return False
    body = json.dumps({"tabs": tabs(apps, today)}, ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    hash_file = Path(hash_file)
    # Hashing the rendered rows: pushes on a data change, and once a day as Days quiet ticks.
    if not force and hash_file.exists() and hash_file.read_text().strip() == digest:
        return False
    req = urllib.request.Request(WEB_APP, data=body, headers={"Content-Type": "application/json"})
    # ponytail: Apps Script's 302 -> GET is followed by urllib's default redirect handling.
    with urllib.request.urlopen(req, timeout=60) as resp:
        out = resp.read().decode("utf-8", "replace").strip()
    if out != "ok":
        raise RuntimeError(out[:200])
    hash_file.parent.mkdir(parents=True, exist_ok=True)
    hash_file.write_text(digest)
    return True


if __name__ == "__main__":
    if WEB_APP is None:
        print("Set '- **Sheet web app:** <the /exec URL>' in config.md (see job_scanner/README.md, Tracker sheet).")
        sys.exit(1)
    apps = A.load()
    push(apps, date.today(), force=True)
    print(f"pushed {len(apps)} applications to the sheet")
