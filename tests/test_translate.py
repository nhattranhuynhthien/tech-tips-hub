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

class TestTranslateModule(unittest.TestCase):
    def test_mixed_language_detection(self):
        """Phát hiện các câu trộn ngữ pháp giữa tiếng Anh và tiếng Việt."""
        self.assertTrue(is_mixed("Cách a Salon Website Gets Built in Lovable"))
        self.assertTrue(is_mixed("This Newly Proposed Linux Filesystem Can Khắc phục Corrupted Data"))
        self.assertTrue(is_mixed("How to Tối ưu hóa Windows for gaming"))
        # Câu thuần tiếng Việt hoặc thuần tiếng Anh không phải là câu trộn
        self.assertFalse(is_mixed("Hướng dẫn cấu hình SSH an toàn trên máy chủ Ubuntu"))
        self.assertFalse(is_mixed("How to configure SSH securely on Ubuntu server"))
        self.assertFalse(is_mixed("Thủ thuật tăng tốc máy tính Windows 11 hiệu quả"))

    def test_language_detection(self):
        """Kiểm tra nhận diện tiếng Việt và tiếng Anh chuẩn."""
        self.assertTrue(looks_vietnamese("Thủ thuật tối ưu hóa Windows 11"))
        self.assertFalse(looks_vietnamese("How to speed up Windows 11 with simple tweaks"))
        
        self.assertTrue(looks_english("How to speed up Windows 11 with simple tweaks"))
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

    def test_chinese_translation_failure_keeps_original(self):
        translator = Mock()
        translator.translate_batch.return_value = []
        item = {
            "id": "zh-item-2", "original_lang": "zh-CN", "title": {"zh-CN": "苹果发布新款 MacBook"},
            "summary": {"zh-CN": "苹果今天发布了搭载新芯片的笔记本电脑。"}, "score": 0.8,
        }
        batch_translate_pending([item], {}, translator=translator, max_items=4)

        self.assertEqual(item["title"]["vi"], item["title"]["zh-CN"])
        self.assertEqual(item["title"]["en"], item["title"]["zh-CN"])
        self.assertFalse(item["translated"]["vi"])
        self.assertFalse(item["translated"]["en"])

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

        # Khi không có kết quả dịch, không được gắn nhãn machine.
        self.assertNotEqual(trans.get("vi"), "machine")
        self.assertEqual(title["en"], "How to configure Docker containers on Linux")
        self.assertEqual(title["vi"], "How to configure Docker containers on Linux")

if __name__ == "__main__":
    unittest.main()

