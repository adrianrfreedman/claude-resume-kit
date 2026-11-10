#!/usr/bin/env python3
"""
Fetch the candidate's email replies to a sent application package.

Searches Gmail "All Mail" (IMAP, read-only) for messages FROM the candidate whose
subject contains --subject (so "Re: <subject>" matches). Each new reply is
saved to <package_folder>/replies/ as reply_<YYYYmmdd-HHMM>.md (front matter
+ plain-text body with quoted text removed); attachments are saved beside it
as <stem>_<filename>. Already-fetched replies (same Message-ID) are skipped.

Reuses SENDER and the Keychain password from send_digest.py.

Usage:
    python3 fetch_replies.py <package_folder> --subject "Application package: ..."
        [--since YYYY-MM-DD]

Exit codes:
    0  success (including "No new replies.")
    1  package folder missing
    2  keychain lookup failed
    3  IMAP error
"""

from __future__ import annotations

import argparse
import datetime as _dt
import email
import email.policy
import email.utils
import html
import imaplib
import re
import sys
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from send_digest import RECIPIENTS_TO, SENDER, keychain_password  # noqa: E402

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
MAILBOX = '"[Gmail]/All Mail"'
CANDIDATE = RECIPIENTS_TO[0]

_ON_WROTE = re.compile(r"^On .+wrote:$")


def strip_quoted(text: str) -> str:
    """Drop '>' lines and cut at Gmail's 'On ... wrote:' header (may wrap over two lines)."""
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith(">")]
    for i, ln in enumerate(lines):
        s = ln.strip()
        if _ON_WROTE.match(s) or (
            s.startswith("On ") and i + 1 < len(lines) and lines[i + 1].strip().endswith("wrote:")
        ):
            lines = lines[:i]
            break
    return "\n".join(ln.rstrip() for ln in lines).strip()


def body_text(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    content = part.get_content()
    if part.get_content_type() == "text/html":
        content = html.unescape(re.sub(r"<[^>]+>", "", content))
    return strip_quoted(content)


def stem_for(msg: EmailMessage) -> str:
    try:
        dt = email.utils.parsedate_to_datetime(msg["Date"]).astimezone()
    except (TypeError, ValueError):
        dt = _dt.datetime.now()
    return f"reply_{dt:%Y%m%d-%H%M}"


def unique_stem(out: Path, stem: str, mid: str) -> str | None:
    """Return a free stem, or None if this Message-ID was already saved."""
    n, cand = 1, stem
    while (out / f"{cand}.md").exists():
        if f"message_id: {mid}\n" in (out / f"{cand}.md").read_text(encoding="utf-8"):
            return None
        n += 1
        cand = f"{stem}_{n}"
    return cand


def save_reply(msg: EmailMessage, out: Path) -> tuple[Path, int] | None:
    mid = (msg["Message-ID"] or "").strip()
    stem = unique_stem(out, stem_for(msg), mid)
    if stem is None:
        return None
    refs = " ".join((msg["References"] or "").split())
    front = (
        f"---\nfrom: {msg['From']}\ndate: {msg['Date']}\nsubject: {msg['Subject']}\n"
        f"message_id: {mid}\nreferences: {refs}\n---\n\n"
    )
    path = out / f"{stem}.md"
    path.write_text(front + body_text(msg) + "\n", encoding="utf-8")
    count = 0
    for att in msg.iter_attachments():
        name = re.sub(r"[^A-Za-z0-9._ -]", "_", att.get_filename() or "attachment")
        (out / f"{stem}_{name}").write_bytes(att.get_payload(decode=True) or b"")
        count += 1
    return path, count


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", type=Path)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--since", help="YYYY-MM-DD")
    args = ap.parse_args()

    if not args.folder.is_dir():
        sys.stderr.write(f"Package folder not found: {args.folder}\n")
        return 1
    crit = ["FROM", f'"{CANDIDATE}"', "SUBJECT", '"' + args.subject.replace('"', "") + '"']
    if args.since:
        d = _dt.date.fromisoformat(args.since)
        crit += ["SINCE", f"{d.day:02d}-{d.strftime('%b')}-{d.year}"]

    password = keychain_password()
    raws: list[bytes] = []
    try:
        imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        try:
            imap.login(SENDER, password)
            imap.select(MAILBOX, readonly=True)
            _, data = imap.search(None, *crit)
            for num in data[0].split():
                _, parts = imap.fetch(num, "(BODY.PEEK[])")
                raws.append(parts[0][1])
        finally:
            try:
                imap.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
    except (imaplib.IMAP4.error, OSError) as exc:
        sys.stderr.write(f"IMAP failed: {exc}\n")
        return 3

    out = args.folder / "replies"
    out.mkdir(exist_ok=True)
    new = 0
    for raw in raws:
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        saved = save_reply(msg, out)
        if saved:
            new += 1
            print(f"{saved[0]}  ({saved[1]} attachment(s))")
    if not new:
        print("No new replies.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
