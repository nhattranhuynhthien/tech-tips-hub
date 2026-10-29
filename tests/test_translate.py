# tests/test_translate.py
import sys
import unittest
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from translate import (
    looks_vietnamese,
    looks_english,
    is_mixed,
    GeminiTranslator,
    ArgosOfflineTranslator,
    CompositeTranslator,
    process_item_bilingual
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

    def test_translator_interface(self):
        """Kiểm tra tính nhất quán của Translator interface."""
        gemini = GeminiTranslator()
        argos = ArgosOfflineTranslator()
        comp = CompositeTranslator()

        self.assertTrue(hasattr(gemini, "translate_batch"))
        self.assertTrue(hasattr(argos, "translate_batch"))
        self.assertTrue(hasattr(comp, "translate_batch"))

    def test_fallback_when_untranslated(self):
        """Khi không có khóa API hoặc dịch thất bại, giữ nguyên bản gốc và KHÔNG gắn nhãn dịch máy."""
        comp = CompositeTranslator()
        cache = {}
        title, summ, trans = process_item_bilingual(
            item_id="test_sample_001",
            orig_title="How to configure Docker containers on Linux",
            orig_summary="A complete step by step tutorial to setup Docker on Linux distributions.",
            orig_lang="en",
            cache=cache,
            translator=comp
        )

        # Vì không có API key trong môi trường test này, không được gắn nhãn machine
        self.assertNotEqual(trans.get("vi"), "machine")
        self.assertEqual(title["en"], "How to configure Docker containers on Linux")
        self.assertEqual(title["vi"], "How to configure Docker containers on Linux")

if __name__ == "__main__":
    unittest.main()
