"""mail_identity: recipient, CC and header names derived from config.md."""

import pytest

from send_digest import mail_identity

SENDER = "sender@example.com"


def write_config(tmp_path, name, email, sender=SENDER, service=None):
    p = tmp_path / "config.md"
    lines = f"## Personal Info\n\n- **Name:** {name}\n- **Degree suffix:** Ph.D.\n- **Email:** {email}\n"
    if sender:
        lines += f"\n## Mail\n\n- **Sender:** {sender}\n"
    if service:
        lines += f"- **Keychain service:** {service}\n"
    p.write_text(lines, encoding="utf-8")
    return p


class TestConfigRecipients:
    def test_other_recipient_gets_sender_cc_and_alias(self, tmp_path):
        ident = mail_identity(write_config(tmp_path, "Jane Doe", "jane@example.com"))
        assert ident["to"] == ["jane@example.com"]
        assert ident["cc"] == [SENDER]
        assert ident["from_header"] == f"Jane job tracker <{SENDER}>"
        assert ident["list_id"] == "<jane-job-tracker>"
        assert ident["reply_to"] == "sender+jobs@example.com"

    def test_sender_as_recipient_has_no_cc_and_replies_to_sender(self, tmp_path):
        ident = mail_identity(write_config(tmp_path, "Sam Smith", SENDER))
        assert ident["to"] == [SENDER]
        assert ident["cc"] == []
        assert ident["reply_to"] == SENDER
        assert ident["from_header"] == f"Sam job tracker <{SENDER}>"
        assert ident["list_id"] == "<sam-job-tracker>"

    def test_missing_config_exits(self, tmp_path):
        with pytest.raises(SystemExit, match="config.md not found"):
            mail_identity(tmp_path / "config.md")

    def test_missing_email_exits(self, tmp_path):
        p = tmp_path / "config.md"
        p.write_text("- **Name:** Someone Else\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="Email"):
            mail_identity(p)


class TestMailSection:
    def test_missing_sender_exits(self, tmp_path):
        with pytest.raises(SystemExit, match="Sender"):
            mail_identity(write_config(tmp_path, "Jane Doe", "jane@example.com", sender=None))

    def test_keychain_service_defaults(self, tmp_path):
        ident = mail_identity(write_config(tmp_path, "Jane Doe", "jane@example.com"))
        assert ident["keychain_service"] == "job-scanner-gmail"

    def test_keychain_service_from_config(self, tmp_path):
        ident = mail_identity(write_config(tmp_path, "Jane Doe", "jane@example.com", service="my-svc"))
        assert ident["keychain_service"] == "my-svc"

    def test_alias_and_sender_derived(self, tmp_path):
        ident = mail_identity(write_config(tmp_path, "Jane Doe", "jane@example.com", sender="Some.One@Example.org"))
        assert ident["sender"] == "some.one@example.org"
        assert ident["alias"] == "some.one+jobs@example.org"
        assert ident["name"] == "Jane Doe"
