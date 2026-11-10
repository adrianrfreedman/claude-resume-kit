#!/usr/bin/env python3
"""
Email a finished job-application package to the candidate.

Attachments are auto-collected from <package_folder>:
  "<Name> - CV - <Company>.pdf", "<Name> - CL - <Company>.pdf" (required; Name from
  config.md; a bare "<Name> - CV.pdf" is the fallback),
  e2e_*_cover_letter.txt and interview_prep_*.html (optional, all matches).

Reuses the Gmail SMTP config and Keychain password from send_digest.py.

Usage:
    python3 send_package.py <package_folder> --subject "..." --body body.txt
        [--html body.html] [--reply reply.md] [--dry-run]
        [--company C --role R [--job-url URL]]

--reply <file> (written by fetch_replies.py) threads the email as a reply:
sets In-Reply-To / References from its front matter and prefixes "Re: ".

--company and --role record the package in the application tracker as
"prepared" after a successful real send (not --dry-run, not --reply).

Exit codes:
    0  success (or dry-run)
    1  package folder / required PDF / body / reply file missing (or no message_id)
    2  keychain lookup failed
    3  SMTP error
"""

from __future__ import annotations

import argparse
import email.utils
import mimetypes
import re
import smtplib
import sys
from email.message import EmailMessage
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import applications  # noqa: E402
from send_digest import (  # noqa: E402
    FROM_HEADER,
    LIST_ID,
    NAME,
    RECIPIENTS_CC,
    REPLY_TO,
    RECIPIENTS_TO,
    SENDER,
    SMTP_HOST,
    SMTP_PORT,
    keychain_password,
    tagged_msgid,
)


def pick_required(folder: Path, kind: str) -> Path:
    """The single "<Name> - <kind> - *.pdf", else "<Name> - <kind>.pdf"; exit 1 if none or ambiguous."""
    found = sorted(folder.glob(f"{NAME} - {kind} - *.pdf"))
    if len(found) > 1:
        sys.stderr.write(f"More than one {kind} in {folder}: {', '.join(f.name for f in found)}\n")
        sys.exit(1)
    if found:
        return found[0]
    bare = folder / f"{NAME} - {kind}.pdf"
    if bare.is_file():
        return bare
    sys.stderr.write(f"Missing required file in {folder}: {NAME} - {kind} - <Company>.pdf\n")
    sys.exit(1)


def collect_attachments(folder: Path) -> list[Path]:
    if not folder.is_dir():
        sys.stderr.write(f"Package folder not found: {folder}\n")
        sys.exit(1)
    required = [pick_required(folder, "CV"), pick_required(folder, "CL")]
    optional = sorted(folder.glob("e2e_*_cover_letter.txt")) + sorted(folder.glob("interview_prep_*.html"))
    return required + optional


def package_tag(folder: Path) -> str:
    """Stem of the single session_*.md minus 'session_'; else the folder name."""
    sessions = list(folder.glob("session_*.md"))
    if len(sessions) == 1:
        return sessions[0].stem.removeprefix("session_")
    return folder.resolve().name.lower()


def reply_headers(reply: Path) -> dict[str, str] | None:
    """In-Reply-To / References from a fetch_replies.py front matter block."""
    if not reply.is_file():
        sys.stderr.write(f"Reply file not found: {reply}\n")
        return None
    text = reply.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    fm = dict(
        ln.split(":", 1) for ln in (m.group(1).splitlines() if m else []) if ":" in ln
    )
    mid = fm.get("message_id", "").strip()
    if not mid:
        sys.stderr.write(f"No message_id in front matter of {reply}\n")
        return None
    refs = " ".join(f"{fm.get('references', '')} {mid}".split())
    return {"In-Reply-To": mid, "References": refs}


def build_message(
    subject: str,
    body: str,
    files: list[Path],
    html: str | None = None,
    headers: dict[str, str] | None = None,
    message_id: str | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = FROM_HEADER
    msg["Reply-To"] = REPLY_TO
    msg["List-Id"] = LIST_ID
    msg["To"] = ", ".join(RECIPIENTS_TO)
    if RECIPIENTS_CC:
        msg["Cc"] = ", ".join(RECIPIENTS_CC)
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = message_id or tagged_msgid("package", "unknown")
    for k, v in (headers or {}).items():
        msg[k] = v
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    for f in files:
        ctype, _ = mimetypes.guess_type(f.name)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(
            f.read_bytes(), maintype=maintype, subtype=subtype, filename=f.name
        )
    return msg


def record_prepared(apps, package, company, role, job_url, message_id, today):
    """Find or create the app for `package`; add 'prepared' once. Returns the app."""
    app = next((a for a in apps if a.get("package") == package), None)
    if app is None:
        app = applications.create(
            apps, company, role, job_url=job_url, package=package
        )
    if not any(e["type"] == "prepared" for e in app["events"]):
        applications.add_event(
            app, today, "prepared", "Package emailed", message_id=message_id
        )
    return app


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", type=Path)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--body", required=True, type=Path)
    ap.add_argument("--html", type=Path, help="HTML email body; --body is the plain-text fallback")
    ap.add_argument("--reply", type=Path, help="reply .md from fetch_replies.py; sends as a threaded reply")
    ap.add_argument("--company", help="with --role: track the package as prepared")
    ap.add_argument("--role")
    ap.add_argument("--job-url")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = collect_attachments(args.folder)
    if not args.body.is_file():
        sys.stderr.write(f"Body file not found: {args.body}\n")
        return 1
    body = args.body.read_text(encoding="utf-8").strip()
    if args.html and not args.html.is_file():
        sys.stderr.write(f"HTML body not found: {args.html}\n")
        return 1
    html = args.html.read_text(encoding="utf-8") if args.html else None
    cc = ", ".join(RECIPIENTS_CC)
    subject, headers = args.subject, None
    if args.reply:
        headers = reply_headers(args.reply)
        if headers is None:
            return 1
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

    message_id = tagged_msgid("package", package_tag(args.folder))

    if args.dry_run:
        print(f"Message-ID: {message_id}")
        print(f"To: {', '.join(RECIPIENTS_TO)}  Cc: {cc}")
        print(f"Subject: {subject}")
        for k, v in (headers or {}).items():
            print(f"{k}: {v}")
        print(f"Body: plain text{' + HTML (' + args.html.name + ')' if html else ''}")
        for f in files:
            print(f"  attach: {f.name} ({f.stat().st_size:,} bytes)")
        print("Dry run: nothing sent.")
        return 0

    msg = build_message(subject, body, files, html, headers, message_id)
    password = keychain_password()
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(SENDER, password)
            smtp.send_message(
                msg, from_addr=SENDER, to_addrs=RECIPIENTS_TO + RECIPIENTS_CC
            )
    except (smtplib.SMTPException, OSError) as exc:
        sys.stderr.write(f"SMTP send failed: {exc}\n")
        return 3
    print(f"Emailed {len(files)} files to {', '.join(RECIPIENTS_TO)} (cc: {cc})")
    if args.company and args.role and not args.reply:
        kit = Path(__file__).resolve().parent.parent
        try:
            package = str(args.folder.resolve().relative_to(kit))
        except ValueError:
            package = str(args.folder)
        try:
            apps = applications.load()
            app = record_prepared(
                apps, package, args.company, args.role, args.job_url,
                message_id, date.today().isoformat(),
            )
            applications.save(apps)
            print(f"Tracked: {app['id']} (prepared)")
        except Exception as exc:  # the email already went
            sys.stderr.write(f"Warning: tracker not updated: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
