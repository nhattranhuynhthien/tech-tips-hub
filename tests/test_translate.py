# tests/test_translate.py
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import translate
from translate import (
    looks_vietnamese,
    looks_english,
    is_mixed,
    sanitize_key_points,
    normalize_key_points_map,
    parse_gemini_response,
    load_cache,
    GeminiTranslator,
    ArgosOfflineTranslator,
    CompositeTranslator,
    process_item_bilingual,
    batch_translate_pending,
)
from qa import validate_key_points
from run_pipeline import sync_item_key_points
from filters import accept
from dedupe import is_blocked
from classify import classify, VALID_CATEGORIES
from textclean import clean_text, clean_title
from score import parse_published_time
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


if __name__ == "__main__":
    unittest.main()
