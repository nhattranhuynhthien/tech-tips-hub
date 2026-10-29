# scripts/translate.py
import os
import json
import re
from pathlib import Path

CACHE_FILE = Path("data/cache/translations.json")

VI_CHARS = re.compile(
    r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡ"
    r"ùúụủũưừứựửữỳýỵỷỹđ]",
    re.IGNORECASE
)

EN_COMMON_WORDS = re.compile(
    r"\b(the|and|for|with|that|this|to|in|of|on|is|are|from|by|how)\b",
    re.IGNORECASE
)

def looks_vietnamese(text: str) -> bool:
    """Kiểm tra văn bản có mật độ ký tự tiếng Việt chuẩn hay không (> 3%)."""
    if not text:
        return False
    return (len(VI_CHARS.findall(text)) / max(len(text), 1)) > 0.03

def looks_english(text: str) -> bool:
    """Kiểm tra văn bản hoàn toàn không chứa ký tự tiếng Việt có dấu."""
    if not text:
        return True
    return len(VI_CHARS.findall(text)) == 0

def is_mixed(text: str) -> bool:
    """
    Phát hiện câu trộn ngữ pháp (ví dụ có từ tiếng Việt thay thế nằm giữa câu tiếng Anh).
    Bằng chứng: "This Newly Proposed Linux Filesystem Can Khắc phục Corrupted Data".
    """
    if not text:
        return False
    has_vi_keyword = bool(re.search(r"\b(Cách|Khắc phục|Tối ưu hóa|Mẹo|Hướng dẫn|Thủ thuật)\b", text))
    en_words_count = len(EN_COMMON_WORDS.findall(text))
    return has_vi_keyword and en_words_count >= 2

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
    """
    Dịch toàn câu bằng Google Gemini API khi có biến môi trường GEMINI_API_KEY.
    Hoàn toàn không thay thế từ khóa chắp vá.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key or not text:
        return ""
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        target_name = "Tiếng Việt" if target_lang == "vi" else "English"
        context = "Tóm tắt ngắn gọn và dịch sang" if is_summary else "Dịch trọn vẹn và tự nhiên tiêu đề thủ thuật công nghệ sang"
        prompt = (
            f"{context} {target_name}. Giữ nguyên thuật ngữ kỹ thuật phổ biến (như Git, Docker, Windows, Linux, SSD, RAM). "
            f"Chỉ trả về duy nhất nội dung đã dịch, không giải thích thêm:\n\n{text}"
        )
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        if response and response.text:
            cleaned = response.text.strip().replace("\n", " ")
            return cleaned
    except Exception as e:
        print(f"[Gemini API Warning]: {e}")
    return ""

def process_item_bilingual(item_id: str, orig_title: str, orig_summary: str, orig_lang: str, cache: dict) -> tuple[dict, dict, dict]:
    """
    Xử lý song ngữ an toàn và trung thực:
    - Nếu có bản dịch máy đạt chuẩn (Gemini hoặc cache đã kiểm tra hợp lệ), gán nhãn machine.
    - Nếu không dịch được hoặc bản dịch bị trộn ngôn ngữ, giữ nguyên bản gốc và KHÔNG gắn nhãn dịch giả dối.
    - Tuyệt đối không gắn tiền tố '[Bản dịch]' vào văn bản.
    """
    # 1. Kiểm tra cache
    if item_id in cache:
        c = cache[item_id]
        t_vi = c.get("title", {}).get("vi", "")
        s_vi = c.get("summary", {}).get("vi", "")
        # Nếu cache cũ chứa câu trộn hoặc rác thì hủy cache mục này
        if not is_mixed(t_vi) and not is_mixed(s_vi) and not ("[Bản dịch]" in s_vi or "[Bản dịch]" in t_vi):
            return c["title"], c["summary"], c.get("translated", {})

    target_lang = "vi" if orig_lang == "en" else "en"

    title_dict = {orig_lang: orig_title}
    summary_dict = {orig_lang: orig_summary}
    trans_meta = {}

    # 2. Thử dịch bằng Gemini nếu có key
    translated_title = translate_with_gemini(orig_title, target_lang, is_summary=False)
    translated_summary = translate_with_gemini(orig_summary, target_lang, is_summary=True)

    # 3. Nghiệm thu chất lượng dịch thuật
    if translated_title and translated_summary:
        if target_lang == "vi":
            is_valid = (
                looks_vietnamese(translated_title) and
                not is_mixed(translated_title) and
                not is_mixed(translated_summary)
            )
        else:
            is_valid = (
                looks_english(translated_title) and
                not is_mixed(translated_title) and
                not is_mixed(translated_summary)
            )

        if is_valid:
            title_dict[target_lang] = translated_title
            summary_dict[target_lang] = translated_summary
            trans_meta[target_lang] = "machine"
        else:
            # Không đạt chuẩn: giữ nguyên bản gốc cho ngôn ngữ đích
            title_dict[target_lang] = orig_title
            summary_dict[target_lang] = orig_summary
    else:
        # Không có bản dịch: giữ nguyên bản gốc, KHÔNG gắn nhãn machine
        title_dict[target_lang] = orig_title
        summary_dict[target_lang] = orig_summary

    # Lưu cache
    cache[item_id] = {
        "title": title_dict,
        "summary": summary_dict,
        "translated": trans_meta
    }

    return title_dict, summary_dict, trans_meta
