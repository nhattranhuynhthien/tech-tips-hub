# tests/test_translate.py
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from translate import (
    looks_vietnamese,
    looks_english,
    is_mixed,
    GeminiTranslator,
    ArgosOfflineTranslator,
    CompositeTranslator,
    process_item_bilingual,
    batch_translate_pending
)
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


if __name__ == "__main__":
    unittest.main()
