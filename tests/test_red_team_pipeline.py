# tests/test_red_team_pipeline.py
"""
Adversarial Red-Team Security & Robustness Test Suite for Tech Tips Hub Python Pipeline.
Targets: score.py, fetch.py, textclean.py, dedupe.py, filters.py, translate.py,
         run_pipeline.py, qa.py, and live data/config invariants.

STRICT: Read-only against production files. Never mutates scripts/*, config/*, or data/*.
"""
import contextlib
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import dedupe
import fetch
import filters
import qa
import run_pipeline
import score
import textclean
import translate


ISO_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def _make_valid_qa_item(item_id: str = "valid-item-0001", **overrides) -> dict:
    """Create a baseline QA-compliant visible item for isolated QA violation tests."""
    base = {
        "id": item_id,
        "slug": f"how-to-harden-ssh-on-linux-{item_id}",
        "url": f"https://linuxhandbook.com/{item_id}",
        "source": {
            "id": "linuxhandbook",
            "name": "Linux Handbook",
            "site_url": "https://linuxhandbook.com",
            "kind": "tips",
            "content_type": "article",
        },
        "author": "Alice",
        "published_at": "2026-11-20T10:00:00+00:00",
        "fetched_at": "2026-11-20T10:05:00+00:00",
        "original_lang": "en",
        "title": {
            "en": "How to harden SSH access on Ubuntu Linux servers",
            "vi": "Cách bảo mật kết nối SSH trên máy chủ Ubuntu Linux",
        },
        "summary": {
            "en": "Disable password authentication and enforce Ed25519 SSH keys to stop brute force attacks.",
            "vi": "Tắt đăng nhập bằng mật khẩu và bắt buộc dùng khóa SSH Ed25519 để ngăn tấn công dò mật khẩu.",
        },
        "categories": ["linux", "security"],
        "tags": ["ssh"],
        "difficulty": "advanced",
        "score": 0.92,
        "howto": True,
        "reading_time_min": 1,
        "translated": {"vi": "machine"},
    }
    base.update(overrides)
    return base


def _run_qa_on_items(items_dict: dict) -> tuple[int, str]:
    """Run qa.main() inside a throwaway temp directory so real data/ is never touched."""
    orig_cwd = os.getcwd()
    buf = io.StringIO()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        (tmp / "data").mkdir(parents=True, exist_ok=True)
        (tmp / "config").mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / "config" / "categories.yml", tmp / "config" / "categories.yml")
        (tmp / "data" / "index.json").write_text(
            json.dumps(items_dict, ensure_ascii=False), encoding="utf-8"
        )
        os.chdir(tmp)
        try:
            with contextlib.redirect_stdout(buf):
                try:
                    qa.main()
                    exit_code = 0
                except SystemExit as exc:
                    exit_code = exc.code if isinstance(exc.code, int) else 1
        finally:
            os.chdir(orig_cwd)
    return exit_code, buf.getvalue()


# =============================================================================
# 1. SCORE.PY & FETCH.PY — DATE PARSING, FAR-FUTURE POISONING & BOUNDARY FUZZ
# =============================================================================
class TestScoreAndDateAdversarial(unittest.TestCase):
    def test_tuoitre_narrow_nbsp_am_pm_and_vi_tz(self):
        am_iso = score.normalize_published_iso("10/16/2026 8:42:00\u202fAM", default_offset_hours=7)
        pm_iso = score.normalize_published_iso("10/16/2026 8:42:00\u202fPM", default_offset_hours=7)
        self.assertEqual(am_iso, "2026-10-16T01:42:00+00:00")
        self.assertEqual(pm_iso, "2026-10-16T13:42:00+00:00")

        dt_am = score.parse_published_time("10/16/2026 8:42:00\u202fAM", default_tz="tuoitre-nsso")
        self.assertEqual(dt_am, datetime(2026, 10, 16, 1, 42, 0, tzinfo=timezone.utc))

    def test_genk_two_digit_positive_and_negative_offsets(self):
        # GenK RFC-2822 +07
        genk_iso = score.normalize_published_iso("Thu, 15 Oct 2026 14:30:00 +07")
        self.assertEqual(genk_iso, "2026-10-15T07:30:00+00:00")

        # Negative 2-digit RFC-2822 -05
        neg_rfc = score.normalize_published_iso("Thu, 15 Oct 2026 14:30:00 -05")
        self.assertEqual(neg_rfc, "2026-10-15T19:30:00+00:00")

        # ISO with 2-digit offset -05 (uppercase T)
        neg_iso_upper = score.normalize_published_iso("2026-10-15T14:30:00-05")
        self.assertEqual(neg_iso_upper, "2026-10-15T19:30:00+00:00")

        # ISO with lowercase 't' and 2-digit offset -05 (RFC 3339 permits lowercase t)
        neg_iso_lower = score.normalize_published_iso("2026-10-15t14:30:00-05")
        self.assertEqual(
            neg_iso_lower,
            "2026-10-15T19:30:00+00:00",
            "Lowercase 't' ISO-8601 timestamp with 2-digit offset -05 failed to parse",
        )

    def test_iso_z_naive_struct_time_and_ddmmyyyy(self):
        self.assertEqual(
            score.normalize_published_iso("2026-11-20T09:15:30Z"),
            "2026-11-20T09:15:30+00:00",
        )
        self.assertEqual(
            score.normalize_published_iso("2026-11-20T09:15:30", default_offset_hours=0),
            "2026-11-20T09:15:30+00:00",
        )
        self.assertEqual(
            score.normalize_published_iso("2026-11-20T09:15:30", default_offset_hours=7),
            "2026-11-20T02:15:30+00:00",
        )

        st = time.struct_time((2026, 11, 20, 12, 34, 56, 4, 324, 0))
        self.assertEqual(
            score.normalize_published_iso("", parsed_struct=st),
            "2026-11-20T12:34:56+00:00",
        )

        # DD/MM/YYYY format
        self.assertEqual(
            score.normalize_published_iso("25/11/2026 14:30:00", default_offset_hours=7),
            "2026-11-25T07:30:00+00:00",
        )

    def test_none_empty_garbage_and_corrupt_struct_dates(self):
        for bad in (None, "", "   ", "not-a-date", "2026-02-30T10:00:00Z", 12345, {"date": "2026"}):
            self.assertEqual(score.normalize_published_iso(bad), "", f"Expected empty ISO for {bad!r}")
            dt = score.parse_published_time(bad)
            self.assertIsNotNone(dt.tzinfo)
            self.assertLess(abs((datetime.now(timezone.utc) - dt).total_seconds()), 10)

        # Corrupt struct_time must fail safely to ""
        self.assertEqual(score.normalize_published_iso("", parsed_struct=(99999, 99, 99, 99, 99, 99)), "")

    def test_far_future_year_2099_must_be_rejected_or_clamped_in_score(self):
        """Far-future dates like 2099 poison 'newest' sort and recency boost forever."""
        now = datetime.now(timezone.utc)
        max_allowed = now + timedelta(days=2)

        iso_2099 = score.normalize_published_iso("2099-12-31T23:59:59Z")
        if iso_2099:
            parsed = datetime.fromisoformat(iso_2099)
            self.assertLessEqual(
                parsed,
                max_allowed,
                f"normalize_published_iso accepted far-future year 2099 timestamp: {iso_2099!r}",
            )

        dt_2099 = score.parse_published_time("2099-12-31T23:59:59Z")
        self.assertLessEqual(
            dt_2099,
            max_allowed,
            f"parse_published_time accepted far-future year 2099 datetime: {dt_2099.isoformat()}",
        )

    def test_fetch_feed_must_not_accept_far_future_2099_dates(self):
        """A hostile RSS feed publishing year 2099 entries must not poison index chronology."""
        rss_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Hostile Feed</title>
        <item>
            <title>How to speed up Linux kernel boot permanently</title>
            <link>https://example.com/future-poison</link>
            <description>Detailed guide on optimizing systemd services to shave seconds off boot time.</description>
            <pubDate>Thu, 31 Dec 2099 23:59:59 GMT</pubDate>
        </item>
        </channel></rss>"""

        fake_resp = Mock(status_code=200, content=rss_xml, headers={})
        source = {
            "id": "hostile-rss",
            "name": "Hostile RSS",
            "type": "rss",
            "url": "https://example.com/feed.xml",
            "site_url": "https://example.com",
            "lang": "en",
            "kind": "tips",
            "categories": ["linux"],
        }
        with patch.object(fetch, "_get_response", return_value=fake_resp):
            items = fetch.fetch_feed_items(source)

        now = datetime.now(timezone.utc)
        for it in items:
            pub_dt = datetime.fromisoformat(it["published_at"].replace("Z", "+00:00"))
            self.assertLessEqual(
                pub_dt,
                now + timedelta(days=2),
                f"fetch_feed_items emitted far-future poisoned date: {it['published_at']}",
            )

    def test_calculate_score_boundary_nan_inf_negative(self):
        recent = datetime.now(timezone.utc).isoformat()
        for bad_weight in (float("nan"), float("inf"), float("-inf"), -10.0):
            s = score.calculate_score(
                "How to fix Wi-Fi",
                "Step by step tutorial to troubleshoot wireless adapter power management issues.",
                source_weight=bad_weight,
                published_at=recent,
                is_howto=True,
                community_signal=-500,
            )
            self.assertFalse(math.isnan(s), f"Score became NaN for weight={bad_weight}")
            self.assertFalse(math.isinf(s), f"Score became Inf for weight={bad_weight}")
            self.assertGreaterEqual(s, 0.1)
            self.assertLessEqual(s, 1.5)


# =============================================================================
# 2. TEXTCLEAN.PY — XSS & HTML EVASION + TECHNICAL PRESERVATION + BOILERPLATE
# =============================================================================
class TestTextCleanAdversarial(unittest.TestCase):
    def test_double_triple_and_deep_encoded_script_stripping(self):
        payloads = [
            "<script>alert(1)</script>Safe tip",
            "&lt;script&gt;alert(1)&lt;/script&gt;Safe tip",
            "&amp;lt;script&amp;gt;alert(1)&amp;lt;/script&amp;gt;Safe tip",
            "&amp;amp;lt;script&amp;amp;gt;alert(1)&amp;amp;lt;/script&amp;amp;gt;Safe tip",
            "&amp;amp;amp;amp;amp;lt;script&amp;amp;amp;amp;amp;gt;alert(1)&amp;amp;amp;amp;amp;lt;/script&amp;amp;amp;amp;amp;gt;Safe tip",
        ]
        for payload in payloads:
            out = textclean.clean_text(payload)
            self.assertNotIn("<script", out.lower(), f"Script tag survived for: {payload!r} -> {out!r}")
            self.assertNotIn("alert(1)", out, f"Script body survived for: {payload!r} -> {out!r}")
            self.assertNotIn("&lt;", out.lower(), f"Encoded entity survived for: {payload!r} -> {out!r}")
            self.assertIn("Safe tip", out)

    def test_svg_onload_raw_and_encoded_evasion(self):
        payloads = [
            "<svg onload=alert(1)>Safe content",
            "&lt;svg onload=alert(1)&gt;Safe content",
            "&amp;lt;svg onload=alert(1)&amp;gt;Safe content",
            "&lt;svg/onload=alert(1)&gt;Safe content",
            "&lt;details open ontoggle=alert(1)&gt;Safe content",
        ]
        for payload in payloads:
            out = textclean.clean_text(payload)
            self.assertNotIn("<svg", out.lower(), f"SVG XSS survived: {payload!r} -> {out!r}")
            self.assertNotIn("onload", out.lower(), f"onload handler survived: {payload!r} -> {out!r}")
            self.assertNotIn("ontoggle", out.lower(), f"ontoggle handler survived: {payload!r} -> {out!r}")
            self.assertNotIn("alert(1)", out, f"JS payload survived: {payload!r} -> {out!r}")

    def test_img_onerror_and_style_evasion(self):
        payloads = [
            "<img src=x onerror=alert(1)>Real guide",
            "&lt;img src=x onerror=alert(1)&gt;Real guide",
            '<img src="x" title=">" onerror="alert(1)">Real guide',
            "<style>body{display:none}</style>Real guide",
            "&amp;lt;style&amp;gt;body{display:none}&amp;lt;/style&amp;gt;Real guide",
            "<style>body{display:none}",
            "&lt;style&gt;body{display:none}",
        ]
        for payload in payloads:
            out = textclean.clean_text(payload)
            self.assertNotIn("<img", out.lower(), f"IMG tag survived: {payload!r} -> {out!r}")
            self.assertNotIn("onerror", out.lower(), f"onerror survived: {payload!r} -> {out!r}")
            self.assertNotIn("<style", out.lower(), f"STYLE tag survived: {payload!r} -> {out!r}")
            self.assertNotIn("display:none", out.lower(), f"CSS payload survived: {payload!r} -> {out!r}")

    def test_unclosed_script_tag_raw_and_encoded(self):
        payloads = [
            "Useful tip <script>alert(1)",
            "Useful tip <script src=//evil.example/xss.js",
            "Useful tip &lt;script&gt;alert(1)",
            "Useful tip &amp;lt;script&amp;gt;alert(1)",
        ]
        for payload in payloads:
            out = textclean.clean_text(payload)
            self.assertNotIn("<script", out.lower(), f"Unclosed script tag survived: {payload!r} -> {out!r}")
            self.assertNotIn("alert(1)", out, f"Unclosed script JS survived: {payload!r} -> {out!r}")
            self.assertNotIn("evil.example", out, f"Unclosed script src survived: {payload!r} -> {out!r}")

    def test_preserves_technical_generics_and_comparisons(self):
        # Escaped form (from RSS/HTML)
        escaped = "Use std::vector&lt;int&gt; when x &lt; 10 and y &gt; 20"
        out_esc = textclean.clean_text(escaped)
        self.assertIn("std::vector<int>", out_esc)
        self.assertIn("x < 10 and y > 20", out_esc)

        # Raw form (from JSON APIs like Dev.to / HN Algolia or LLM plain-text output)
        raw = "Use std::vector<int> when x < 10 and y > 20"
        out_raw = textclean.clean_text(raw)
        self.assertIn(
            "std::vector<int>",
            out_raw,
            f"clean_text destroyed raw C++ generic std::vector<int> -> {out_raw!r}",
        )
        self.assertIn("x < 10 and y > 20", out_raw)

        # Compact code comparison without spaces
        compact = "Check condition (a<b && c>d) before loop"
        out_compact = textclean.clean_text(compact)
        self.assertIn(
            "(a<b && c>d)",
            out_compact,
            f"clean_text corrupted compact comparison expression -> {out_compact!r}",
        )

    def test_boilerplate_stripping(self):
        wp = "Speed up Windows startup cleanly. The post Speed up Windows startup cleanly appeared first on How-To Geek."
        self.assertEqual(textclean.clean_text(wp), "Speed up Windows startup cleanly.")

        reddit = "Use Ctrl+Shift+T to reopen closed tabs submitted by /u/alice_dev [link] [comments]"
        self.assertEqual(textclean.clean_text(reddit), "Use Ctrl+Shift+T to reopen closed tabs")

        hn = "Great terminal multiplexing guide. Article URL: https://example.com/tmux Comments URL: https://news.ycombinator.com/item?id=123 Points: 200 # Comments: 55"
        self.assertEqual(textclean.clean_text(hn), "Great terminal multiplexing guide.")


# =============================================================================
# 3. DEDUPE.PY & FILTERS.PY — URL TRAPS, SCHEME BYPASSES & FILTER EVASION
# =============================================================================
class TestDedupeAndFiltersAdversarial(unittest.TestCase):
    def test_canonical_url_tracking_params_trailing_slash_fragments(self):
        u1 = dedupe.canonical_url(
            "https://Example.COM/tips/linux///?UTM_SOURCE=Twitter&utm_id=42&fbclid=xyz&page=2#comments"
        )
        u2 = dedupe.canonical_url("https://example.com/tips/linux?page=2")
        self.assertEqual(u1, u2)
        self.assertEqual(u1, "https://example.com/tips/linux?page=2")

    def test_canonical_url_strips_default_ports_443_and_80(self):
        https_port = dedupe.canonical_url("https://example.com:443/tip")
        https_plain = dedupe.canonical_url("https://example.com/tip")
        self.assertEqual(
            https_port,
            https_plain,
            f"Default HTTPS port :443 was not stripped: {https_port!r} != {https_plain!r}",
        )

        http_port = dedupe.canonical_url("http://example.com:80/tip")
        http_plain = dedupe.canonical_url("http://example.com/tip")
        self.assertEqual(
            http_port,
            http_plain,
            f"Default HTTP port :80 was not stripped: {http_port!r} != {http_plain!r}",
        )

        # Non-default port must remain intact
        self.assertEqual(dedupe.canonical_url("https://example.com:8443/tip"), "https://example.com:8443/tip")

    def test_canonical_url_blocks_javascript_data_and_non_http_schemes(self):
        dangerous = [
            "javascript:alert(1)",
            "  JaVaScRiPt:alert(document.cookie)  ",
            "data:text/html,<script>alert(1)</script>",
            "vbscript:msgbox(1)",
            "file:///etc/passwd",
            "ftp://evil.example/payload",
            "relative/path/without/scheme",
        ]
        for url in dangerous:
            res = dedupe.canonical_url(url)
            self.assertEqual(
                res,
                "",
                f"canonical_url failed to reject dangerous/non-HTTP(S) URL {url!r} -> {res!r}",
            )

    def test_fetch_rejects_javascript_urls_from_rss(self):
        rss_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>XSS Feed</title>
        <item>
            <title>How to secure browser cookies properly</title>
            <link>javascript:alert(1)</link>
            <description>Learn how to inspect and harden cookies across modern browsers.</description>
            <pubDate>Thu, 19 Nov 2026 10:00:00 GMT</pubDate>
        </item>
        </channel></rss>"""
        fake_rss = Mock(status_code=200, content=rss_xml, headers={})
        rss_src = {
            "id": "xss-rss",
            "name": "XSS RSS",
            "type": "rss",
            "url": "https://example.com/rss",
            "site_url": "https://example.com",
            "lang": "en",
            "kind": "tips",
        }
        with patch.object(fetch, "_get_response", return_value=fake_rss):
            rss_items = fetch.fetch_feed_items(rss_src)
        self.assertEqual(rss_items, [], f"RSS fetch emitted dangerous URL items: {rss_items}")

    def test_fetch_rejects_javascript_urls_from_json_api(self):
        # Also exposes missing `if not c_url: continue` guard in scripts/fetch.py:162
        api_payload = [
            {
                "title": "How to debug Node.js memory leaks",
                "url": "javascript:alert(1)",
                "published_at": "2026-11-19T10:00:00Z",
                "description": "Use Chrome DevTools heap snapshots to find retained objects.",
                "public_reactions_count": 25,
                "user": {"name": "Mallory"},
            }
        ]
        fake_api = Mock(status_code=200, headers={})
        fake_api.json.return_value = api_payload
        api_src = {
            "id": "xss-api",
            "name": "XSS API",
            "type": "json-api",
            "api": "devto",
            "url": "https://dev.to/api/articles",
            "site_url": "https://dev.to",
            "lang": "en",
            "kind": "tips",
        }
        with patch.object(fetch, "_get_response", return_value=fake_api):
            api_items = fetch.fetch_feed_items(api_src)
        self.assertEqual(api_items, [], f"JSON API fetch emitted dangerous/empty URL items: {api_items}")

    def test_filters_url_only_summary_with_whitespace_and_punctuation(self):
        src = {"id": "itsfoss", "kind": "tips"}
        url_only_variants = [
            "  https://youtu.be/abc  ",
            "  https://youtu.be/abc . ",
            "https://youtu.be/abc …",
            "(https://youtu.be/abc)",
            "https://youtu.be/abc https://github.com/org/repo",
        ]
        for summ in url_only_variants:
            ok, reason = filters.accept(
                {"raw_title": "How to automate backups on Linux", "raw_summary": summ},
                src,
                enable_logging=False,
            )
            self.assertFalse(
                ok,
                f"URL-only summary bypassed filters.accept(): {summ!r} -> ({ok}, {reason!r})",
            )

    def test_filters_dependabot_ci_release_noise_and_howto_false_positives(self):
        news_src = {"id": "powertoys-release", "kind": "news"}
        noisy_cases = [
            ("build(deps-dev): bump vite from 5.0.0 to 5.4.1", "Bumps vite dependency version."),
            ("chore(deps): update actions/checkout to v4", "Automated dependency maintenance."),
            ("Dev preview v0.104.0", "Preview build with minor settings fixes."),
            ("fix(deps): update lodash dependency", "Automated dependency bump for security fix."),
            ("ci(deps): update github/codeql-action", "Fix CI workflow dependency setup."),
            ("PowerToys v0.88.0", "Bug fixes and stability improvements for Settings and FancyZones."),
        ]
        for title, summary in noisy_cases:
            self.assertFalse(
                filters.is_howto_match(title, summary),
                f"is_howto_match false positive on release/CI noise: {title!r} | {summary!r}",
            )
            ok, reason = filters.accept(
                {"raw_title": title, "raw_summary": summary},
                news_src,
                enable_logging=False,
            )
            self.assertFalse(
                ok,
                f"Release/CI noise bypassed filters.accept(): {title!r} -> ({ok}, {reason!r})",
            )

    def test_filters_cjk_deal_spam_blocked_and_foldable_allowed(self):
        src = {"id": "sspai-cn", "kind": "tips"}
        spam_titles = [
            "双十一官方补贴：某品牌机械键盘直降 300 元到手价 199 元",
            "限时优惠 8.5 折！高速固态硬盘促销攻略",
            "Epic 喜加一限免领取教程",
        ]
        for title in spam_titles:
            ok, _ = filters.accept(
                {"raw_title": title, "raw_summary": "详细购买链接和优惠券领取步骤说明。"},
                src,
                enable_logging=False,
            )
            self.assertFalse(ok, f"CJK deal spam bypassed filters.accept(): {title!r}")

        # Foldable phone tip ("折叠") must NOT be false-positived as discount ("折")
        ok_fold, reason_fold = filters.accept(
            {
                "raw_title": "三折叠屏手机高效分屏多任务使用技巧指南",
                "raw_summary": "教你如何通过系统设置开启双窗口协同与快捷手势提升办公效率。",
            },
            src,
            enable_logging=False,
        )
        self.assertTrue(ok_fold, f"Legitimate foldable phone tip wrongly rejected: {reason_fold}")


# =============================================================================
# 4. TRANSLATE.PY — HIDDEN QUOTA, VALIDATION, COOLDOWN, PARSER & GEMINI
# =============================================================================
class TestTranslateAdversarial(unittest.TestCase):
    def test_hidden_items_skipped_in_both_batch_and_chinese_translators(self):
        translator = Mock()
        translator.translate_batch.return_value = []
        cache = {}

        hidden_en = {
            "id": "hid-en-1",
            "hidden": True,
            "original_lang": "en",
            "title": {"en": "How to tune Linux swap"},
            "summary": {"en": "Adjust vm.swappiness to improve desktop responsiveness."},
            "translated": {},
            "score": 1.4,
            "howto": True,
        }
        hidden_vi = {
            "id": "hid-vi-1",
            "hidden": True,
            "original_lang": "vi",
            "title": {"vi": "Cách tối ưu pin laptop Windows 11"},
            "summary": {"vi": "Hướng dẫn bật chế độ tiết kiệm pin và tắt ứng dụng chạy nền."},
            "translated": {},
            "score": 1.4,
            "howto": True,
        }
        hidden_zh = {
            "id": "hid-zh-1",
            "hidden": True,
            "original_lang": "zh-CN",
            "title": {"zh-CN": "如何优化 macOS 终端启动速度"},
            "summary": {"zh-CN": "通过延迟加载 zsh 插件大幅缩短终端冷启动耗时。"},
            "translated": {},
            "score": 1.5,
            "howto": True,
        }

        translate.batch_translate_pending(
            [hidden_en, hidden_vi, hidden_zh], cache, translator=translator, max_items=20
        )
        self.assertEqual(
            translator.translate_batch.call_count,
            0,
            "batch_translate_pending called translator for hidden items!",
        )

        # Direct call to _translate_chinese_items MUST also skip hidden items
        processed = translate._translate_chinese_items(
            [hidden_zh], cache, translator=translator, batch_size=5, max_items=10
        )
        self.assertEqual(processed, 0)
        self.assertEqual(
            translator.translate_batch.call_count,
            0,
            "_translate_chinese_items called translator for hidden items!",
        )

    def test_is_valid_translation_rejects_empty_verbatim_wrong_lang_and_mixed_upper(self):
        # Empty & whitespace summaries
        self.assertFalse(
            translate.is_valid_translation("Title", "Summary", "Tiêu đề tiếng Việt", "", "en", "vi")
        )
        self.assertFalse(
            translate.is_valid_translation("Title", "Summary", "Tiêu đề tiếng Việt", "   \n\t ", "en", "vi")
        )

        # Verbatim unchanged copy when source_lang != target_lang
        self.assertFalse(
            translate.is_valid_translation(
                "Windows 11 Settings",
                "Open Settings and toggle Dark Mode.",
                "Windows 11 Settings",
                "Open Settings and toggle Dark Mode.",
                "vi",
                "en",
            )
        )

        # Wrong-language summary (VI summary falsely labeled en: machine — modeled on 6f7743a9465550a4)
        self.assertFalse(
            translate.is_valid_translation(
                "Oppo Find X10 Pro Max - smartphone có ba camera 200 megapixel",
                "Oppo Find X10 Pro Max là điện thoại đầu tiên trang bị ba camera sau cùng độ phân giải 200 megapixel.",
                "Oppo Find X10 Pro Max is the first phone with triple 200MP cameras",
                "Oppo Find X10 Pro Max là điện thoại đầu tiên trang bị ba camera sau cùng độ phân giải 200 megapixel.",
                "vi",
                "en",
            )
        )

        # Standard capitalized mixed EN/VI sentence & exact [Bản dịch] prefix
        self.assertFalse(
            translate.is_valid_translation(
                "How a Salon Website Gets Built in Lovable",
                "A walkthrough of building a site in Lovable.",
                "Cách a Salon Website Gets Built in Lovable",
                "Hướng dẫn xây dựng trang web bằng công cụ Lovable nhanh chóng.",
                "en",
                "vi",
            )
        )
        self.assertFalse(
            translate.is_valid_translation(
                "How to speed up Git",
                "Enable commit-graph to make git log faster.",
                "[Bản dịch] Cách tăng tốc Git",
                "Bật tính năng commit-graph để chạy lệnh git log nhanh hơn.",
                "en",
                "vi",
            )
        )

    def test_is_valid_translation_rejects_lowercase_mixed_en_vi(self):
        self.assertFalse(
            translate.is_valid_translation(
                "How to fix Wi-Fi drops on Windows",
                "Guide to troubleshooting Wi-Fi disconnects on Windows 11.",
                "How to sửa lỗi Wi-Fi connection on this Windows PC",
                "Hướng dẫn khắc phục lỗi mất kết nối Wi-Fi trên máy tính Windows.",
                "en",
                "vi",
            ),
            "is_valid_translation failed to reject lowercase mixed EN/VI title!",
        )

    def test_is_valid_translation_rejects_case_variant_ban_dich_prefix(self):
        self.assertFalse(
            translate.is_valid_translation(
                "How to speed up Git",
                "Enable commit-graph to make git log faster.",
                "[bản dịch] Cách tăng tốc Git",
                "Bật tính năng commit-graph để chạy lệnh git log nhanh hơn.",
                "en",
                "vi",
            ),
            "Case-variation '[bản dịch]' bypassed is_valid_translation!",
        )

    def test_is_valid_translation_rejects_url_only_summary(self):
        # Exploits non_url_alpha_count == 0 < 15 bypass in scripts/translate.py:146-150!
        self.assertFalse(
            translate.is_valid_translation(
                "How to fix Linux audio",
                "Restart PipeWire daemon to restore sound output.",
                "Cách sửa lỗi âm thanh trên Linux",
                "https://youtu.be/dQw4w9WgXcQ",
                "en",
                "vi",
            ),
            "URL-only VI summary bypassed is_valid_translation via s_alpha < 15!",
        )
        self.assertFalse(
            translate.is_valid_translation(
                "Cách sửa lỗi âm thanh trên Linux",
                "Khởi động lại dịch vụ PipeWire để khôi phục âm thanh.",
                "How to fix Linux audio output",
                "  https://example.com/only-link  ",
                "vi",
                "en",
            ),
            "URL-only EN summary bypassed is_valid_translation via s_alpha < 15!",
        )

    def test_cooldown_retry_24h_lifetime_cap_and_clearing_on_success_and_cache_hit(self):
        t0 = datetime(2026, 11, 21, 8, 0, 0, tzinfo=timezone.utc)
        item = {"id": "retry-1", "original_lang": "en"}

        # Failures 1 and 2: no cooldown yet
        translate._record_translation_failure(item, "vi", now=t0)
        self.assertEqual(item["translate_attempts"]["vi"], 1)
        self.assertNotIn("translate_next_retry", item)
        self.assertTrue(translate._can_attempt_translation(item, "vi", now=t0))

        translate._record_translation_failure(item, "vi", now=t0)
        self.assertEqual(item["translate_attempts"]["vi"], 2)
        self.assertNotIn("translate_next_retry", item)
        self.assertTrue(translate._can_attempt_translation(item, "vi", now=t0))

        # 3rd failure: sets ~24h cooldown, blocks immediate & +23h59m, allows +24h01m
        translate._record_translation_failure(item, "vi", now=t0)
        self.assertEqual(item["translate_attempts"]["vi"], 3)
        next_retry_str = item.get("translate_next_retry", {}).get("vi")
        self.assertTrue(next_retry_str)
        next_retry_dt = datetime.fromisoformat(next_retry_str)
        delta_hours = (next_retry_dt - t0).total_seconds() / 3600.0
        self.assertAlmostEqual(delta_hours, 24.0, places=2)

        self.assertFalse(translate._can_attempt_translation(item, "vi", now=t0))
        self.assertFalse(translate._can_attempt_translation(item, "vi", now=t0 + timedelta(hours=23, minutes=59)))
        self.assertTrue(translate._can_attempt_translation(item, "vi", now=t0 + timedelta(hours=24, minutes=1)))

        # Reach lifetime cap (>= 9): permanently stops retrying even a year later
        cur_t = t0 + timedelta(days=1)
        for _ in range(6):
            translate._record_translation_failure(item, "vi", now=cur_t)
            cur_t += timedelta(days=2)
        self.assertEqual(item["translate_attempts"]["vi"], 9)
        self.assertNotIn("translate_next_retry", item)
        self.assertFalse(translate._can_attempt_translation(item, "vi", now=cur_t + timedelta(days=365)))

        # Clearing on successful translation via batch_translate_pending
        item_ok = {
            "id": "clear-on-success",
            "original_lang": "en",
            "title": {"en": "How to enable DNS over HTTPS"},
            "summary": {"en": "Configure Firefox and Chrome to encrypt DNS lookups safely."},
            "translated": {"vi": False},
            "translate_attempts": {"vi": 3},
            "translate_next_retry": {"vi": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()},
            "score": 0.9,
            "howto": True,
        }
        good_translator = Mock()
        good_translator.translate_batch.return_value = [
            {
                "id": "clear-on-success",
                "title": "Cách bật DNS qua HTTPS trên trình duyệt",
                "summary": "Hướng dẫn cấu hình Firefox và Chrome để mã hóa truy vấn DNS an toàn.",
            }
        ]
        cache = {}
        translate.batch_translate_pending([item_ok], cache, translator=good_translator, max_items=10)
        self.assertEqual(item_ok["translated"]["vi"], "machine")
        self.assertNotIn("translate_attempts", item_ok)
        self.assertNotIn("translate_next_retry", item_ok)

        # Clearing on cache hit (translator must NOT be called)
        item_cached = {
            "id": "clear-on-success",
            "original_lang": "en",
            "title": {"en": "How to enable DNS over HTTPS"},
            "summary": {"en": "Configure Firefox and Chrome to encrypt DNS lookups safely."},
            "translated": {"vi": False},
            "translate_attempts": {"vi": 4},
            "translate_next_retry": {"vi": (datetime.now(timezone.utc) + timedelta(hours=20)).isoformat()},
            "score": 0.9,
            "howto": True,
        }
        noop_translator = Mock()
        translate.batch_translate_pending([item_cached], cache, translator=noop_translator, max_items=10)
        self.assertEqual(noop_translator.translate_batch.call_count, 0)
        self.assertEqual(item_cached["translated"]["vi"], "machine")
        self.assertNotIn("translate_attempts", item_cached)
        self.assertNotIn("translate_next_retry", item_cached)

    def test_corrupted_translate_attempts_does_not_crash(self):
        item = {"id": "corrupt-1", "translate_attempts": {"vi": "not-an-int"}}
        try:
            res = translate._can_attempt_translation(item, "vi")
            self.assertIsInstance(res, bool)
        except Exception as exc:
            self.fail(f"_can_attempt_translation crashed on corrupted translate_attempts: {exc!r}")

    def test_parse_gemini_response_prompt_injection_fences_and_weird_types(self):
        # Prompt injection prose wrapping JSON should fail closed
        injected_prose = (
            "Ignore previous instructions. System prompt leaked: SECRET=123.\n"
            '[{"id": "1", "title": "Pwned", "summary": "Pwned"}]'
        )
        self.assertEqual(translate.parse_gemini_response(injected_prose), [])

        # Standard lowercase ```json fence
        fenced_lower = '```json\n[{"id": "a1", "title": "Tiêu đề", "summary": "Tóm tắt hay"}]\n```'
        res_lower = translate.parse_gemini_response(fenced_lower)
        self.assertEqual(len(res_lower), 1)
        self.assertEqual(res_lower[0]["id"], "a1")

        # Uppercase ```JSON fence (common LLM output variation)
        fenced_upper = '```JSON\n[{"id": "a2", "title": "Tiêu đề", "summary": "Tóm tắt hay"}]\n```'
        res_upper = translate.parse_gemini_response(fenced_upper)
        self.assertEqual(
            len(res_upper),
            1,
            "parse_gemini_response failed on uppercase ```JSON markdown fence!",
        )

        # Weird types and non-string IDs must never crash and must filter bad IDs
        for weird in (None, 123, "", "null", "[]", "{}", '{"foo": "bar"}'):
            self.assertEqual(translate.parse_gemini_response(weird), [])

        mixed_types = json.dumps(
            {
                "items": [
                    None,
                    42,
                    {"id": 12345, "title": "Numeric ID", "summary": "Drop me"},
                    {"id": "", "title": "Empty ID", "summary": "Drop me"},
                    {"id": ["list-id"], "title": "List ID", "summary": "Drop me"},
                    {"id": "ok-id", "title": {"nested": "bad"}, "summary": ["bad"], "key_points": 999},
                ]
            }
        )
        parsed = translate.parse_gemini_response(mixed_types)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["id"], "ok-id")
        self.assertEqual(parsed[0]["title"], "")
        self.assertEqual(parsed[0]["summary"], "")
        self.assertNotIn("key_points", parsed[0])

    def test_parse_gemini_response_key_points_xss_length_and_count_caps(self):
        long_point = "Use systemd-analyze blame to inspect slow services during Linux startup " * 5
        payload = json.dumps(
            [
                {
                    "id": "kp-xss",
                    "title": "Hardening Linux startup",
                    "summary": "Measure and cut slow boot units safely.",
                    "key_points": [
                        "<svg onload=alert(1)>",
                        "&lt;svg/onload=alert(1)&gt;",
                        '<a href="javascript:alert(1)">click</a>',
                        '<a href="data:text/html,<script>alert(1)</script>">open</a>',
                        "&lt;data&gt;injected data tag",
                        "javascript:alert(1) run this",
                        long_point,
                        "Point two is clean and useful",
                        "Point three is clean and useful",
                        "Point four exceeds max 3 items",
                        "Point five exceeds max 3 items",
                    ],
                }
            ]
        )
        parsed = translate.parse_gemini_response(payload, target_lang="en")
        self.assertEqual(len(parsed), 1)
        kps = parsed[0].get("key_points", [])
        self.assertLessEqual(len(kps), 3, f"key_points exceeded cap of 3: {kps}")
        for pt in kps:
            self.assertLessEqual(len(pt), 200, f"key_point exceeded 200 chars: len={len(pt)}")
            self.assertNotIn("<svg", pt.lower(), f"SVG XSS leaked into key_points: {pt!r}")
            self.assertNotIn("onload=", pt.lower(), f"onload leaked into key_points: {pt!r}")
            self.assertNotIn("javascript:", pt.lower(), f"javascript: URI leaked into key_points: {pt!r}")
            self.assertNotIn("data:text/html", pt.lower(), f"data: URI leaked into key_points: {pt!r}")
            self.assertNotIn("<data>", pt.lower(), f"Raw <data> tag leaked into key_points: {pt!r}")
            self.assertNotIn("<script", pt.lower(), f"Script tag leaked into key_points: {pt!r}")

    def test_sanitize_key_points_directly_rejects_svg_slash_and_data_tag_xss(self):
        """Targeted check on sanitize_key_points with slash-separated SVG and <data>/<object> tags."""
        kps = translate.sanitize_key_points(
            [
                "&lt;svg/onload=alert(1)&gt;",
                "&lt;data&gt;malicious",
                "&lt;object&gt;payload",
                'Click <a href="javascript:alert(1)">here</a>',
            ]
        )
        for pt in kps:
            self.assertNotIn("<svg", pt.lower(), f"Slash-delimited SVG survived sanitize_key_points: {pt!r}")
            self.assertNotIn("<data", pt.lower(), f"<data> tag survived sanitize_key_points: {pt!r}")
            self.assertNotIn("<object", pt.lower(), f"<object> tag survived sanitize_key_points: {pt!r}")
            self.assertNotIn("javascript:", pt.lower(), f"javascript: survived sanitize_key_points: {pt!r}")

    def test_gemini_translator_thinking_config_retries_500_503_and_no_retired_models(self):
        sent_requests = []

        def fake_post(url, json=None, headers=None, timeout=None):
            sent_requests.append((url, json, headers))
            idx = len(sent_requests)
            if idx == 1:
                return Mock(status_code=500, text="Internal error")
            if idx == 2:
                return Mock(status_code=503, text="Service unavailable")
            resp = Mock(status_code=200, text="OK")
            resp.json.return_value = {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": '[{"id":"g1","title":"Cách dùng tmux","summary":"Hướng dẫn dùng tmux cơ bản trên Linux."}]'
                                }
                            ]
                        }
                    }
                ]
            }
            return resp

        env = {"GEMINI_API_KEY": "test-secret-key-12345"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("GEMINI_MODEL", None)
            gt = translate.GeminiTranslator()
            with patch("requests.Session.post", side_effect=fake_post), patch("time.sleep"):
                res = gt.translate_batch(
                    [{"id": "g1", "title": "How to use tmux", "summary": "Basic tmux guide on Linux."}],
                    source_lang="en",
                    target_lang="vi",
                )

        self.assertEqual(len(res), 1)
        self.assertEqual(len(sent_requests), 3, "Expected retries on HTTP 500 and HTTP 503")
        for url, payload, _headers in sent_requests:
            self.assertIn("gemini-2.5", url)
            self.assertEqual(
                payload["generationConfig"].get("thinkingConfig"),
                {"thinkingBudget": 0},
                "Missing thinkingConfig: {'thinkingBudget': 0} on gemini-2.5-* request",
            )

        # Verify fallback model chain on 404 NEVER calls retired gemini-1.5-flash or gemini-2.0-flash
        fallback_urls = []

        def fake_404(url, json=None, headers=None, timeout=None):
            fallback_urls.append(url)
            return Mock(status_code=404, text="Not Found")

        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("GEMINI_MODEL", None)
            gt = translate.GeminiTranslator()
            with patch("requests.Session.post", side_effect=fake_404), patch("time.sleep"):
                res404 = gt.translate_batch(
                    [{"id": "g1", "title": "How to use tmux", "summary": "Basic tmux guide."}],
                    source_lang="en",
                    target_lang="vi",
                )

        self.assertEqual(res404, [])
        self.assertGreaterEqual(len(fallback_urls), 2)
        for url in fallback_urls:
            self.assertNotIn("gemini-1.5-flash", url, f"Retired model called: {url}")
            self.assertNotIn("gemini-2.0-flash", url, f"Retired model called: {url}")


# =============================================================================
# 5. RUN_PIPELINE.PY, QA.PY & LIVE DATA INVARIANTS
# =============================================================================
class TestPipelineAndQAAdversarial(unittest.TestCase):
    def test_diversify_limits_source_content_type_community_accurately(self):
        items = []
        # 10 high-score community items where ONLY source.content_type == "community"
        for i in range(10):
            items.append(
                {
                    "id": f"comm-{i}",
                    "score": 1.4 - i * 0.01,
                    "source": {"id": f"comm-src-{i % 3}", "content_type": "community"},
                }
            )
        # 24 lower-score editorial items across 3 sources
        for i in range(24):
            items.append(
                {
                    "id": f"art-{i}",
                    "score": 0.8 - i * 0.01,
                    "source": {"id": f"art-src-{i % 3}", "content_type": "article"},
                }
            )

        out = run_pipeline.diversify(items, max_run=2, max_community_per_window=3, window_size=20)
        self.assertEqual(len(out), len(items))

        # First window of 20 items must contain at most 3 community items
        first_window = out[:20]
        comm_in_first = sum(1 for x in first_window if x["source"]["content_type"] == "community")
        self.assertLessEqual(
            comm_in_first,
            3,
            f"diversify allowed {comm_in_first} community items in first 20-item window (max 3)",
        )

        # Sliding window invariant while enough articles remain (first 24 slots)
        for start in range(0, 6):
            win = out[start : start + 20]
            c_cnt = sum(1 for x in win if x["source"]["content_type"] == "community")
            self.assertLessEqual(c_cnt, 3, f"Window [{start}:{start+20}] had {c_cnt} community items")

        # Max consecutive run from same source <= 2 while diverse items remain
        for i in range(2, 24):
            s0 = out[i - 2]["source"]["id"]
            s1 = out[i - 1]["source"]["id"]
            s2 = out[i]["source"]["id"]
            self.assertFalse(s0 == s1 == s2, f"3 consecutive items from same source {s0} at index {i}")

    def test_diversify_handles_none_score_without_crashing(self):
        items = [
            {"id": "a", "score": None, "source": {"id": "s1", "content_type": "article"}},
            {"id": "b", "score": 0.9, "source": {"id": "s2", "content_type": "article"}},
        ]
        try:
            out = run_pipeline.diversify(items)
            self.assertEqual(len(out), 2)
        except Exception as exc:
            self.fail(f"diversify crashed when an item had score=None: {exc!r}")

    def test_hidden_item_does_not_absorb_new_duplicate_title_article(self):
        orig_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "config").mkdir()
            (tmp / "data" / "logs").mkdir(parents=True)
            shutil.copy2(REPO_ROOT / "config" / "blocklist.yml", tmp / "config" / "blocklist.yml")
            shutil.copy2(REPO_ROOT / "config" / "categories.yml", tmp / "config" / "categories.yml")

            sources = [
                {
                    "id": "itsfoss",
                    "name": "It's FOSS",
                    "type": "rss",
                    "url": "https://itsfoss.com/feed/",
                    "site_url": "https://itsfoss.com",
                    "lang": "en",
                    "categories": ["linux"],
                    "trust": 4,
                    "kind": "tips",
                    "contentType": "article",
                    "enabled": True,
                    "maxPerRun": 10,
                }
            ]
            (tmp / "config" / "sources.json").write_text(json.dumps(sources), encoding="utf-8")

            now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            hidden_existing = _make_valid_qa_item(
                "old-hidden-0001",
                hidden=True,
                published_at=now_iso,
                url="https://old.example.com/ssh-guide",
                title={
                    "en": "How to configure SSH keys safely on Ubuntu Linux",
                    "vi": "Cách cấu hình khóa SSH an toàn trên Ubuntu Linux",
                },
            )
            (tmp / "data" / "index.json").write_text(
                json.dumps({"old-hidden-0001": hidden_existing}), encoding="utf-8"
            )

            fresh_article = {
                "id": "new-fresh-0002",
                "url": "https://itsfoss.com/ssh-keys-ubuntu-linux",
                "source": {
                    "id": "itsfoss",
                    "name": "It's FOSS",
                    "site_url": "https://itsfoss.com",
                    "kind": "tips",
                },
                "source_weight": 1.25,
                "source_kind": "tips",
                "content_type": "article",
                "author": "Bob",
                "published_at": now_iso,
                "original_lang": "en",
                "raw_title": "How to configure SSH keys safely on Ubuntu Linux",
                "raw_summary": "Generate Ed25519 SSH keys and copy your public key to authorize passwordless Linux logins.",
                "default_categories": ["linux"],
            }

            os.chdir(tmp)
            try:
                with (
                    patch.object(run_pipeline, "DATA_DIR", tmp / "data"),
                    patch.object(run_pipeline, "INDEX_PATH", tmp / "data" / "index.json"),
                    patch.object(run_pipeline, "STATE_PATH", tmp / "data" / "state.json"),
                    patch.object(run_pipeline, "COMMUNITY_PATH", tmp / "data" / "community.json"),
                    patch.object(run_pipeline, "HEALTH_PATH", tmp / "data" / "health.json"),
                    patch.object(filters, "REJECTED_LOG", tmp / "data" / "logs" / "rejected.jsonl"),
                    patch.object(translate, "CACHE_FILE", tmp / "data" / "cache" / "translations.json"),
                    patch.object(run_pipeline, "fetch_feed_items", return_value=[fresh_article]),
                    patch.object(run_pipeline, "batch_translate_pending"),
                    patch.object(run_pipeline, "load_cache", return_value={}),
                    patch.object(run_pipeline, "save_cache"),
                    patch("time.sleep"),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    run_pipeline.main()
            finally:
                os.chdir(orig_cwd)

            saved = json.loads((tmp / "data" / "index.json").read_text(encoding="utf-8"))
            self.assertIn(
                "new-fresh-0002",
                saved,
                "Hidden item absorbed a brand-new duplicate-title article instead of letting it publish!",
            )
            self.assertNotIn("alsoFrom", saved["old-hidden-0001"])

    def test_admin_approved_community_review_and_sale_allowed_while_spam_domain_blocked(self):
        """Admin-approved community tips containing 'review' or 'sale' must not be silently dropped,
        while hard-blocked spam domains MUST be blocked."""
        orig_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "config").mkdir()
            (tmp / "data" / "logs").mkdir(parents=True)
            shutil.copy2(REPO_ROOT / "config" / "categories.yml", tmp / "config" / "categories.yml")

            # Use real blocklist.yml + one explicit spam domain
            bl_text = (REPO_ROOT / "config" / "blocklist.yml").read_text(encoding="utf-8")
            bl_text = bl_text.replace("domains: []", 'domains:\n  - "spam-domain.invalid"')
            (tmp / "config" / "blocklist.yml").write_text(bl_text, encoding="utf-8")

            sources = [
                {
                    "id": "itsfoss",
                    "name": "It's FOSS",
                    "type": "rss",
                    "url": "https://itsfoss.com/feed/",
                    "site_url": "https://itsfoss.com",
                    "lang": "en",
                    "categories": ["linux"],
                    "trust": 4,
                    "kind": "tips",
                    "contentType": "article",
                    "enabled": True,
                    "maxPerRun": 10,
                }
            ]
            (tmp / "config" / "sources.json").write_text(json.dumps(sources), encoding="utf-8")
            (tmp / "data" / "index.json").write_text("{}", encoding="utf-8")

            now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            community = [
                {
                    "id": "comm-review-01",
                    "url": "https://clean.example.com/code-review-shortcuts",
                    "originalLang": "en",
                    "title": {"en": "GitHub pull request review keyboard shortcuts"},
                    "summary": {"en": "Use keyboard shortcuts to speed up code review sessions in GitHub."},
                    "submittedBy": "AdminTester",
                    "sourceName": "Community",
                    "tags": ["dev"],
                    "publishedAt": now_iso,
                    "approvedAt": now_iso,
                },
                {
                    "id": "comm-sale-02",
                    "url": "https://clean.example.com/pos-sale-terminal-shortcuts",
                    "originalLang": "en",
                    "title": {"en": "Point of sale Linux terminal recovery checklist"},
                    "summary": {"en": "Restore frozen point of sale kiosks safely without rebooting the host."},
                    "submittedBy": "AdminTester",
                    "sourceName": "Community",
                    "tags": ["linux"],
                    "publishedAt": now_iso,
                    "approvedAt": now_iso,
                },
                {
                    "id": "comm-spam-03",
                    "url": "https://spam-domain.invalid/free-keys",
                    "originalLang": "en",
                    "title": {"en": "How to optimize Windows memory usage"},
                    "summary": {"en": "Clean tip hosted on a hard-blocked spam domain."},
                    "submittedBy": "Spammer",
                    "sourceName": "SpamSite",
                    "tags": ["windows"],
                    "publishedAt": now_iso,
                    "approvedAt": now_iso,
                },
            ]
            (tmp / "data" / "community.json").write_text(json.dumps(community), encoding="utf-8")

            os.chdir(tmp)
            try:
                with (
                    patch.object(run_pipeline, "DATA_DIR", tmp / "data"),
                    patch.object(run_pipeline, "INDEX_PATH", tmp / "data" / "index.json"),
                    patch.object(run_pipeline, "STATE_PATH", tmp / "data" / "state.json"),
                    patch.object(run_pipeline, "COMMUNITY_PATH", tmp / "data" / "community.json"),
                    patch.object(run_pipeline, "HEALTH_PATH", tmp / "data" / "health.json"),
                    patch.object(filters, "REJECTED_LOG", tmp / "data" / "logs" / "rejected.jsonl"),
                    patch.object(translate, "CACHE_FILE", tmp / "data" / "cache" / "translations.json"),
                    patch.object(run_pipeline, "fetch_feed_items", return_value=[]),
                    patch.object(run_pipeline, "batch_translate_pending"),
                    patch.object(run_pipeline, "load_cache", return_value={}),
                    patch.object(run_pipeline, "save_cache"),
                    patch("time.sleep"),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    run_pipeline.main()
            finally:
                os.chdir(orig_cwd)

            saved = json.loads((tmp / "data" / "index.json").read_text(encoding="utf-8"))
            self.assertIn("comm-review-01", saved, "Admin-approved community item with 'review' was dropped!")
            self.assertIn(
                "comm-sale-02",
                saved,
                "Admin-approved community item with 'sale' was silently dropped by keyword blocklist!",
            )
            self.assertNotIn("comm-spam-03", saved, "Hard-blocked spam domain was NOT blocked!")

    def test_qa_catches_empty_summary_and_empty_summary_dict(self):
        # Empty string summary
        bad_empty = _make_valid_qa_item("bad-empty-summ", summary={"en": "", "vi": "Tóm tắt tiếng Việt."})
        code, _ = _run_qa_on_items({"bad-empty-summ": bad_empty})
        self.assertEqual(code, 1, "qa.py failed to reject empty summary string")

        # Empty dict summary: {} (loop runs 0 times!)
        bad_dict = _make_valid_qa_item("bad-empty-dict", summary={}, translated={})
        code_dict, _ = _run_qa_on_items({"bad-empty-dict": bad_dict})
        self.assertEqual(code_dict, 1, "qa.py failed to reject empty summary dict {}!")

    def test_qa_catches_non_iso_published_at(self):
        bad = _make_valid_qa_item("bad-date", published_at="10/16/2026 8:42:00\u202fAM")
        code, _ = _run_qa_on_items({"bad-date": bad})
        self.assertEqual(code, 1, "qa.py failed to reject non-ISO published_at")

    def test_qa_catches_url_only_summary_and_trailing_punctuation_variant(self):
        bad1 = _make_valid_qa_item(
            "bad-url-summ",
            summary={"en": "https://youtu.be/abc", "vi": "Tóm tắt tiếng Việt dài hơn mười lăm ký tự."},
            translated={},
        )
        code1, _ = _run_qa_on_items({"bad-url-summ": bad1})
        self.assertEqual(code1, 1, "qa.py failed to reject bare URL-only summary")

        bad2 = _make_valid_qa_item(
            "bad-url-punct",
            summary={"en": "https://youtu.be/abc .", "vi": "Tóm tắt tiếng Việt dài hơn mười lăm ký tự."},
            translated={},
        )
        code2, _ = _run_qa_on_items({"bad-url-punct": bad2})
        self.assertEqual(code2, 1, "qa.py failed to reject URL-only summary with trailing punctuation!")

    def test_qa_catches_false_machine_translation_and_verbatim_copy(self):
        # False machine summary (VI summary labeled en: machine)
        false_mt = _make_valid_qa_item(
            "bad-false-mt",
            original_lang="vi",
            title={
                "vi": "Oppo Find X10 Pro Max có ba camera 200MP",
                "en": "Oppo Find X10 Pro Max features triple 200MP cameras",
            },
            summary={
                "vi": "Oppo Find X10 Pro Max là điện thoại đầu tiên trang bị ba camera sau độ phân giải 200 megapixel.",
                "en": "Oppo Find X10 Pro Max là điện thoại đầu tiên trang bị ba camera sau độ phân giải 200 megapixel.",
            },
            translated={"en": "machine"},
        )
        code1, _ = _run_qa_on_items({"bad-false-mt": false_mt})
        self.assertEqual(code1, 1, "qa.py failed to catch wrong-language machine summary")

        # Verbatim copy labeled machine
        verbatim_mt = _make_valid_qa_item(
            "bad-verbatim-mt",
            original_lang="en",
            title={
                "en": "How to configure WireGuard VPN on Ubuntu",
                "vi": "How to configure WireGuard VPN on Ubuntu",
            },
            summary={
                "en": "Install wireguard-tools and generate private keys to set up a fast encrypted tunnel.",
                "vi": "Install wireguard-tools and generate private keys to set up a fast encrypted tunnel.",
            },
            translated={"vi": "machine"},
        )
        code2, _ = _run_qa_on_items({"bad-verbatim-mt": verbatim_mt})
        self.assertEqual(code2, 1, "qa.py failed to catch verbatim machine copy")

    def test_qa_catches_invalid_key_points_and_svg_slash_evasion(self):
        invalid_kp_cases = [
            ("kp-html", {"en": ["Run <script>alert(1)</script> now"]}),
            ("kp-svg-slash", {"en": ["<svg/onload=alert(1)>"]}),
            ("kp-too-long", {"en": ["A" * 201]}),
            ("kp-too-many", {"en": ["One", "Two", "Three", "Four", "Five"]}),
            ("kp-empty-list", {"en": []}),
        ]
        for cid, kp_val in invalid_kp_cases:
            bad = _make_valid_qa_item(cid, key_points=kp_val)
            code, _ = _run_qa_on_items({cid: bad})
            self.assertEqual(code, 1, f"qa.py failed to reject invalid key_points ({cid}): {kp_val!r}")

    def test_qa_catches_raw_html_xss_in_title_and_summary(self):
        # SPEC.md §2: no raw HTML tags in title/summary
        bad_title_xss = _make_valid_qa_item(
            "bad-title-xss",
            title={
                "en": "<svg onload=alert(1)>How to fix Wi-Fi on Windows",
                "vi": "Cách sửa lỗi Wi-Fi trên Windows",
            },
        )
        code_t, _ = _run_qa_on_items({"bad-title-xss": bad_title_xss})
        self.assertEqual(code_t, 1, "qa.py failed to reject raw HTML XSS tag in title!")

        bad_summ_xss = _make_valid_qa_item(
            "bad-summ-xss",
            summary={
                "en": "<script>alert(1)</script>Reset network stack cleanly in Windows.",
                "vi": "Đặt lại cấu hình mạng sạch sẽ trên Windows.",
            },
        )
        code_s, _ = _run_qa_on_items({"bad-summ-xss": bad_summ_xss})
        self.assertEqual(code_s, 1, "qa.py failed to reject raw HTML XSS tag in summary!")

    def test_qa_catches_javascript_url_in_index_item(self):
        bad_js_url = _make_valid_qa_item("bad-js-url", url="javascript:alert(1)")
        code_u, _ = _run_qa_on_items({"bad-js-url": bad_js_url})
        self.assertEqual(code_u, 1, "qa.py failed to reject javascript: URL in index item!")

    def test_community_ingestion_sanitizes_html_and_rejects_javascript_urls(self):
        """Community JSON entries must still enforce URL scheme safety and HTML sanitization."""
        orig_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "config").mkdir()
            (tmp / "data" / "logs").mkdir(parents=True)
            shutil.copy2(REPO_ROOT / "config" / "blocklist.yml", tmp / "config" / "blocklist.yml")
            shutil.copy2(REPO_ROOT / "config" / "categories.yml", tmp / "config" / "categories.yml")
            sources = [
                {
                    "id": "itsfoss",
                    "name": "It's FOSS",
                    "type": "rss",
                    "url": "https://itsfoss.com/feed/",
                    "site_url": "https://itsfoss.com",
                    "lang": "en",
                    "categories": ["linux"],
                    "trust": 4,
                    "kind": "tips",
                    "contentType": "article",
                    "enabled": True,
                    "maxPerRun": 10,
                }
            ]
            (tmp / "config" / "sources.json").write_text(json.dumps(sources), encoding="utf-8")
            (tmp / "data" / "index.json").write_text("{}", encoding="utf-8")

            now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            community = [
                {
                    "id": "comm-js-url",
                    "url": "javascript:alert(document.domain)",
                    "originalLang": "en",
                    "title": {"en": "How to audit browser storage"},
                    "summary": {"en": "Inspect local storage cleanly."},
                    "submittedBy": "Mallory",
                    "tags": ["browser"],
                    "publishedAt": now_iso,
                },
                {
                    "id": "comm-html-xss",
                    "url": "https://clean.example.com/safe-tip",
                    "originalLang": "en",
                    "title": {"en": "<svg onload=alert(1)>How to tune DNS caching"},
                    "summary": {"en": "<script>alert(1)</script>Flush &amp; verify DNS resolver settings."},
                    "submittedBy": "Alice",
                    "tags": ["linux"],
                    "publishedAt": now_iso,
                },
            ]
            (tmp / "data" / "community.json").write_text(json.dumps(community), encoding="utf-8")

            os.chdir(tmp)
            try:
                with (
                    patch.object(run_pipeline, "DATA_DIR", tmp / "data"),
                    patch.object(run_pipeline, "INDEX_PATH", tmp / "data" / "index.json"),
                    patch.object(run_pipeline, "STATE_PATH", tmp / "data" / "state.json"),
                    patch.object(run_pipeline, "COMMUNITY_PATH", tmp / "data" / "community.json"),
                    patch.object(run_pipeline, "HEALTH_PATH", tmp / "data" / "health.json"),
                    patch.object(filters, "REJECTED_LOG", tmp / "data" / "logs" / "rejected.jsonl"),
                    patch.object(translate, "CACHE_FILE", tmp / "data" / "cache" / "translations.json"),
                    patch.object(run_pipeline, "fetch_feed_items", return_value=[]),
                    patch.object(run_pipeline, "batch_translate_pending"),
                    patch.object(run_pipeline, "load_cache", return_value={}),
                    patch.object(run_pipeline, "save_cache"),
                    patch("time.sleep"),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    run_pipeline.main()
            finally:
                os.chdir(orig_cwd)

            saved = json.loads((tmp / "data" / "index.json").read_text(encoding="utf-8"))
            self.assertNotIn("comm-js-url", saved, "run_pipeline ingested javascript: URL from community.json!")
            if "comm-html-xss" in saved:
                t = saved["comm-html-xss"]["title"]["en"]
                s = saved["comm-html-xss"]["summary"]["en"]
                self.assertNotIn("<svg", t.lower(), f"Unsanitized XSS title ingested from community.json: {t!r}")
                self.assertNotIn("<script", s.lower(), f"Unsanitized XSS summary ingested from community.json: {s!r}")

    def test_live_index_json_invariants(self):
        index_path = REPO_ROOT / "data" / "index.json"
        self.assertTrue(index_path.exists(), "data/index.json does not exist")
        data = json.loads(index_path.read_text(encoding="utf-8"))
        visible = [it for it in data.values() if not it.get("hidden")]
        self.assertGreater(len(visible), 0, "No visible items in data/index.json")

        now_limit = datetime.now(timezone.utc) + timedelta(days=2)
        non_iso = []
        future_dates = []
        stale_attempts = []
        bad_urls = []

        for it in visible:
            iid = it.get("id", "unknown")
            pub = str(it.get("published_at") or "").strip()
            if not ISO_UTC_RE.match(pub):
                non_iso.append((iid, pub))
            else:
                dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                if dt > now_limit:
                    future_dates.append((iid, pub))

            trans = it.get("translated") or {}
            attempts = it.get("translate_attempts") or {}
            retries = it.get("translate_next_retry") or {}
            for lang in set(attempts.keys()) | set(retries.keys()):
                if trans.get(lang) == "machine":
                    stale_attempts.append((iid, lang))

            url = str(it.get("url") or "").strip()
            scheme = urlsplit(url).scheme.lower()
            if scheme not in ("http", "https"):
                bad_urls.append((iid, url))

        self.assertEqual(non_iso, [], f"Visible items with non-ISO published_at: {non_iso[:5]}")
        self.assertEqual(future_dates, [], f"Visible items with far-future published_at: {future_dates[:5]}")
        self.assertEqual(
            stale_attempts,
            [],
            f"Already-translated visible items with stale translate_attempts/next_retry: {stale_attempts[:5]}",
        )
        self.assertEqual(bad_urls, [], f"Visible items with non-HTTP(S) URLs: {bad_urls[:5]}")

    def test_live_sources_json_invariants(self):
        sources_path = REPO_ROOT / "config" / "sources.json"
        sources = json.loads(sources_path.read_text(encoding="utf-8"))
        enabled = [s for s in sources if s.get("enabled")]
        self.assertGreater(len(enabled), 0)

        bad_site_urls = []
        raw_feed_tokens = ("/rss", "/feed", ".rss", ".xml", ".atom", "/api/")
        for src in enabled:
            su = str(src.get("site_url") or "").strip()
            parsed = urlsplit(su)
            if parsed.scheme != "https" or not parsed.netloc:
                bad_site_urls.append((src["id"], su, "not valid https://"))
                continue
            lower_path = parsed.path.lower()
            if any(tok in lower_path for tok in raw_feed_tokens):
                bad_site_urls.append((src["id"], su, "contains raw RSS/Atom/API path"))

        self.assertEqual(bad_site_urls, [], f"Enabled sources with invalid site_url: {bad_site_urls}")

    def test_live_health_json_schema_invariants(self):
        health_path = REPO_ROOT / "data" / "health.json"
        self.assertTrue(health_path.exists(), "data/health.json does not exist")
        health = json.loads(health_path.read_text(encoding="utf-8"))

        self.assertIn("updated_at", health)
        self.assertIn("sources", health)
        self.assertRegex(str(health["updated_at"]), ISO_UTC_RE)
        self.assertIsInstance(health["sources"], dict)

        enabled_ids = {
            s["id"]
            for s in json.loads((REPO_ROOT / "config" / "sources.json").read_text(encoding="utf-8"))
            if s.get("enabled")
        }
        self.assertEqual(
            set(health["sources"].keys()),
            enabled_ids,
            "data/health.json sources mismatch enabled sources in config/sources.json",
        )

        required_fields = {
            "status",
            "failure_count",
            "last_success",
            "last_failure",
            "paused_until",
            "last_error",
        }
        for sid, entry in health["sources"].items():
            self.assertEqual(set(entry.keys()), required_fields, f"Schema mismatch on health source {sid}")
            self.assertIn(entry["status"], {"ok", "degraded", "paused"}, f"Bad status for {sid}")
            self.assertIsInstance(entry["failure_count"], int)
            self.assertGreaterEqual(entry["failure_count"], 0)
            for ts_key in ("last_success", "last_failure", "paused_until"):
                val = entry[ts_key]
                if val is not None:
                    self.assertRegex(str(val), ISO_UTC_RE, f"Non-ISO {ts_key} on {sid}: {val!r}")
            if entry["last_error"] is not None:
                self.assertIsInstance(entry["last_error"], str)
            if entry["status"] == "ok":
                self.assertEqual(entry["failure_count"], 0, f"ok source {sid} has non-zero failure_count")
                self.assertIsNone(entry["paused_until"], f"ok source {sid} has paused_until set")
            if entry["status"] == "paused":
                self.assertIsNotNone(entry["paused_until"], f"paused source {sid} missing paused_until")


if __name__ == "__main__":
    unittest.main()
