#!/usr/bin/env python3
"""
Send today's job-digest Markdown via Gmail SMTP.

The Gmail app password is read from the macOS Keychain so it never appears
on disk or in env vars.

Usage:
    python3 send_digest.py [<digest_path>]

If <digest_path> is omitted, defaults to digests/digest_<today>.md
relative to this script.

Exit codes:
    0  sent successfully
    1  digest file missing
    2  keychain lookup failed
    3  SMTP error
"""

from __future__ import annotations

import datetime as _dt
import email.utils
import re
import smtplib
import subprocess
import sys
from email.message import EmailMessage
from pathlib import Path

# ---------------------------------------------------------------------------
# Config — candidate and mail account come from config.md at the kit root.
# ---------------------------------------------------------------------------
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.md"


def _config_field(text: str, label: str) -> str | None:
    m = re.search(rf"^- \*\*{label}:\*\*[ \t]*(\S.*?)[ \t]*$", text, re.MULTILINE)
    return m.group(1) if m else None


def mail_identity(config_path: Path) -> dict:
    """Candidate, sender, alias, keychain service and header names derived from config.md."""
    if not config_path.is_file():
        raise SystemExit(f"config.md not found at {config_path}")
    text = config_path.read_text(encoding="utf-8")
    name, to = _config_field(text, "Name"), _config_field(text, "Email")
    if not name or not to:
        raise SystemExit(f"config.md ({config_path}) needs '- **Name:**' and '- **Email:**' lines")
    sender = _config_field(text, "Sender")
    if not sender:
        raise SystemExit(f"config.md ({config_path}) needs a '- **Sender:**' line (Mail section)")
    sender = sender.lower()
    service = _config_field(text, "Keychain service") or "job-scanner-gmail"
    local, domain = sender.split("@", 1)
    # ponytail: the tracker alias is derived (plus-addressing), not configured.
    alias = f"{local}+jobs@{domain}"
    first = name.split()[0]
    cc = [sender] if to.lower() != sender else []
    return {
        "to": [to],
        "cc": cc,
        # Replies land on the tracker alias; Gmail keeps the display name but rewrites an unverified From.
        "reply_to": alias if cc else sender,
        "from_header": f"{first} job tracker <{sender}>",
        "list_id": f"<{first.lower()}-job-tracker>",  # Gmail filter: list:<first>-job-tracker
        "first": first,
        "name": name,
        "sender": sender,
        "alias": alias,
        "keychain_service": service,
        # Message-ID domain; each candidate's tracker only recognises replies to its own mail.
        "domain": f"{first.lower()}-job-scanner.local",
    }


_ID = mail_identity(CONFIG_PATH)
RECIPIENTS_TO = _ID["to"]
RECIPIENTS_CC = _ID["cc"]
REPLY_TO = _ID["reply_to"]
FROM_HEADER = _ID["from_header"]
LIST_ID = _ID["list_id"]
FIRST = _ID["first"]
NAME = _ID["name"]
SENDER = _ID["sender"]
ALIAS = _ID["alias"]
KEYCHAIN_SERVICE = _ID["keychain_service"]
DOMAIN = _ID["domain"]

# The keychain item holds the sender's app password.
KEYCHAIN_ACCOUNT = SENDER

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def tagged_msgid(kind: str, tag: str) -> str:
    """<{kind}-{tag}.{timestamp}@domain>; the timestamp keeps each send unique."""
    tag = re.sub(r"[^a-z0-9_-]", "_", tag.lower())
    ts = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    return f"<{kind}-{tag}.{ts}@{DOMAIN}>"


def keychain_password() -> str:
    """Fetch the Gmail app password from macOS Keychain."""
    try:
        out = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-a",
                KEYCHAIN_ACCOUNT,
                "-s",
                KEYCHAIN_SERVICE,
                "-w",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(
            f"Keychain lookup failed for service={KEYCHAIN_SERVICE} "
            f"account={KEYCHAIN_ACCOUNT}: {exc.stderr.strip()}\n"
            "Did you run the one-time `security add-generic-password ...` setup?\n"
        )
        sys.exit(2)
    return out.stdout.strip()


def resolve_digest(arg: str | None) -> Path:
    here = Path(__file__).resolve().parent
    if arg:
        p = Path(arg).expanduser()
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
    else:
        today = _dt.date.today().isoformat()
        p = here / "digests" / f"digest_{today}.md"
    if not p.exists():
        sys.stderr.write(f"Digest file not found: {p}\n")
        sys.exit(1)
    return p


_TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_MATCHES_RE = re.compile(r"Matches \(≥?50\)?:?\*{0,2}\s*(\d+)", re.IGNORECASE)
_TOP_SCORE_RE = re.compile(r"score\s+(\d+)\s*/\s*100", re.IGNORECASE)


def build_subject(digest_md: str, fallback_date: str) -> str:
    title_match = _TITLE_RE.search(digest_md)
    title = title_match.group(1).strip() if title_match else f"Job digest {fallback_date}"
    n_matches_match = _MATCHES_RE.search(digest_md)
    n_matches = n_matches_match.group(1) if n_matches_match else "?"
    top_scores = [int(m.group(1)) for m in _TOP_SCORE_RE.finditer(digest_md)]
    top = max(top_scores) if top_scores else None
    if top is not None:
        return f"{title} — {n_matches} matches (top: {top})"
    return f"{title} — {n_matches} matches"


def md_to_basic_html(md: str) -> str:
    """Minimal Markdown -> HTML for readable email clients.

    Handles: h1/h2/h3, bullet lists, links, bold, code spans, paragraphs,
    horizontal rules. Not a full converter; intentionally conservative.
    """
    lines = md.splitlines()
    html: list[str] = []
    in_list = False

    def flush_list() -> None:
        nonlocal in_list
        if in_list:
            html.append("</ul>")
            in_list = False

    def inline(s: str) -> str:
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        return s

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            flush_list()
            html.append("")
            continue
        if line.startswith("### "):
            flush_list()
            html.append(f"<h3>{inline(line[4:])}</h3>")
            continue
        if line.startswith("## "):
            flush_list()
            html.append(f"<h2>{inline(line[3:])}</h2>")
            continue
        if line.startswith("# "):
            flush_list()
            html.append(f"<h1>{inline(line[2:])}</h1>")
            continue
        if line.strip() in ("---", "***"):
            flush_list()
            html.append("<hr>")
            continue
        if line.lstrip().startswith("- "):
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"<li>{inline(line.lstrip()[2:])}</li>")
            continue
        flush_list()
        html.append(f"<p>{inline(line)}</p>")
    flush_list()

    return (
        "<html><body style=\"font-family: -apple-system, BlinkMacSystemFont, "
        "'Helvetica Neue', sans-serif; font-size: 14px; line-height: 1.5;\">"
        + "\n".join(html)
        + "</body></html>"
    )


def main(argv: list[str]) -> int:
    digest_path = resolve_digest(argv[1] if len(argv) > 1 else None)
    digest_md = digest_path.read_text(encoding="utf-8")

    today_iso = _dt.date.today().isoformat()
    subject = build_subject(digest_md, today_iso)
    html_body = md_to_basic_html(digest_md)

    msg = EmailMessage()
    msg["From"] = FROM_HEADER
    msg["Reply-To"] = REPLY_TO
    msg["List-Id"] = LIST_ID
    msg["To"] = ", ".join(RECIPIENTS_TO)
    if RECIPIENTS_CC:
        msg["Cc"] = ", ".join(RECIPIENTS_CC)
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    tag = digest_path.stem.removeprefix("digest_")
    msg["Message-ID"] = tagged_msgid("scan", tag)
    msg.set_content(digest_md)
    msg.add_alternative(html_body, subtype="html")

    password = keychain_password()
    all_recipients = RECIPIENTS_TO + RECIPIENTS_CC

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(SENDER, password)
            smtp.send_message(msg, from_addr=SENDER, to_addrs=all_recipients)
    except (smtplib.SMTPException, OSError) as exc:
        sys.stderr.write(f"SMTP send failed: {exc}\n")
        return 3

    sys.stdout.write(
        f"Sent digest {digest_path.name} to {', '.join(RECIPIENTS_TO)} "
        f"(cc: {', '.join(RECIPIENTS_CC)})\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
