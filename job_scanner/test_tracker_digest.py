import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tracker_digest as D

TODAY = date(2026, 10, 19)
SINCE = datetime(2026, 10, 18, 9, 0)
OLD, NEW = "2026-10-17T10:00:00", "2026-10-19T07:00:00"


def ev(date_, type_, note="", recorded=OLD):
    e = {"date": date_, "type": type_, "note": note, "message_id": None}
    if recorded:
        e["recorded"] = recorded
    return e


def app(co, events, role="Analyst", **kw):
    return {"id": co.lower(), "company": co, "role": role, "events": events, **kw}


def render(apps, ledger=None, since=SINCE):
    return D.render(apps, TODAY, since, ledger or {})


def heads(html):
    import re
    return re.findall(r">(Interviewing|Offer|Acknowledged|Applied|Prepared|Ghosted) <span", html)


class TestSections:
    def test_order_and_omission(self):
        apps = [
            app("A", [ev("2026-10-10", "applied")]),
            app("B", [ev("2026-10-10", "interviewing")]),
            app("C", [ev("2026-10-10", "prepared")]),
            app("D", [ev("2026-08-01", "applied")]),  # ghosted
            app("E", [ev("2026-10-10", "acknowledged")]),
        ]
        _, html, _ = render(apps)
        assert heads(html) == ["Interviewing", "Acknowledged", "Applied", "Prepared", "Ghosted"]

    def test_newest_first_then_company(self):
        apps = [
            app("Zed", [ev("2026-10-15", "applied")]),
            app("Old", [ev("2026-10-01", "applied")]),
            app("Abe", [ev("2026-10-15", "applied")]),
            app("Fresh", [ev("2026-10-18", "applied")]),
        ]
        _, html, _ = render(apps)
        pos = [html.index(f">{c}, ") for c in ("Fresh", "Abe", "Zed", "Old")]
        assert pos == sorted(pos)

    def test_ghosted_placement_and_red_tint(self):
        _, html, text = render([app("Stale", [ev("2026-08-01", "applied")])])
        assert heads(html) == ["Ghosted"]
        assert D.age_hex(80, l=0.93) in html and "Ghosted (1)" in text

    def test_prepared_shows_package_tag(self):
        a = app("OurCrowd", [ev("2026-10-18", "prepared", "Package emailed")], package="output/OurCrowd")
        _, html, text = render([a])
        assert "Package: output/OurCrowd" in html and "[package: output/OurCrowd]" in text

    def test_summary_fallback(self):
        a = app("X", [ev("2026-10-18", "applied", "from note")])
        assert "from note" in render([a])[1]
        a["summary"] = "generated line"
        html = render([a])[1]
        assert "generated line" in html and "from note" not in html


class TestNew:
    def test_new_detected_by_recorded(self):
        apps = [
            app("Fresh", [ev("2026-10-10", "applied"), ev("2026-10-19", "interviewing", "2nd interview", NEW)],
                scan_id="s"),
            app("Quiet", [ev("2026-10-10", "applied")], scan_id="s2"),
        ]
        subj, html, _ = render(apps)
        assert html.count("New today") == 1
        assert "Fresh: interview, 2nd interview." in html
        assert subj.endswith(": 1 update")

    def test_old_events_without_recorded_are_old(self):
        a = app("Legacy", [ev("2026-10-18", "applied", recorded=None)])
        subj, html, _ = render([a])
        assert "New today" not in html and subj.endswith("no new updates")
        assert "No news since the last digest." in html

    def test_forwarded_new_app(self):
        a = app("Acme", [ev("2026-10-19", "applied", "", NEW), ev("2026-10-19", "acknowledged", "", NEW)])
        _, html, _ = render([a])
        assert "Acme: new, from a forwarded email (application received)." in html
        assert "New, from a forwarded email" in html

    def test_subject_plural_and_order(self):
        apps = [app("B", [ev("2026-10-19", "applied", "", "2026-10-19T08:00:00")], scan_id="x"),
                app("A", [ev("2026-10-19", "interviewing", "", "2026-10-19T07:00:00")], scan_id="y")]
        subj, html, _ = render(apps)
        assert subj == "Your applications, Mon 19 Oct: 2 updates"
        assert html.index("A: interview.") < html.index("B: applied.")


class TestClosed:
    def test_closed_recent_shown_old_dropped(self):
        apps = [
            app("Recent", [ev("2026-10-05", "applied"), ev("2026-10-14", "rejected")]),
            app("Ancient", [ev("2026-08-01", "applied"), ev("2026-08-20", "rejected")]),
        ]
        _, html, text = render(apps)
        assert "Closed: Recent (rejected 14 Oct)" in html
        assert "Ancient" not in html and "Ancient" not in text

    def test_closed_not_in_sections(self):
        _, html, _ = render([app("Gone", [ev("2026-10-14", "withdrawn")])])
        assert heads(html) == []


class TestLedger:
    LEDGER = {
        "<1>": {"status": "unusable", "subject": "Fwd: LinkedIn alerts", "time": NEW},
        "<2>": {"status": "unusable", "subject": "Too old", "time": "2026-10-01T10:00:00"},
        "<3>": {"status": "done", "kind": "package", "intent": "edits", "package": "output/OurCrowd", "time": NEW},
        "<4>": {"status": "done", "kind": "package", "intent": "applied", "package": "output/Other", "time": NEW},
    }

    def test_unusable_and_revised(self):
        a = app("OurCrowd", [ev("2026-10-18", "prepared")], package="output/OurCrowd")
        _, html, text = render([a], self.LEDGER)
        assert "Fwd: LinkedIn alerts" in html and "Too old" not in html
        assert "OurCrowd: updated from your edits; the new files are in that email thread." in html
        assert "output/Other" not in html and "Other: updated" not in text


class TestLabelsAndStyle:
    def test_days_label(self):
        assert [D.days_label(n) for n in (0, 1, 18)] == ["today", "1 day", "18 days"]

    def test_row_units(self):
        apps = [app("Zero", [ev("2026-10-19", "applied")]), app("One", [ev("2026-10-18", "applied")]),
                app("Many", [ev("2026-10-01", "applied")])]
        _, html, _ = render(apps)
        assert ">today</div>" in html and ">day</div>" in html and ">days</div>" in html
        assert ">18</div>" in html

    def test_no_forbidden_patterns(self):
        a = app("X", [ev("2026-10-19", "interviewing", "note", NEW)])
        _, html, text = render([a], TestLedger.LEDGER)
        for bad in ("·", "→", "&middot;", "&rarr;", "text-transform:uppercase", "monospace", "class="):
            assert bad not in html

    def test_text_mirrors(self):
        a = app("Navina", [ev("2026-10-19", "applied", "Applied", NEW)], role="Manager", scan_id="s")
        _, _, text = render([a])
        assert "- Navina, Manager (today): Applied [new today]" in text
        assert "How to use this" in text


class TestCompactRows:
    @staticmethod
    def seven():
        return [app(f"Co{i}", [ev(f"2026-10-{18 - i:02d}", "applied", "", OLD)], summary=f"sum{i}") for i in range(7)]

    def test_whats_new_bullets(self):
        a = app("Fresh", [ev("2026-10-19", "interviewing", "2nd", NEW)], scan_id="s")
        _, html, text = render([a])
        assert html.count("<li style=\"padding:0 0 4px;") == 1 and "<ul style=\"margin:0;padding:0 0 0 18px;\">" in html
        assert "- Fresh: interview, 2nd." in text

    def test_no_news_is_paragraph(self):
        _, html, text = render([app("Q", [ev("2026-10-10", "applied")], scan_id="s")])
        assert '<p style="margin:0;font-size:15px;line-height:1.5;color:#1d2a2e;">No news since the last digest.</p>' in html
        assert "\nNo news since the last digest.\n" in text

    def test_seven_apps_five_full_two_details(self):
        _, html, text = render(self.seven())
        assert html.count("<details>") == 2 + 1  # +1 for "How to use this"
        assert html.count("font-size:26px;font-weight:bold") == 5
        assert text.count(", Analyst (") == 7

    def test_compact_company_once_in_summary(self):
        _, html, _ = render(self.seven())
        assert html.count("Co6, Analyst") == 1
        i = html.index("Co6, Analyst")
        assert html.rindex("<summary", 0, i) > html.rindex("</summary>", 0, i)  # inside open summary
        assert html[i:].index("</summary>") < html[i:].index("</details>")

    def test_compact_without_detail_has_no_details(self):
        apps = [app(f"Co{i}", [ev(f"2026-10-{18 - i:02d}", "applied", "", OLD)]) for i in range(6)]
        _, html, _ = render(apps)
        assert html.count("<details>") == 1  # only "How to use this"
        assert "Co5, Analyst" in html
