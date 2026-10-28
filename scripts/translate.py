# scripts/translate.py
import os
import json
import re
from pathlib import Path

CACHE_FILE = Path("data/cache/translations.json")

# Từ điển ánh xạ cụm từ công nghệ thông dụng EN -> VI
EN_TO_VI_PHRASES = [
    (r"\bHow to\b", "Cách"),
    (r"\bHow To\b", "Cách"),
    (r"\bStep-by-step guide\b", "Hướng dẫn từng bước"),
    (r"\bTips and tricks\b", "Thủ thuật và mẹo hay"),
    (r"\bTips & Tricks\b", "Thủ thuật & mẹo hay"),
    (r"\bTop (\d+) tricks\b", "Top \1 mẹo hay"),
    (r"\bBest ways to\b", "Cách tốt nhất để"),
    (r"\bFix\b", "Khắc phục"),
    (r"\bTroubleshoot\b", "Sửa lỗi"),
    (r"\bSpeed up\b", "Tăng tốc"),
    (r"\bOptimize\b", "Tối ưu hóa"),
    (r"\bHidden features\b", "Tính năng ẩn"),
    (r"\bKeyboard shortcuts\b", "Phím tắt bàn phím"),
    (r"\bBattery saver\b", "Tiết kiệm pin"),
    (r"\bDark mode\b", "Chế độ nền tối"),
    (r"\bClean install\b", "Cài đặt sạch"),
    (r"\bTask Manager\b", "Trình quản lý tác vụ Task Manager"),
    (r"\bCommand Prompt\b", "Cửa sổ lệnh Command Prompt"),
    (r"\bon Windows 11\b", "trên Windows 11"),
    (r"\bon Windows 10\b", "trên Windows 10"),
    (r"\bon Mac\b", "trên máy Mac"),
    (r"\bon iPhone\b", "trên iPhone"),
    (r"\bon Android\b", "trên Android"),
    (r"\bfor beginners\b", "cho người mới bắt đầu"),
    (r"\bEverything you need to know\b", "Tất cả những gì bạn cần biết"),
]

# Từ điển ánh xạ cụm từ VI -> EN
VI_TO_EN_PHRASES = [
    (r"\bCách\b", "How to"),
    (r"\bHướng dẫn\b", "Guide to"),
    (r"\bThủ thuật\b", "Tricks for"),
    (r"\bMẹo hay\b", "Smart tips for"),
    (r"\bPhím tắt\b", "Keyboard shortcuts for"),
    (r"\bTăng tốc\b", "Speed up"),
    (r"\bTối ưu\b", "Optimize"),
    (r"\bKhắc phục lỗi\b", "Fix errors in"),
    (r"\bSửa lỗi\b", "Fix issue in"),
    (r"\bTiết kiệm pin\b", "Save battery on"),
    (r"\bTính năng ẩn\b", "Hidden features in"),
    (r"\btrên máy tính\b", "on PC"),
    (r"\btrên điện thoại\b", "on smartphone"),
]

def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_cache(cache: dict):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

def translate_with_gemini(text: str, target_lang: str, is_summary: bool = False) -> str:
    """Sử dụng Gemini API nếu có GEMINI_API_KEY trong environment."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return ""
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        target_name = "Tiếng Việt" if target_lang == "vi" else "English"
        context = "Tóm tắt ngắn gọn và dịch sang" if is_summary else "Dịch tiêu đề thủ thuật công nghệ một cách tự nhiên sang"
        prompt = f"{context} {target_name}. Giữ nguyên thuật ngữ kỹ thuật phổ biến. Chỉ trả về nội dung đã dịch, không giải thích thêm:\n\n{text}"
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        if response and response.text:
            return response.text.strip().replace("\n", " ")
    except Exception as e:
        print(f"[Gemini API Warning]: {e}")
    return ""

def rule_based_translate(text: str, source_lang: str, target_lang: str) -> str:
    """Bộ dịch thông minh ngoại tuyến khi không dùng API bên ngoài (chi phí 0đ)."""
    if not text:
        return ""
    translated = text
    if source_lang == "en" and target_lang == "vi":
        for pattern, repl in EN_TO_VI_PHRASES:
            translated = re.sub(pattern, repl, translated, flags=re.IGNORECASE)
        # Bổ sung tiền tố nếu là câu hướng dẫn
        if translated.lower().startswith("how "):
            translated = "Cách " + translated[4:]
    elif source_lang == "vi" and target_lang == "en":
        for pattern, repl in VI_TO_EN_PHRASES:
            translated = re.sub(pattern, repl, translated, flags=re.IGNORECASE)

    return translated.strip()

def process_item_bilingual(item_id: str, orig_title: str, orig_summary: str, orig_lang: str, cache: dict) -> tuple[dict, dict, dict]:
    """
    Xử lý song ngữ cho tiêu đề và tóm tắt của một bài viết:
    Trả về (title_dict, summary_dict, translation_metadata)
    """
    if item_id in cache:
        c = cache[item_id]
        return c["title"], c["summary"], c.get("translated", {})

    target_lang = "vi" if orig_lang == "en" else "en"

    title_dict = {orig_lang: orig_title}
    summary_dict = {orig_lang: orig_summary}

    # 1. Thử qua Gemini API nếu có cấu hình
    translated_title = translate_with_gemini(orig_title, target_lang, is_summary=False)
    translated_summary = translate_with_gemini(orig_summary, target_lang, is_summary=True)

    # 2. Dự phòng bằng rule-based nếu API rỗng hoặc không có key
    if not translated_title:
        translated_title = rule_based_translate(orig_title, orig_lang, target_lang)
    if not translated_summary:
        if orig_lang == "en":
            translated_summary = f"[Bản dịch] {rule_based_translate(orig_summary, 'en', 'vi')}"
        else:
            translated_summary = f"[Summary] {rule_based_translate(orig_summary, 'vi', 'en')}"

    title_dict[target_lang] = translated_title
    summary_dict[target_lang] = translated_summary
    translated_meta = {target_lang: "machine"}

    # Lưu vào cache
    cache[item_id] = {
        "title": title_dict,
        "summary": summary_dict,
        "translated": translated_meta
    }

    return title_dict, summary_dict, translated_meta
