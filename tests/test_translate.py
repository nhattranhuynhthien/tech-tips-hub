# tests/test_translate.py
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import translate
from translate import (
    looks_vietnamese,
    looks_english,
    is_mixed,
    is_valid_translation,
    sanitize_key_points,
    normalize_key_points_map,
    parse_gemini_response,
    load_cache,
    GeminiTranslator,
    ArgosOfflineTranslator,
    CompositeTranslator,
    process_item_bilingual,
    batch_translate_pending,
    _can_attempt_translation,
    _record_translation_failure,
)
from qa import validate_key_points, validate_machine_translation
from run_pipeline import sync_item_key_points, diversify, write_health_report
from filters import accept, is_howto_match
from dedupe import is_blocked, canonical_url
from classify import classify, VALID_CATEGORIES
from textclean import clean_text, clean_title
from score import parse_published_time, normalize_published_iso
from fetch import parse_hn_summary


class TestTranslateModule(unittest.TestCase):
    def test_mixed_language_detection(self):
        """Phát hiện các câu trộn ngữ pháp giữa tiếng Anh và tiếng Việt."""
        self.assertTrue(is_mixed("Cách a Salon Website Gets Built in Lovable"))
        self.assertTrue(is_mixed("This Newly Proposed Linux Filesystem Can Khắc phục Corrupted Data"))
        self.assertTrue(is_mixed("How to Tối ưu hóa Windows for gaming"))
        self.assertFalse(is_mixed("Hướng dẫn cấu hình SSH an toàn trên máy chủ Ubuntu"))
        self.assertFalse(is_mixed("How to configure SSH securely on Ubuntu server"))
        self.assertFalse(is_mixed("Thủ thuật tăng tốc máy tính Windows 11 hiệu quả"))

    def test_language_detection(self):
        """Kiểm tra nhận diện tiếng Việt và tiếng Anh chuẩn (kể cả khi giữ tên riêng)."""
        self.assertTrue(looks_vietnamese("Thủ thuật tối ưu hóa Windows 11"))
        self.assertFalse(looks_vietnamese("How to speed up Windows 11 with simple tweaks"))

        self.assertTrue(looks_english("How to speed up Windows 11 with simple tweaks"))
        self.assertTrue(looks_english("According to IT之家, Sony did not launch PlayStation as revenge against Nintendo"))
        self.assertTrue(looks_english("How Tinh tế built a fresh air supply solution for its workspace"))
        self.assertFalse(looks_english("Thủ thuật tối ưu hóa Windows 11"))
        self.assertFalse(looks_english("苹果发布新款 MacBook"))

    def test_translator_interface(self):
        """Kiểm tra tính nhất quán của Translator interface."""
        gemini = GeminiTranslator()
        argos = ArgosOfflineTranslator()
        comp = CompositeTranslator()

        self.assertTrue(hasattr(gemini, "translate_batch"))
        self.assertTrue(hasattr(argos, "translate_batch"))
        self.assertTrue(hasattr(comp, "translate_batch"))

    def test_chinese_item_gets_both_translations(self):
        class FakeTranslator:
            def __init__(self):
                self.calls = []

            def translate_batch(self, items, source_lang, target_lang):
                self.calls.append((source_lang, target_lang))
                if target_lang == "vi":
                    title, summary = "Apple ra mắt máy tính mới", "Sản phẩm mới có chip nhanh hơn và thời lượng pin dài hơn."
                else:
                    title, summary = "Apple launches a new computer", "The new product has a faster chip and longer battery life."
                return [{"id": item["id"], "title": title, "summary": summary} for item in items]

        translator = FakeTranslator()
        item = {
            "id": "zh-item-1", "original_lang": "zh-CN", "title": {"zh-CN": "苹果发布新款 MacBook"},
            "summary": {"zh-CN": "苹果今天发布了搭载新芯片的笔记本电脑。"}, "score": 0.8,
        }
        cache = {}
        batch_translate_pending([item], cache, translator=translator, max_items=4)

        self.assertEqual(translator.calls, [("zh-CN", "vi"), ("zh-CN", "en")])
        self.assertEqual(item["translated"]["vi"], "machine")
        self.assertEqual(item["translated"]["en"], "machine")
        self.assertEqual(item["title"]["zh-CN"], "苹果发布新款 MacBook")
        self.assertIn("zh-item-1", cache)

    def test_chinese_translation_failure_keeps_original_and_skips_cache(self):
        translator = Mock()
        translator.translate_batch.return_value = []
        cache = {}
        item = {
            "id": "zh-item-2", "original_lang": "zh-CN", "title": {"zh-CN": "苹果发布新款 MacBook"},
            "summary": {"zh-CN": "苹果今天发布了搭载新芯片的笔记本电脑。"}, "score": 0.8,
        }
        batch_translate_pending([item], cache, translator=translator, max_items=4)

        self.assertEqual(item["title"]["vi"], item["title"]["zh-CN"])
        self.assertEqual(item["title"]["en"], item["title"]["zh-CN"])
        self.assertFalse(item["translated"]["vi"])
        self.assertFalse(item["translated"]["en"])
        self.assertNotIn("zh-item-2", cache)

    def test_fallback_when_untranslated(self):
        """Giữ nguyên bản gốc nếu translator không trả kết quả, không gọi dịch vụ bên ngoài."""
        translator = Mock()
        translator.translate_batch.return_value = []
        cache = {}
        title, summ, trans = process_item_bilingual(
            item_id="test_sample_001",
            orig_title="How to configure Docker containers on Linux",
            orig_summary="A complete step by step tutorial to setup Docker on Linux distributions.",
            orig_lang="en",
            cache=cache,
            translator=translator
        )

        self.assertNotEqual(trans.get("vi"), "machine")
        self.assertEqual(title["en"], "How to configure Docker containers on Linux")
        self.assertEqual(title["vi"], "How to configure Docker containers on Linux")

    def test_filters_word_boundaries_and_cjk_blocklist(self):
        """Không chặn nhầm từ con tiếng Anh ('ideal'/'Salesforce'), nhưng chặn chuẩn từ khóa tiếng Trung viết liền."""
        ok, _ = accept(
            {
                "raw_title": "How to configure ideal Linux settings for Salesforce CLI",
                "raw_summary": "Ideal setup steps when dealing with multiple environments.",
            },
            {"id": "linuxhandbook", "kind": "tips"},
            enable_logging=False,
        )
        self.assertTrue(ok)

        blocked_zh, reason = accept(
            {
                "raw_title": "小米上线双十一 8 折手机电池换新服务",
                "raw_summary": "京东双11限时优惠活动现已开启",
            },
            {"id": "ithome-cn", "kind": "news", "allowNews": True},
            enable_logging=False,
        )
        self.assertFalse(blocked_zh)
        self.assertEqual(reason, "blocklist-title")

        self.assertTrue(is_blocked("京东双11限时优惠活动", "", "https://ithome.com/1", {"keywords": ["优惠"]}))

    def test_classify_never_returns_invalid_category(self):
        cats1 = classify("Samsung flow and s26", "Quick question", fallback=["android"])
        self.assertEqual(cats1, ["android"])
        cats2 = classify("Unrelated tech note", "Short note", fallback=[])
        self.assertTrue(all(c in VALID_CATEGORIES for c in cats2))

    def test_long_cjk_translation_is_clamped_within_qa_limit(self):
        class LongTranslator:
            def translate_batch(self, items, source_lang, target_lang):
                if target_lang == "vi":
                    title = "Bản dịch tiếng Việt có độ dài hợp lệ cho bài viết công nghệ"
                    summary = ("Nội dung tóm tắt chi tiết về thiết bị phần cứng và hệ điều hành mới " * 12).strip()
                else:
                    title = "Valid English translated title for technology article"
                    summary = ("Detailed summary about the new hardware device and operating system update " * 12).strip()
                return [{"id": item["id"], "title": title, "summary": summary} for item in items]

        item = {
            "id": "zh-long-1", "original_lang": "zh-CN",
            "title": {"zh-CN": "长摘要测试"}, "summary": {"zh-CN": "测试内容" * 60}, "score": 0.9,
        }
        batch_translate_pending([item], {}, translator=LongTranslator(), max_items=4)
        self.assertLessEqual(len(item["summary"]["vi"]), 325)
        self.assertLessEqual(len(item["summary"]["en"]), 325)

    def test_textclean_preserves_generics_and_comparisons_while_stripping_style(self):
        self.assertEqual(
            clean_title("Why C++ std::vector&lt;int&gt; beats std::list&lt;int&gt;"),
            "Why C++ std::vector<int> beats std::list<int>",
        )
        self.assertEqual(
            clean_text("Check if x < 10 and y > 20 in bash"),
            "Check if x < 10 and y > 20 in bash",
        )
        self.assertEqual(
            clean_text("<style>.ad{display:none}</style><p>Real tip text here</p>"),
            "Real tip text here",
        )
        self.assertEqual(
            clean_text("&lt;p&gt;Double encoded paragraph&lt;/p&gt;"),
            "Double encoded paragraph",
        )

    def test_naive_datetime_is_treated_as_utc(self):
        dt_naive = parse_published_time("2026-10-29T10:00:00")
        dt_utc = parse_published_time("2026-10-29T10:00:00Z")
        self.assertEqual(dt_naive, dt_utc)

    def test_hn_summary_is_english(self):
        pts, c_url, c_cnt, summ = parse_hn_summary(
            "Points: 239 Comments URL: https://news.ycombinator.com/item?id=1 # Comments: 77"
        )
        self.assertEqual(pts, 239)
        self.assertEqual(c_cnt, 77)
        self.assertTrue(looks_english(summ))
        self.assertFalse(looks_vietnamese(summ))

    def test_gemini_prompt_requests_natural_vietnamese_and_key_points(self):
        prompt_vi = GeminiTranslator.build_prompt(
            [{"id": "tip-1", "title": "How to speed up Git", "summary": "Enable fsmonitor for faster status."}],
            source_lang="en",
            target_lang="vi",
        )
        self.assertIn("của nó", prompt_vi)
        self.assertIn("key_points", prompt_vi)
        self.assertIn("UNTRUSTED DATA RULE", prompt_vi)

    def test_gemini_parser_with_and_without_key_points(self):
        fenced_payload = """```json
        [
          {
            "id": "tip-1",
            "title": "Cách tăng tốc Git trên dự án lớn",
            "summary": "Bật fsmonitor và commit-graph để tăng tốc git status.",
            "key_points": [
              "- Chạy git config core.fsmonitor true để giảm độ trễ.",
              "• Bật commit-graph giúp git log phản hồi nhanh hơn."
            ]
          },
          {
            "id": "tip-2",
            "title": "Mẹo dùng tmux hiệu quả",
            "summary": "Chia cửa sổ làm việc bằng Ctrl+B."
          },
          {
            "id": "tip-3",
            "title": "Tối ưu RAM cho Chrome",
            "summary": "Bật Memory Saver trong Settings.",
            "key_points": []
          }
        ]
        ```"""
        parsed = parse_gemini_response(fenced_payload, target_lang="vi")
        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[0]["id"], "tip-1")
        self.assertEqual(
            parsed[0]["key_points"],
            [
                "Chạy git config core.fsmonitor true để giảm độ trễ.",
                "Bật commit-graph giúp git log phản hồi nhanh hơn.",
            ],
        )
        self.assertNotIn("key_points", parsed[1])
        self.assertNotIn("key_points", parsed[2])

        wrapped_payload = json.dumps({
            "items": [
                {
                    "id": "tip-4",
                    "title": "Fast SSH setup",
                    "summary": "Use ed25519 keys.",
                    "key_points": ["Generate keys with ssh-keygen -t ed25519"],
                }
            ]
        })
        wrapped_parsed = GeminiTranslator.parse_response(wrapped_payload, target_lang="en")
        self.assertEqual(len(wrapped_parsed), 1)
        self.assertEqual(wrapped_parsed[0]["key_points"], ["Generate keys with ssh-keygen -t ed25519"])

    def test_gemini_parser_handles_malformed_and_invalid_responses(self):
        self.assertEqual(parse_gemini_response(""), [])
        self.assertEqual(parse_gemini_response("not valid json"), [])
        self.assertEqual(parse_gemini_response("{}"), [])
        mixed_entries = json.dumps([
            "not-a-dict",
            {"title": "Missing id"},
            {
                "id": "ok-1",
                "title": "Valid entry",
                "summary": "Summary",
                "key_points": "not-a-list",
            },
        ])
        parsed = parse_gemini_response(mixed_entries, target_lang="en")
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["id"], "ok-1")
        self.assertNotIn("key_points", parsed[0])

    def test_gemini_translate_batch_parses_mocked_api_response(self):
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps([
                                    {
                                        "id": "g-1",
                                        "title": "Mẹo tối ưu Docker image nhỏ gọn",
                                        "summary": "Dùng multi-stage build và alpine để giảm dung lượng image.",
                                        "key_points": [
                                            "Tách bước build và runtime bằng multi-stage Dockerfile",
                                            "Ưu tiên base image nhẹ như alpine hoặc distroless",
                                        ],
                                    }
                                ])
                            }
                        ]
                    }
                }
            ]
        }

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret-key", "GEMINI_MODEL": "gemini-2.5-flash"}):
            translator = GeminiTranslator()
            with patch("translate.requests.Session.post", return_value=mock_resp) as mock_post:
                results = translator.translate_batch(
                    [{"id": "g-1", "title": "Shrink Docker images", "summary": "Use multi-stage builds."}],
                    source_lang="en",
                    target_lang="vi",
                )
        self.assertEqual(len(results), 1)
        self.assertEqual(len(results[0]["key_points"]), 2)
        called_headers = mock_post.call_args.kwargs["headers"]
        self.assertEqual(called_headers.get("x-goog-api-key"), "test-secret-key")
        self.assertNotIn("test-secret-key", mock_post.call_args.args[0])

    def test_sanitize_key_points_clamping_sanitization_and_dedup(self):
        exact_160 = "a" * 160
        long_sentence = ("Sử dụng tổ hợp phím Ctrl+Shift+P để mở nhanh bảng lệnh trong VS Code " * 5).strip()
        long_no_space = "x" * 220

        raw = [
            "<p><b>Dùng</b> <code>Ctrl+Shift+T</code> mở lại tab vừa đóng</p>",
            "&lt;b&gt;Dùng&lt;/b&gt; Ctrl+Shift+T mở lại tab vừa đóng",  # duplicate after clean
            "1. " + long_sentence,
            "- " + long_no_space,
            "Điểm thứ tư phải bị cắt bỏ",
            "",
            123,
            "Cách a Salon Website Gets Built in Lovable",  # mixed language
        ]
        cleaned = sanitize_key_points(raw, target_lang="vi")
        self.assertEqual(len(cleaned), 3)
        self.assertEqual(cleaned[0], "Dùng Ctrl+Shift+T mở lại tab vừa đóng")
        for pt in cleaned:
            self.assertLessEqual(len(pt), 160)
            self.assertNotIn("<", pt)
            self.assertNotIn(">", pt)

        self.assertEqual(sanitize_key_points([exact_160]), [exact_160])
        self.assertEqual(
            sanitize_key_points(["Check x < 10 and y > 20 in bash", "<script>alert(1)</script>Safe tip"]),
            ["Check x < 10 and y > 20 in bash", "Safe tip"],
        )
        self.assertEqual(
            normalize_key_points_map({"vi": ["Mẹo hay"], "en": [], "123": ["bad"], "fr": ["  "]}),
            {"vi": ["Mẹo hay"]},
        )

    def test_batch_translate_preserves_key_points_and_omits_when_absent(self):
        class KeyPointsTranslator:
            def translate_batch(self, items, source_lang, target_lang):
                out = []
                for it in items:
                    if target_lang == "vi":
                        out.append({
                            "id": it["id"],
                            "title": "Cách dọn bộ nhớ đệm Docker an toàn",
                            "summary": "Dùng docker system prune để giải phóng dung lượng ổ cứng.",
                            "key_points": [
                                "Chạy docker system df để xem dung lượng đang chiếm",
                                "Dùng docker image prune xóa image không dùng tới",
                                "Tránh cờ --volumes nếu chưa sao lưu dữ liệu",
                                "Ý thứ 4 sẽ bị loại bỏ tự động",
                            ],
                        })
                    else:
                        out.append({
                            "id": it["id"],
                            "title": "How to clean Docker cache safely",
                            "summary": "Use docker system prune to free disk space.",
                            "key_points": [
                                "Inspect disk usage with docker system df",
                                "Remove unused images with docker image prune",
                            ],
                        })
                return out

        cache = {}
        en_item = {
            "id": "kp-en-1",
            "original_lang": "en",
            "title": {"en": "Clean Docker cache", "vi": "Clean Docker cache"},
            "summary": {"en": "Use docker prune.", "vi": "Use docker prune."},
            "score": 0.9,
        }
        zh_item = {
            "id": "kp-zh-1",
            "original_lang": "zh-CN",
            "title": {"zh-CN": "清理 Docker 缓存"},
            "summary": {"zh-CN": "使用 docker prune 清理空间"},
            "score": 0.9,
        }
        batch_translate_pending([en_item, zh_item], cache, translator=KeyPointsTranslator(), max_items=10)

        self.assertEqual(len(en_item["key_points"]["vi"]), 3)
        self.assertNotIn("en", en_item["key_points"])
        self.assertEqual(cache["kp-en-1"]["key_points"], en_item["key_points"])

        self.assertEqual(len(zh_item["key_points"]["vi"]), 3)
        self.assertEqual(len(zh_item["key_points"]["en"]), 2)
        self.assertEqual(cache["kp-zh-1"]["key_points"], zh_item["key_points"])

        # Fresh item restored from cache gets key_points cleanly
        reloaded = {
            "id": "kp-en-1",
            "original_lang": "en",
            "title": {"en": "Clean Docker cache", "vi": "Clean Docker cache"},
            "summary": {"en": "Use docker prune.", "vi": "Use docker prune."},
        }
        batch_translate_pending([reloaded], cache, translator=Mock(), max_items=10)
        self.assertEqual(reloaded["key_points"], cache["kp-en-1"]["key_points"])

        # Fallback translator without key_points must omit key_points cleanly
        class PlainTranslator:
            def translate_batch(self, items, source_lang, target_lang):
                return [{
                    "id": it["id"],
                    "title": "Mẹo tối ưu tốc độ khởi động Windows",
                    "summary": "Tắt ứng dụng khởi động cùng hệ thống trong Task Manager.",
                } for it in items]

        plain_item = {
            "id": "plain-1",
            "original_lang": "en",
            "title": {"en": "Speed up Windows boot", "vi": "Speed up Windows boot"},
            "summary": {"en": "Disable startup apps.", "vi": "Disable startup apps."},
            "score": 0.8,
        }
        plain_cache = {}
        batch_translate_pending([plain_item], plain_cache, translator=PlainTranslator(), max_items=5)
        self.assertNotIn("key_points", plain_item)
        self.assertNotIn("key_points", plain_cache["plain-1"])

    def test_cache_backwards_compatibility_and_google_fallback(self):
        legacy_cache_data = {
            "legacy-1": {
                "title": {"en": "Speed up Linux", "vi": "Tăng tốc Linux hiệu quả"},
                "summary": {"en": "Enable zram.", "vi": "Bật zram để tối ưu bộ nhớ."},
                "translated": {"vi": "machine"},
            },
            "with-empty-kp": {
                "title": {"en": "Git tips", "vi": "Mẹo dùng Git nhanh"},
                "summary": {"en": "Use aliases.", "vi": "Dùng alias cho lệnh ngắn hơn."},
                "translated": {"vi": "machine"},
                "key_points": {"vi": []},
            },
            "with-valid-kp": {
                "title": {"en": "SSH keys", "vi": "Cấu hình khóa SSH an toàn"},
                "summary": {"en": "Use ed25519.", "vi": "Dùng khóa ed25519 thay RSA."},
                "translated": {"vi": "machine"},
                "key_points": {"vi": ["<b>Dùng</b> ssh-keygen -t ed25519"]},
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "translations.json"
            cache_path.write_text(json.dumps(legacy_cache_data, ensure_ascii=False), encoding="utf-8")
            with patch.object(translate, "CACHE_FILE", cache_path):
                loaded = load_cache()

        self.assertIn("legacy-1", loaded)
        self.assertNotIn("key_points", loaded["legacy-1"])
        self.assertIn("with-empty-kp", loaded)
        self.assertNotIn("key_points", loaded["with-empty-kp"])
        self.assertEqual(loaded["with-valid-kp"]["key_points"], {"vi": ["Dùng ssh-keygen -t ed25519"]})

        # process_item_bilingual keeps exact 3-tuple return value on legacy cache hit
        t, s, meta = process_item_bilingual(
            "legacy-1", "Speed up Linux", "Enable zram.", "en", loaded, translator=Mock()
        )
        self.assertEqual(t["vi"], "Tăng tốc Linux hiệu quả")
        self.assertEqual(s["vi"], "Bật zram để tối ưu bộ nhớ.")
        self.assertEqual(meta["vi"], "machine")

        # run_pipeline.sync_item_key_points preserves cached/translated key_points and drops empty ones
        item_a = {"id": "with-valid-kp"}
        sync_item_key_points(item_a, loaded["with-valid-kp"])
        self.assertEqual(item_a["key_points"], {"vi": ["Dùng ssh-keygen -t ed25519"]})

        item_b = {"id": "legacy-1", "key_points": {"vi": []}}
        sync_item_key_points(item_b, loaded["legacy-1"])
        self.assertNotIn("key_points", item_b)

        # CompositeTranslator falls back to GoogleWebTranslator when GEMINI_API_KEY is missing
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False):
            comp = CompositeTranslator()
            self.assertFalse(comp.gemini.is_available())
            comp.google_web.translate_batch = Mock(return_value=[
                {"id": "fb-1", "title": "Mẹo cấu hình SSH", "summary": "Dùng khóa SSH thay mật khẩu."}
            ])
            res = comp.translate_batch(
                [{"id": "fb-1", "title": "SSH config tip", "summary": "Use SSH keys."}],
                source_lang="en",
                target_lang="vi",
            )
            self.assertEqual(len(res), 1)
            self.assertNotIn("key_points", res[0])
            comp.google_web.translate_batch.assert_called_once()

    def test_qa_validate_key_points(self):
        # Absent key_points passes unchanged
        self.assertEqual(validate_key_points({"id": "no-kp"}), [])

        # Valid key_points (1-4 items, <=200 chars, math comparisons & generics allowed)
        valid_item = {
            "id": "valid-kp",
            "key_points": {
                "vi": ["Dùng tổ hợp Ctrl+Shift+T mở lại tab", "Bật Memory Saver trong cài đặt"],
                "en": [
                    "Prefer std::vector<int> over std::list<int>",
                    "Check x < 10 and y > 20 before running",
                    "Keep each takeaway concise",
                    "A" * 200,
                ],
            },
        }
        self.assertEqual(validate_key_points(valid_item), [])

        # Invalid shapes and violations
        invalid_cases = [
            {"id": "bad-none", "key_points": None},
            {"id": "bad-list", "key_points": ["not a dict"]},
            {"id": "bad-empty-dict", "key_points": {}},
            {"id": "bad-lang", "key_points": {"123": ["Invalid lang"]}},
            {"id": "bad-val-type", "key_points": {"vi": "not a list"}},
            {"id": "bad-empty-list", "key_points": {"vi": []}},
            {"id": "bad-too-many", "key_points": {"vi": ["1", "2", "3", "4", "5"]}},
            {"id": "bad-elem-type", "key_points": {"vi": [42]}},
            {"id": "bad-blank", "key_points": {"vi": ["   "]}},
            {"id": "bad-too-long", "key_points": {"en": ["x" * 201]}},
            {"id": "bad-html-b", "key_points": {"en": ["<b>Bold</b> takeaway"]}},
            {"id": "bad-html-script", "key_points": {"en": ["Run <script>alert(1)</script>"]}},
            {"id": "bad-html-link", "key_points": {"vi": ["Mở <a href='https://example.com'>liên kết</a>"]}},
            {"id": "bad-html-br", "key_points": {"en": ["Line 1<br/>Line 2"]}},
            {"id": "bad-html-close", "key_points": {"en": ["Unmatched </span> tag"]}},
        ]
        for case in invalid_cases:
            with self.subTest(case_id=case["id"]):
                errors = validate_key_points(case)
                self.assertTrue(len(errors) > 0, f"Expected QA errors for {case['id']}")

    def test_date_normalization_tuoitre_short_tz_and_struct(self):
        """Chuẩn hóa ngày kiểu Tuổi Trẻ (\\u202fAM/PM), offset ngắn +07, struct_time và chuỗi lỗi."""
        tz_vn = timezone(timedelta(hours=7))
        dt_am = parse_published_time("10/16/2026 8:42:00\u202fAM", default_tz=tz_vn)
        self.assertEqual(dt_am, datetime(2026, 10, 16, 1, 42, 0, tzinfo=timezone.utc))

        iso_am = normalize_published_iso("10/16/2026 8:42:00\u202fAM", default_offset_hours=7)
        self.assertEqual(iso_am, "2026-10-16T01:42:00+00:00")

        iso_pm = normalize_published_iso("11/5/2026 3:59:00\u00a0PM", default_offset_hours=7)
        self.assertEqual(iso_pm, "2026-11-05T08:59:00+00:00")

        # Offset 2 chữ số của GenK (+07) phải được hiểu là +07:00, KHÔNG phải +00:07
        iso_genk = normalize_published_iso("Sun, 08 Nov 2026 09:23:00 +07")
        self.assertEqual(iso_genk, "2026-11-08T02:23:00+00:00")

        # Dự phòng bằng time.struct_time của feedparser
        struct = time.struct_time((2026, 11, 10, 14, 30, 0, 1, 314, 0))
        self.assertEqual(normalize_published_iso("", parsed_struct=struct), "2026-11-10T14:30:00+00:00")

        # Chuỗi hoàn toàn không phân tích được trả về rỗng
        self.assertEqual(normalize_published_iso("not-a-valid-date"), "")

    def test_canonical_url_strips_all_utm_params(self):
        """Loại bỏ mọi tham số utm_* tương đồng với api/telegram.ts."""
        cleaned = canonical_url("https://example.com/post/?utm_id=99&utm_reader=rss&UTM_Custom=1&fbclid=abc&page=2")
        self.assertEqual(cleaned, "https://example.com/post?page=2")

    def test_batch_translate_skips_hidden_items(self):
        """batch_translate_pending phải bỏ qua tuyệt đối các bài hidden: True (cả EN/VI và ZH)."""
        translator = Mock()
        translator.translate_batch.return_value = [
            {
                "id": "vis-1",
                "title": "Cách tăng tốc khởi động Linux",
                "summary": "Tắt các dịch vụ không cần thiết để giảm thời gian khởi động hệ thống.",
            }
        ]
        items = [
            {
                "id": "hid-en",
                "hidden": True,
                "original_lang": "en",
                "title": {"en": "Hidden English tip", "vi": "Hidden English tip"},
                "summary": {"en": "Should never be sent to translator.", "vi": "Should never be sent to translator."},
                "score": 1.5,
                "howto": True,
            },
            {
                "id": "hid-zh",
                "hidden": True,
                "original_lang": "zh-CN",
                "title": {"zh-CN": "隐藏的中文文章"},
                "summary": {"zh-CN": "不应该消耗翻译配额。"},
                "score": 1.5,
                "howto": True,
            },
            {
                "id": "vis-1",
                "hidden": False,
                "original_lang": "en",
                "title": {"en": "How to speed up Linux boot", "vi": "How to speed up Linux boot"},
                "summary": {"en": "Disable unused services to boot faster.", "vi": "Disable unused services to boot faster."},
                "score": 0.8,
                "howto": True,
            },
        ]
        cache = {}
        batch_translate_pending(items, cache, translator=translator, max_items=10)

        self.assertEqual(translator.translate_batch.call_count, 1)
        sent_ids = [x["id"] for x in translator.translate_batch.call_args.args[0]]
        self.assertEqual(sent_ids, ["vis-1"])
        self.assertNotIn("hid-en", cache)
        self.assertNotIn("hid-zh", cache)
        self.assertEqual(items[2]["translated"]["vi"], "machine")

    def test_is_valid_translation_rejects_bad_outputs(self):
        """is_valid_translation phải từ chối bản sao nguyên văn, tóm tắt rỗng và tóm tắt sai ngôn ngữ."""
        # Bản sao nguyên văn giữa 2 ngôn ngữ khác nhau (case 6f7743a9465550a4)
        self.assertFalse(
            is_valid_translation(
                "Oppo Find X10 Pro Max - smartphone có ba camera 200 megapixel",
                "Oppo Find X10 Pro Max là điện thoại đầu tiên trang bị ba camera sau.",
                "Oppo Find X10 Pro Max - smartphone có ba camera 200 megapixel",
                "Oppo Find X10 Pro Max là điện thoại đầu tiên trang bị ba camera sau.",
                "vi",
                "en",
            )
        )
        # Tóm tắt rỗng
        self.assertFalse(
            is_valid_translation(
                "How to speed up Windows",
                "Disable startup apps in Task Manager.",
                "Cách tăng tốc Windows",
                "",
                "en",
                "vi",
            )
        )
        # Tiêu đề đúng tiếng Việt nhưng tóm tắt vẫn giữ tiếng Anh (>= 15 chữ cái)
        self.assertFalse(
            is_valid_translation(
                "How to speed up Windows",
                "Disable startup applications in Task Manager to improve boot time.",
                "Cách tăng tốc Windows nhanh chóng",
                "Disable startup applications in Task Manager to improve boot time.",
                "en",
                "vi",
            )
        )
        # Tiêu đề đúng tiếng Anh nhưng tóm tắt vẫn là tiếng Việt (>= 15 chữ cái)
        self.assertFalse(
            is_valid_translation(
                "Mẹo tối ưu pin điện thoại",
                "Tắt ứng dụng chạy nền để tiết kiệm pin điện thoại mỗi ngày.",
                "Tips to optimize phone battery",
                "Tắt ứng dụng chạy nền để tiết kiệm pin điện thoại mỗi ngày.",
                "vi",
                "en",
            )
        )
        # Bản dịch hợp lệ đạt cả tiêu đề lẫn tóm tắt
        self.assertTrue(
            is_valid_translation(
                "How to speed up Windows",
                "Disable startup apps in Task Manager to improve boot time.",
                "Cách tăng tốc khởi động Windows",
                "Tắt ứng dụng khởi động cùng hệ thống trong Task Manager để mở máy nhanh hơn.",
                "en",
                "vi",
            )
        )

    def test_translation_retry_cooldown_and_clearing(self):
        """Hết 3 lần thất bại thì chờ 24h thay vì đóng băng vĩnh viễn; đạt trần 9 thì dừng; thành công thì xóa sạch."""
        t0 = datetime(2026, 11, 20, 0, 0, 0, tzinfo=timezone.utc)
        item = {
            "id": "retry-1",
            "original_lang": "en",
            "title": {"en": "Speed up Git", "vi": "Speed up Git"},
            "summary": {"en": "Enable fsmonitor on large repos.", "vi": "Enable fsmonitor on large repos."},
        }
        # 2 lần lỗi đầu chưa vào cooldown
        _record_translation_failure(item, "vi", now=t0)
        self.assertTrue(_can_attempt_translation(item, "vi", now=t0))
        self.assertNotIn("translate_next_retry", item)
        _record_translation_failure(item, "vi", now=t0)
        self.assertTrue(_can_attempt_translation(item, "vi", now=t0))

        # Lần lỗi thứ 3 -> đặt cooldown 24h
        _record_translation_failure(item, "vi", now=t0)
        self.assertEqual(item["translate_attempts"]["vi"], 3)
        self.assertIn("vi", item["translate_next_retry"])
        self.assertFalse(_can_attempt_translation(item, "vi", now=t0 + timedelta(hours=12)))
        self.assertTrue(_can_attempt_translation(item, "vi", now=t0 + timedelta(hours=25)))

        # Khi phục hồi thành công từ cache, xóa sạch cả translate_attempts và translate_next_retry
        cache = {
            "retry-1": {
                "title": {"en": "Speed up Git", "vi": "Cách tăng tốc Git hiệu quả"},
                "summary": {"en": "Enable fsmonitor on large repos.", "vi": "Bật fsmonitor để tăng tốc kho mã nguồn lớn."},
                "translated": {"vi": "machine"},
            }
        }
        batch_translate_pending([item], cache, translator=Mock(), max_items=5)
        self.assertEqual(item["translated"]["vi"], "machine")
        self.assertNotIn("translate_attempts", item)
        self.assertNotIn("translate_next_retry", item)

        # Kiểm tra chạm trần trọn đời 9 lần sẽ dừng hẳn
        doomed = {"id": "doomed-1"}
        for i in range(9):
            _record_translation_failure(doomed, "vi", now=t0 + timedelta(days=i))
        self.assertFalse(_can_attempt_translation(doomed, "vi", now=t0 + timedelta(days=30)))

    def test_gemini_thinking_budget_5xx_retry_and_fallback_models(self):
        """Gemini 2.5 bật thinkingBudget=0, thử lại khi gặp 503 và dùng fallback 2.5-flash-lite."""
        resp_503 = Mock(status_code=503, text="Service Unavailable")
        resp_404 = Mock(status_code=404, text="Not Found")
        resp_200 = Mock(status_code=200)
        resp_200.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps([{
                            "id": "g-retry",
                            "title": "Cách cấu hình SSH nhanh gọn",
                            "summary": "Sử dụng khóa ed25519 để tăng bảo mật khi đăng nhập máy chủ.",
                        }])
                    }]
                }
            }]
        }

        with patch.dict(os.environ, {"GEMINI_API_KEY": "secret-k", "GEMINI_MODEL": "gemini-2.5-flash"}):
            translator = GeminiTranslator()
            with patch("translate.time.sleep") as _mock_sleep:
                with patch("translate.requests.Session.post", side_effect=[resp_503, resp_404, resp_200]) as mock_post:
                    res = translator.translate_batch(
                        [{"id": "g-retry", "title": "Configure SSH", "summary": "Use ed25519 keys."}],
                        source_lang="en",
                        target_lang="vi",
                    )

        self.assertEqual(len(res), 1)
        self.assertEqual(mock_post.call_count, 3)
        # Payload gửi tới gemini-2.5-* phải có thinkingConfig.thinkingBudget == 0
        first_payload = mock_post.call_args_list[0].kwargs["json"]
        self.assertEqual(first_payload["generationConfig"].get("thinkingConfig"), {"thinkingBudget": 0})
        # Model dự phòng là gemini-2.5-flash-lite (không còn model cũ 1.5/2.0)
        third_url = mock_post.call_args_list[2].args[0]
        self.assertIn("gemini-2.5-flash-lite", third_url)

    def test_diversify_limits_nested_source_content_type_community(self):
        """diversify() phải giới hạn nguồn có source.content_type == 'community' (như HN, Dev.to, Community)."""
        items = []
        # 6 bài cộng đồng điểm rất cao (không có content_type ở cấp root, chỉ ở source.content_type)
        for i in range(6):
            items.append({
                "id": f"comm-{i}",
                "score": 1.4 - i * 0.01,
                "source": {"id": f"hn-src-{i}", "content_type": "community"},
            })
        # 10 bài báo chí công nghệ điểm thấp hơn
        for i in range(10):
            items.append({
                "id": f"art-{i}",
                "score": 0.9 - i * 0.01,
                "source": {"id": f"press-{i}", "content_type": "article"},
            })

        out = diversify(items, max_run=2, max_community_per_window=2, window_size=10)
        first_ten = out[:10]
        comm_in_first_ten = sum(1 for x in first_ten if x["source"]["content_type"] == "community")
        self.assertLessEqual(comm_in_first_ten, 2)

    def test_filters_reject_release_noise_and_url_only_summary(self):
        """filters.accept() và is_howto_match() phải chặn Dependabot/Dev preview và tóm tắt chỉ có URL trần."""
        noise_titles = [
            "v0.103.3052: Build(deps): Bump actions/setup-dotnet from 5.4.0 to 6.0.0 (#49862)",
            "chore(deps): Bump typescript from 5.7.0 to 5.8.0",
            "Dev preview v0.103.3099.0",
        ]
        for nt in noise_titles:
            ok, reason = accept(
                {"raw_title": nt, "raw_summary": "Automated release notes for dependency update."},
                {"id": "powertoys-release", "kind": "tips"},
                enable_logging=False,
            )
            self.assertFalse(ok)
            self.assertEqual(reason, "release-noise")
            self.assertFalse(is_howto_match(nt, "How to fix settings"))

        ok_url, reason_url = accept(
            {
                "raw_title": "Android 17 features and hidden tips",
                "raw_summary": "https://www.youtube.com/watch?v=_enN4cmvmz8",
            },
            {"id": "reddit-androidtips", "kind": "tips"},
            enable_logging=False,
        )
        self.assertFalse(ok_url)
        self.assertEqual(reason_url, "url-only-summary")

    def test_qa_validate_machine_translation_catches_false_summary_and_verbatim(self):
        """qa.py phải bắt được bản dịch máy sai ngôn ngữ ở tóm tắt và bản sao nguyên văn."""
        # 1. Bản sao nguyên văn (6f7743a9465550a4)
        verbatim_item = {
            "id": "qa-verbatim",
            "original_lang": "vi",
            "title": {
                "vi": "Oppo Find X10 Pro Max - smartphone có ba camera 200 megapixel",
                "en": "Oppo Find X10 Pro Max - smartphone có ba camera 200 megapixel",
            },
            "summary": {
                "vi": "Oppo Find X10 Pro Max là điện thoại đầu tiên trang bị ba camera sau.",
                "en": "Oppo Find X10 Pro Max là điện thoại đầu tiên trang bị ba camera sau.",
            },
            "translated": {"en": "machine"},
        }
        self.assertTrue(len(validate_machine_translation(verbatim_item)) > 0)

        # 2. Tiêu đề đã dịch sang tiếng Anh nhưng tóm tắt vẫn còn tiếng Việt
        bad_summary_item = {
            "id": "qa-bad-summ",
            "original_lang": "vi",
            "title": {
                "vi": "Cách tăng tốc trình duyệt Chrome",
                "en": "How to speed up Chrome browser",
            },
            "summary": {
                "vi": "Bật tính năng tiết kiệm bộ nhớ để giảm tiêu thụ RAM khi mở nhiều tab.",
                "en": "Bật tính năng tiết kiệm bộ nhớ để giảm tiêu thụ RAM khi mở nhiều tab.",
            },
            "translated": {"en": "machine"},
        }
        errs = validate_machine_translation(bad_summary_item)
        self.assertTrue(any("tóm tắt" in e for e in errs))

        # 3. Bản dịch chuẩn cả tiêu đề và tóm tắt phải vượt qua kiểm định
        good_item = {
            "id": "qa-good",
            "original_lang": "vi",
            "title": {
                "vi": "Cách tăng tốc trình duyệt Chrome",
                "en": "How to speed up Chrome browser",
            },
            "summary": {
                "vi": "Bật tính năng tiết kiệm bộ nhớ để giảm tiêu thụ RAM.",
                "en": "Enable Memory Saver to reduce RAM usage across open tabs.",
            },
            "translated": {"en": "machine"},
        }
        self.assertEqual(validate_machine_translation(good_item), [])

    def test_write_health_report_statuses(self):
        """write_health_report xuất chuẩn schema health.json với trạng thái ok/degraded/paused."""
        now = datetime(2026, 11, 21, 8, 0, 0, tzinfo=timezone.utc)
        sources = [
            {"id": "src-ok"},
            {"id": "src-deg"},
            {"id": "src-paused"},
        ]
        state = {
            "src-ok": {"failure_count": 0, "last_success": "2026-11-21T07:00:00+00:00"},
            "src-deg": {"failure_count": 2, "last_failure": "2026-11-21T07:30:00+00:00", "last_error": "HTTP 429"},
            "src-paused": {
                "failure_count": 5,
                "last_failure": "2026-11-21T07:45:00+00:00",
                "paused_until": "2026-11-22T07:45:00+00:00",
                "last_error": "HTTP 503",
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "health.json"
            report = write_health_report(sources, state, now_dt=now, path=out_path)
            loaded = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(loaded, report)
        self.assertEqual(loaded["updated_at"], "2026-11-21T08:00:00+00:00")
        self.assertEqual(loaded["sources"]["src-ok"]["status"], "ok")
        self.assertEqual(loaded["sources"]["src-deg"]["status"], "degraded")
        self.assertEqual(loaded["sources"]["src-paused"]["status"], "paused")


if __name__ == "__main__":
    unittest.main()
