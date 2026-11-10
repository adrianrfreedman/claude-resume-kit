"""prefetch: parsing, dedupe, stripping, deadline. No network."""

import json
import time
from pathlib import Path

import prefetch
from _dedupe import h, load_seen

LI_HTML = """
<ul>
<li><div class="base-card relative">
  <a class="base-card__full-link UNDERLINE_ON_HOVER" href="https://il.linkedin.com/jobs/view/medical-advisor-at-abbvie-4408677709?position=1&amp;pageNum=0&amp;trk=public_jobs_jserp">
    <span class="sr-only">Medical Advisor</span></a>
  <div class="base-search-card__info">
    <h3 class="base-search-card__title">
      Medical Advisor, Oncology
    </h3>
    <h4 class="base-search-card__subtitle">
      <a class="hidden-nested-link" href="https://il.linkedin.com/company/abbvie?trk=x">AbbVie</a>
    </h4>
    <div class="base-search-card__metadata">
      <span class="job-search-card__location">Hod Hasharon, Israel</span>
      <time class="job-search-card__listdate" datetime="2026-10-30">2 days ago</time>
    </div>
  </div>
</div></li>
<li><div class="base-card">
  <a class="base-card__full-link" href="https://il.linkedin.com/jobs/view/analyst-at-wix-4400000001">x</a>
  <h3 class="base-search-card__title">Analyst &amp; Researcher</h3>
  <h4 class="base-search-card__subtitle"><a href="#">Wix</a></h4>
  <span class="job-search-card__location">Tel Aviv-Yafo, Israel</span>
  <time datetime="2026-10-31">1 day ago</time>
</div></li>
</ul>
"""


FIX = Path(__file__).parent / "fixtures"
AJ_HTML = (FIX / "alljobs_cards.html").read_text(encoding="utf-8")
DR_HTML = (FIX / "drushim_cards.html").read_text(encoding="utf-8")


def mk(company, title, url, source="s"):
    return prefetch.cand(company, title, "Israel", url, None, source)


class TestLinkedInParse:
    def test_two_cards(self):
        rows = prefetch.parse_linkedin_cards(LI_HTML, "linkedin_il")
        assert len(rows) == 2
        a, b = rows
        assert a["company"] == "AbbVie"
        assert a["title"] == "Medical Advisor, Oncology"
        assert a["location"] == "Hod Hasharon, Israel"
        assert a["posted"] == "2026-10-30"
        assert a["source"] == "linkedin_il"
        assert b["company"] == "Wix"
        assert b["title"] == "Analyst & Researcher"
        assert b["posted"] == "2026-10-31"

    def test_query_string_stripped(self):
        a = prefetch.parse_linkedin_cards(LI_HTML)[0]
        assert a["url"] == "https://il.linkedin.com/jobs/view/medical-advisor-at-abbvie-4408677709"

    def test_empty_page(self):
        assert prefetch.parse_linkedin_cards("<html>login wall</html>") == []


class TestJobId:
    def test_with_query(self):
        assert prefetch.linkedin_job_id("https://il.linkedin.com/jobs/view/x-at-y-4408677709?trk=1") == "4408677709"

    def test_at_end(self):
        assert prefetch.linkedin_job_id("https://il.linkedin.com/jobs/view/x-at-y-4408677709") == "4408677709"

    def test_view_id_only(self):
        assert prefetch.linkedin_job_id("https://www.linkedin.com/jobs/view/4408677709/") == "4408677709"

    def test_none(self):
        assert prefetch.linkedin_job_id("https://example.com/careers/") is None


class TestDedupe:
    def test_marks_and_collapses(self, tmp_path):
        seen = tmp_path / "seen.jsonl"
        seen.write_text("\n".join([
            json.dumps({"url_hash": h("https://a.com/1"), "content_hash": h("x|y")}),
            json.dumps({"url_hash": "other", "content_hash": h("acme|data scientist")}),
        ]) + "\n")
        urls, contents = load_seen(str(seen))
        cands = [
            mk("A", "Seen By Url", "https://a.com/1"),
            mk("Acme", "Data Scientist", "https://acme.com/9"),
            mk("New Co", "Brand New Role", "https://new.com/1"),
            mk("New Co", "Brand New Role", "https://new.com/2"),  # in-run content dup
        ]
        out = prefetch.mark_seen(cands, urls, contents)
        assert [c["seen"] for c in out] == [True, True, False]
        assert out[2]["url"] == "https://new.com/1"
        assert out[2]["url_hash"] == h("https://new.com/1")
        assert out[2]["content_hash"] == h("New Co|Brand New Role")

    def test_no_dedupe_marks_all_unseen(self):
        urls = {h("https://a.com/1")}
        out = prefetch.mark_seen([mk("A", "T", "https://a.com/1")], urls, set(), dedupe=False)
        assert out[0]["seen"] is False

    def test_legacy_ledger_ids(self, tmp_path):
        seen = tmp_path / "seen.jsonl"
        seen.write_text(json.dumps({
            "url_hash": "li_4485925933", "content_hash": "abbvie|medical advisor",
            "url": "https://il.linkedin.com/jobs/view/medical-advisor-4485925933"}) + "\n\nnot json\n")
        urls, contents, ids = prefetch.load_ledger(seen)
        out = prefetch.mark_seen([
            mk("Other", "Other Title", "https://www.linkedin.com/jobs/view/x-4485925933"),
            mk("AbbVie", "Medical Advisor", "https://z.com/1"),
            mk("Fresh", "Fresh", "https://z.com/2"),
        ], urls, contents, ids)
        assert [c["seen"] for c in out] == [True, True, False]


class TestStrip:
    def test_tags_scripts_entities(self):
        s = "<div>Hi<script>var x=1;</script><style>p{}</style> <b>there</b>&nbsp;&amp; <!-- c -->you</div>"
        assert prefetch.strip_html(s) == "Hi there & you"

    def test_cap(self):
        assert len(prefetch.strip_html("<p>" + "word " * 5000 + "</p>", 6000)) == 6000
        assert len(prefetch.strip_html("a" * 9000)) == 6000


class TestRenderLinks:
    def test_job_like_links(self):
        out = ("=== TITLE ===\nT\n=== LINKS ===\n"
               "https://x.com/careers/\tCareers page\n"
               "https://x.com/co/tel-aviv/1.2/data-analyst/all\tData Analyst Tel Aviv\n"
               "https://x.com/about\tAbout us today\n"
               "https://x.com/job/9\tApply\n"
               "=== TEXT ===\nbody")
        rows = prefetch.parse_render_links(out, "https://x.com/careers/", "X")
        assert [r["title"] for r in rows] == ["Data Analyst Tel Aviv"]


class TestBoardUrl:
    def test_shapes(self):
        aj = {"type": "alljobs", "base_url": "https://aj.test/s", "region_codes": [2, 3]}
        dr = {"type": "drushim", "base_url": "https://dr.test/jobs/search/"}
        assert prefetch.board_url(aj, "a b") == "https://aj.test/s?freetxt=a%20b&region=2,3"
        assert prefetch.board_url(dr, "a b") == "https://dr.test/jobs/search/a%20b/"

    def test_alljobs_nav_trimmed(self):
        raw = "<p>" + "nav " * 200 + "משרה בלעדית לפני 3 שעות MSL Hematology</p>"
        trimmed = prefetch.page_text(raw, "alljobs")
        assert len(trimmed) < 150 and "MSL Hematology" in trimmed
        assert prefetch.page_text(raw, "drushim").startswith("nav nav")


class TestDeadline:
    def test_deadline_zero(self, tmp_path, monkeypatch):
        (tmp_path / "state").mkdir()
        (tmp_path / "sources.yaml").write_text(
            "sources:\n  - id: linkedin_il\n    type: linkedin\n    base_url: x\n    queries: [a, b, c]\n")
        (tmp_path / "companies.yaml").write_text(
            "companies:\n  - name: Foo\n    careers_url: https://foo.com/careers/\n    parser_hint: generic\n")

        def slow_get(url, timeout=20):
            time.sleep(0.5)
            return LI_HTML

        monkeypatch.setattr(prefetch, "get", slow_get)
        out = tmp_path / "out.json"
        t0 = time.monotonic()
        code = prefetch.main(["--out", str(out), "--deadline", "0"], root=tmp_path)
        assert code == 0
        assert time.monotonic() - t0 < 0.4
        data = json.loads(out.read_text())
        assert data["deadline_hit"] is True
        assert data["candidates"] == []
        assert {s["status"] for s in data["sources"]} == {"deadline"}


class TestFullRun:
    def test_stubbed_run(self, tmp_path, monkeypatch):
        (tmp_path / "state").mkdir()
        (tmp_path / "sources.yaml").write_text(
            "sources:\n  - id: linkedin_il\n    type: linkedin\n    base_url: x\n    queries: [a]\n"
            "  - id: alljobs\n    type: alljobs\n    base_url: https://aj.test/s\n    region_codes: [2, 3]\n"
            "    queries_en: [q]\n")
        (tmp_path / "companies.yaml").write_text("companies: []\n")

        def fake_get(url, timeout=20):
            if "seeMoreJobPostings" in url:
                return LI_HTML
            if "jobPosting/4408677709" in url:
                return '<div class="show-more-less-html__markup"><p>Great <b>job</b></p></div>'
            if "jobPosting/" in url:
                raise OSError("boom")
            return "<html><body>listing text</body></html>"

        monkeypatch.setattr(prefetch, "get", fake_get)
        out = tmp_path / "out.json"
        assert prefetch.main(["--out", str(out)], root=tmp_path) == 0
        data = json.loads(out.read_text())
        by = {c["company"]: c for c in data["candidates"]}
        assert by["AbbVie"]["description"] == "Great job"
        assert by["AbbVie"]["description_status"] == "ok"
        assert by["Wix"]["description"] is None
        assert by["Wix"]["description_status"].startswith("error")
        assert data["raw_pages"][0]["text"] == "listing text"
        assert "freetxt=q&region=2,3" in data["raw_pages"][0]["url"]
        assert data["deadline_hit"] is False


class TestTitleTriage:
    def _setup(self, tmp_path, monkeypatch, extra=""):
        (tmp_path / "state").mkdir()
        (tmp_path / "sources.yaml").write_text(
            "sources:\n  - id: linkedin_il\n    type: linkedin\n    base_url: x\n    queries: [a]\n"
            "settings:\n  title_exclude:\n    - account executive\n" + extra)
        (tmp_path / "companies.yaml").write_text("companies: []\n")
        page = (
            '<li><a class="base-card__full-link" href="https://il.linkedin.com/jobs/view/x-4400000001"></a>'
            '<h3 class="base-search-card__title">Senior Account Executive</h3>'
            '<h4 class="base-search-card__subtitle">Foo</h4></li>'
            '<li><a class="base-card__full-link" href="https://il.linkedin.com/jobs/view/y-4400000002"></a>'
            '<h3 class="base-search-card__title">Senior Backend Engineer</h3>'
            '<h4 class="base-search-card__subtitle">Bar</h4></li>')
        fetched = []

        def fake_get(url, timeout=20):
            if "seeMoreJobPostings" in url:
                return page
            fetched.append(url)
            return '<div class="show-more-less-html__markup">Body</div>'

        monkeypatch.setattr(prefetch, "get", fake_get)
        return fetched

    def test_exclude_flags_and_skips_body(self, tmp_path, monkeypatch, capsys):
        fetched = self._setup(tmp_path, monkeypatch)
        out = tmp_path / "out.json"
        assert prefetch.main(["--out", str(out)], root=tmp_path) == 0
        by = {c["title"]: c for c in json.loads(out.read_text())["candidates"]}
        ae, be = by["Senior Account Executive"], by["Senior Backend Engineer"]
        assert ae["triage"] == "title-exclude" and ae["description"] is None
        assert ae["description_status"] == "skipped-title"
        assert be["triage"] == "ok" and be["description"] == "Body"
        assert not any("4400000001" in u for u in fetched)
        assert "1 title-excluded" in capsys.readouterr().out

    def test_excluded_does_not_use_max(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        out = tmp_path / "out.json"
        prefetch.main(["--out", str(out), "--max", "1"], root=tmp_path)
        by = {c["title"]: c for c in json.loads(out.read_text())["candidates"]}
        assert by["Senior Backend Engineer"]["description_status"] == "ok"

    def test_no_setting_all_ok(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        (tmp_path / "sources.yaml").write_text(
            "sources:\n  - id: linkedin_il\n    type: linkedin\n    base_url: x\n    queries: [a]\n")
        out = tmp_path / "out.json"
        prefetch.main(["--out", str(out)], root=tmp_path)
        assert {c["triage"] for c in json.loads(out.read_text())["candidates"]} == {"ok"}


class TestAllJobsParse:
    def test_cards(self):
        rows = prefetch.parse_alljobs_cards(AJ_HTML)  # fixture also holds one closed card
        assert [r["url"] for r in rows] == [
            "https://www.alljobs.co.il/Search/UploadSingle.aspx?JobID=8867495",
            "https://www.alljobs.co.il/Search/UploadSingle.aspx?JobID=8872279"]
        a, b = rows
        assert a["company"] == "ALLSTARSIT"
        assert a["title"] == "לחברה פיננסית במרכז, מפתח /ת backend מנוסה"
        assert a["location"] == "בני ברק"
        assert a["source"] == "alljobs"
        assert b["company"] == "Gtech"
        assert b["location"] == "רחובות, רמלה, ראשון לציון, חולון"

    def test_closed_card_skipped(self):
        assert not any("8828055" in r["url"] for r in prefetch.parse_alljobs_cards(AJ_HTML))

    def test_hidden_company_is_unknown(self):
        page = AJ_HTML.replace('<div class="T14"><a href="/Employer/HP/Default.aspx?cid=74325">ALLSTARSIT</a></div>',
                               '<div class="T14"></div>')
        assert prefetch.parse_alljobs_cards(page)[0]["company"] == "unknown"

    def test_hashes_and_dedupe(self):
        rows = prefetch.mark_seen(prefetch.parse_alljobs_cards(AJ_HTML), set(), set(), ids={"8867495"})
        assert [r["seen"] for r in rows] == [True, False]
        assert rows[0]["url_hash"] and rows[0]["content_hash"]

    def test_no_cards(self):
        assert prefetch.parse_alljobs_cards("<html>nothing</html>") == []


class TestDrushimParse:
    def test_cards(self):
        rows = prefetch.parse_drushim_cards(DR_HTML)
        assert [r["url"] for r in rows] == [
            "https://www.drushim.co.il/job/38605799/5c97e4d5/",
            "https://www.drushim.co.il/job/38855364/98f02415/",
            "https://www.drushim.co.il/job/38756716/ca6d7f1d/"]
        a, b, c = rows
        assert a["company"] == "דאטה וויי - Dataway"
        assert a["title"] == "מפתח/ת BI (Backend & Frontend)"
        assert a["location"] == "באר יעקב"
        assert a["source"] == "drushim"
        assert b["location"] == "גבעתיים, תל אביב"
        assert c["company"] == 'עוז תוכנה בע"מ'
        assert c["location"] == "פתח תקווה, רמת גן, הוד השרון, תל אביב"

    def test_no_cards(self):
        assert prefetch.parse_drushim_cards("<html>nothing</html>") == []


class TestBoardListing:
    def test_cards_drop_raw_page(self):
        rows, page = prefetch.board_listing(AJ_HTML, "alljobs", "alljobs", 25)
        assert len(rows) == 2 and page is None

    def test_cap(self):
        rows, _ = prefetch.board_listing(DR_HTML, "drushim", "drushim", 2)
        assert len(rows) == 2

    def test_raw_fallback_capped(self):
        rows, page = prefetch.board_listing("<p>" + "x " * 5000 + "</p>", "drushim", "drushim", 25)
        assert rows == [] and len(page) == 3000

    def test_full_run_bodies(self, tmp_path, monkeypatch):
        (tmp_path / "state").mkdir()
        (tmp_path / "sources.yaml").write_text(
            "sources:\n  - id: alljobs\n    type: alljobs\n    base_url: https://aj.test/s\n"
            "    queries_en: [q]\n")
        (tmp_path / "companies.yaml").write_text("companies: []\n")
        job = ('<html><nav>MENU</nav><div class="job-content-top-title">T</div>'
               '<div class="job-content-top-desc">Build <b>APIs</b></div></html>')

        def fake_get(url, timeout=20):
            return job if "JobID=" in url else AJ_HTML

        monkeypatch.setattr(prefetch, "get", fake_get)
        out = tmp_path / "out.json"
        assert prefetch.main(["--out", str(out)], root=tmp_path) == 0
        data = json.loads(out.read_text())
        assert data["raw_pages"] == []
        assert {c["company"] for c in data["candidates"]} == {"ALLSTARSIT", "Gtech"}
        d = data["candidates"][0]["description"]
        assert "Build APIs" in d and "MENU" not in d
