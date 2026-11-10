"""Application tracker store: state/applications.json, a JSON list of application dicts.

Application: {id, company, role, [job_url, scan_id, package, summary], events: [...]}
Event: {date, type, note, message_id, recorded}  (recorded = local ISO time added; absent on old events;
auto = true on applied events the tracker inserted itself; their date may move earlier)
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from datetime import date, datetime
from pathlib import Path

PATH = Path(__file__).resolve().parent / "state" / "applications.json"

EVENT_TYPES = {
    "prepared", "applied", "acknowledged", "interviewing",
    "offer", "rejected", "withdrawn", "note",
}
CLOSED = {"rejected", "withdrawn"}
GHOSTABLE = {"applied", "acknowledged", "interviewing"}
GHOST_DAYS = 30
CLOCK = datetime.now  # tests replace this


def load(path=PATH) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save(apps: list[dict], path=PATH) -> None:
    """Atomic: temp file in the same dir, then os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(apps, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def make_id(company: str, role: str, apps: list[dict]) -> str:
    text = unicodedata.normalize("NFKD", f"{company} {role}").encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) > 60:  # cut at a word boundary, not mid-word
        slug = slug[:61].rsplit("-", 1)[0]
    slug = slug or "application"
    taken = {a["id"] for a in apps}
    if slug not in taken:
        return slug
    n = 2
    while f"{slug}-{n}" in taken:
        n += 1
    return f"{slug}-{n}"


def who(company: str, role: str, sep: str = ", ") -> str:
    """Company and role for display; an empty role reads "<Company> (role not stated)"."""
    return f"{company}{sep}{role}" if role else f"{company} (role not stated)"


def find(apps: list[dict], app_id: str) -> dict | None:
    return next((a for a in apps if a["id"] == app_id), None)


def create(apps: list[dict], company: str, role: str, **fields) -> dict:
    app = {"id": make_id(company, role, apps), "company": company, "role": role}
    app.update({k: v for k, v in fields.items() if v is not None})
    app["events"] = []
    apps.append(app)
    return app


def add_event(app: dict, date: str, type: str, note: str = "", message_id: str | None = None, auto: bool = False) -> bool:
    if type not in EVENT_TYPES:
        raise ValueError(f"unknown event type: {type!r}")
    if message_id and any(
        e.get("message_id") == message_id and e["type"] == type for e in app["events"]
    ):
        return False
    app["events"].append({
        "date": date, "type": type, "note": note, "message_id": message_id,
        "recorded": CLOCK().isoformat(timespec="seconds"),
    })
    if auto:
        app["events"][-1]["auto"] = True
    for e in app["events"]:  # an auto-inserted applied never postdates a later-added event
        if e.get("auto") and e["type"] == "applied" and e["date"] > date:
            e["date"] = date
    app["events"].sort(key=lambda e: (e["date"], e["type"] != "applied"))  # stable; applied first on a tie
    app.pop("summary", None)
    return True


def last_event(app: dict) -> dict | None:
    return app["events"][-1] if app["events"] else None


def days_since(app: dict, today: date) -> int | None:
    e = last_event(app)
    return (today - date.fromisoformat(e["date"])).days if e else None


def status(app: dict, today: date) -> str:
    types = [e["type"] for e in app["events"] if e["type"] != "note"]
    # same-day sort puts "applied" before "prepared"; prepared never outranks applied
    base = next((t for t in reversed(types) if t != "prepared" or "applied" not in types), "prepared")
    if base in GHOSTABLE and days_since(app, today) >= GHOST_DAYS:
        return "ghosted"
    return base
