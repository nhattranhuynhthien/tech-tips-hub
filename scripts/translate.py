# scripts/translate.py
import os
import sys
import json
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path
import requests
import urllib.request
import urllib.parse

CACHE_FILE = Path("data/cache/translations.json")

# Ký tự tiếng Việt có dấu chuẩn
VI_CHARS = re.compile(
    r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡ"
    r"ùúụủũưừứựửữỳýỵỷỹđ]",
    re.IGNORECASE
)

# Từ tiếng Anh phổ biến dùng phát hiện câu trộn
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
    """Kiểm tra văn bản tiếng Anh hoàn toàn không chứa ký tự tiếng Việt có dấu."""
    if not text:
        return True
    return len(VI_CHARS.findall(text)) == 0

VI_FUNCTION_WORDS = re.compile(
    r"\b(của|và|cho|trong|được|này|đã|sẽ|như|thế|mình|bạn|với|sau|khi|làm|việc|người|hướng|dẫn|xem|nội|dung|ngày)\b",
    re.IGNORECASE
)

EN_FUNCTION_WORDS = re.compile(
    r"\b(the|and|for|with|that|this|to|in|of|on|is|are|from|by|a|an|how|can|your|you|it|its|at)\b",
    re.IGNORECASE
)

def is_mixed(text: str) -> bool:
    """
    Phát hiện câu trộn ngữ pháp (từ tiếng Việt chắp vá nằm giữa câu tiếng Anh).
    Bằng chứng: "Cách a Salon Website Gets Built in Lovable",
                "This Newly Proposed Linux Filesystem Can Khắc phục Corrupted Data".
    """
    if not text:
        return False

    # Kiểm tra có chứa từ khóa bị thay thế máy móc (viết hoa dạng tiêu đề)
    has_injected_kw = bool(re.search(r"\b(Cách|Khắc phục|Tối ưu hóa)\b", text))
    if not has_injected_kw:
        return False

    # Đếm từ chức năng tiếng Anh vs tiếng Việt
    en_count = len(EN_FUNCTION_WORDS.findall(text))
    vi_count = len(VI_FUNCTION_WORDS.findall(text))

    # Nếu có từ tiếng Anh chức năng (the, and, in, a, this, can...) và không có từ ngữ pháp tiếng Việt
    if en_count >= 2 and vi_count == 0:
        return True

    return False

def load_cache() -> dict:
    """Đọc cache dịch thuật, tự động loại bỏ các bản dịch cũ bị trộn ngữ pháp hoặc chứa rác."""
    if not CACHE_FILE.exists():
        return {}
    try:
        raw_data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        cleaned_cache = {}
        for iid, val in raw_data.items():
            t_vi = val.get("title", {}).get("vi", "")
            s_vi = val.get("summary", {}).get("vi", "")
            if is_mixed(t_vi) or is_mixed(s_vi) or "[Bản dịch]" in t_vi or "[Bản dịch]" in s_vi:
                continue
            # Chỉ nạp vào cache nếu bài viết thực sự đã có nhãn dịch máy thành công
            trans = val.get("translated", {})
            if trans.get("vi") != "machine" and trans.get("en") != "machine":
                continue
            cleaned_cache[iid] = val
        return cleaned_cache
    except Exception as e:
        print(f"[Cache Warning] Không thể đọc cache: {e}")
        return {}

def save_cache(cache: dict):
    """Lưu cache bản dịch vào file JSON."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

# ==========================================
# GIAO DIỆN VÀ CÁC BỘ DỊCH THUẬT (TRANSLATOR)
# ==========================================

class Translator(ABC):
    """Giao diện trừu tượng cho các nhà cung cấp dịch thuật."""
    @abstractmethod
    def translate_batch(self, items: list[dict], source_lang: str, target_lang: str) -> list[dict]:
        """
        Dịch nguyên câu một lô bài viết.
        items: [{"id": str, "title": str, "summary": str}]
        returns: [{"id": str, "title": str, "summary": str}]
        """
        pass

class GeminiTranslator(Translator):
    """
    Nhà cung cấp chính: Google Gemini API (free tier).
    Dịch theo lô, hỗ trợ retry với exponential backoff khi gặp mã 429.
    """
    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"

    def is_available(self) -> bool:
        return bool(self.api_key)

    def translate_batch(self, items: list[dict], source_lang: str, target_lang: str) -> list[dict]:
        if not self.is_available() or not items:
            return []

        target_name = "tiếng Việt" if target_lang == "vi" else "English"
        prompt = (
            f"Bạn là chuyên gia dịch thuật công nghệ thông tin song ngữ Anh - Việt.\n"
            f"Hãy dịch trọn vẹn cả câu danh sách thủ thuật sau sang {target_name}.\n\n"
            f"QUY TẮC BẮT BUỘC:\n"
            f"1. Dịch NGUYÊN CÂU, văn phong tự nhiên, súc tích. Tuyệt đối KHÔNG thay thế từ khóa chắp vá hay trộn tiếng.\n"
            f"2. GIỮ NGUYÊN không dịch: tên phần mềm/sản phẩm (Chrome, Windows, Ubuntu, Docker, Git, VS Code...), "
            f"lệnh shell, code, phím tắt (Ctrl+B, sudo, grep, apt, winget), phần cứng (SSD, RAM, GPU, CPU), API.\n"
            f"3. Không thêm bớt thông tin ngoài bản gốc; không thêm tiền tố như '[Bản dịch]'.\n"
            f"4. Trả về DUY NHẤT một mảng JSON hợp lệ chứa các đối tượng có thuộc tính [\"id\", \"title\", \"summary\"]. "
            f"Không thêm bất kỳ lời bình hay định dạng nào khác.\n\n"
            f"Dữ liệu đầu vào JSON:\n{json.dumps(items, ensure_ascii=False)}"
        )

        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json"
            }
        }
        headers = {"Content-Type": "application/json"}

        # Retry với Exponential Backoff khi gặp 429 hoặc model fallback
        models_to_try = [self.model]
        if self.model != "gemini-2.5-flash":
            models_to_try.append("gemini-1.5-flash")
        if "gemini-2.0-flash" not in models_to_try:
            models_to_try.append("gemini-2.0-flash")

        session = requests.Session()

        for curr_model in models_to_try:
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{curr_model}:generateContent?key={self.api_key}"
            max_retries = 3
            delay = 2.0

            for attempt in range(max_retries):
                try:
                    resp = session.post(endpoint, json=payload, headers=headers, timeout=40)
                    if resp.status_code == 429:
                        print(f"[Gemini 429 Quota] Chờ {delay:.1f}s trước khi thử lại (lần {attempt + 1}/{max_retries})...")
                        time.sleep(delay)
                        delay *= 2
                        continue
                    if resp.status_code == 404:
                        print(f"[Gemini Warning] Model {curr_model} 404 Not Found, chuyển sang model dự phòng...")
                        break
                    if resp.status_code != 200:
                        print(f"[Gemini Warning] HTTP {resp.status_code}: {resp.text[:140]}")
                        return []

                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if not candidates:
                        return []
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if not parts:
                        return []
                    
                    raw_text = parts[0].get("text", "").strip()
                    # Gỡ markdown code blocks nếu có
                    if raw_text.startswith("```"):
                        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
                        raw_text = re.sub(r"\s*```$", "", raw_text)
                    
                    translated_list = json.loads(raw_text)
                    if isinstance(translated_list, list):
                        return translated_list
                    return []
                except Exception as e:
                    print(f"[Gemini Exception (Lần {attempt + 1})]: {e}")
                    time.sleep(delay)
                    delay *= 2

        return []

class ArgosOfflineTranslator(Translator):
    """
    Nhà cung cấp dự phòng: Argos Translate chạy offline trong môi trường GitHub Actions / local.
    Chỉ kích hoạt nếu thư viện argostranslate đã được cài đặt và có model tương ứng.
    """
    def __init__(self):
        self._available = False
        try:
            import argostranslate.translate
            self.argos = argostranslate.translate
            self._available = True
        except ImportError:
            self.argos = None

    def is_available(self) -> bool:
        return self._available

    def translate_batch(self, items: list[dict], source_lang: str, target_lang: str) -> list[dict]:
        if not self.is_available() or not items:
            return []
        try:
            installed_langs = self.argos.get_installed_languages()
            lang_map = {l.code: l for l in installed_langs}
            from_l = lang_map.get(source_lang)
            to_l = lang_map.get(target_lang)
            if not from_l or not to_l:
                return []
            translation = from_l.get_translation(to_l)
            if not translation:
                return []
            
            results = []
            for it in items:
                res_title = translation.translate(it["title"])
                res_summ = translation.translate(it["summary"])
                results.append({
                    "id": it["id"],
                    "title": res_title,
                    "summary": res_summ
                })
            return results
        except Exception as e:
            print(f"[Argos Offline Warning]: {e}")
            return []

class GoogleWebTranslator(Translator):
    """
    Sử dụng endpoint Google Translate công khai (client=gtx) làm lựa chọn dự phòng.
    Endpoint không yêu cầu API key nhưng có thể bị giới hạn hoặc thay đổi.
    """
    def is_available(self) -> bool:
        return True

    def translate_text(self, text: str, source_lang: str, target_lang: str) -> str:
        if not text or not text.strip():
            return ""
        try:
            url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={source_lang}&tl={target_lang}&dt=t&q=" + urllib.parse.quote(text)
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                translated = "".join([part[0] for part in data[0] if part and part[0]])
                return translated.strip()
        except Exception as e:
            return ""

    def translate_batch(self, items: list[dict], source_lang: str, target_lang: str) -> list[dict]:
        if not items:
            return []
        results = []
        for it in items:
            t = self.translate_text(it.get("title", ""), source_lang, target_lang)
            s = self.translate_text(it.get("summary", ""), source_lang, target_lang)
            if t and s:
                results.append({
                    "id": it["id"],
                    "title": t,
                    "summary": s
                })
            time.sleep(0.12)
        return results

class CompositeTranslator(Translator):
    """
    Translator tổ hợp:
    1. Ưu tiên Gemini API (nếu có cấu hình GEMINI_API_KEY).
    2. Dự phòng 1: GoogleWebTranslator (không cần API key; phụ thuộc endpoint công khai).
    3. Dự phòng 2: Argos Translate offline (nếu đã cài đặt model cục bộ).
    """
    def __init__(self):
        self.gemini = GeminiTranslator()
        self.google_web = GoogleWebTranslator()
        self.argos = ArgosOfflineTranslator()

    def translate_batch(self, items: list[dict], source_lang: str, target_lang: str) -> list[dict]:
        if not items:
            return []
        # 1. Thử dùng Gemini trước nếu có key
        if self.gemini.is_available():
            results = self.gemini.translate_batch(items, source_lang, target_lang)
            if results:
                return results
        # 2. Dự phòng 1: Google Web Translator (không cần key)
        if self.google_web.is_available():
            results = self.google_web.translate_batch(items, source_lang, target_lang)
            if results:
                return results
        # 3. Dự phòng 2: Argos Translate offline
        if self.argos.is_available():
            print("[Translator] Chuyển sang mô hình dịch offline Argos Translate...")
            results = self.argos.translate_batch(items, source_lang, target_lang)
            if results:
                return results
        return []

# Khởi tạo instance dùng chung
DEFAULT_TRANSLATOR = CompositeTranslator()

def process_item_bilingual(
    item_id: str,
    orig_title: str,
    orig_summary: str,
    orig_lang: str,
    cache: dict,
    translator: Translator = None
) -> tuple[dict, dict, dict]:
    """
    Xử lý song ngữ an toàn, chính xác và trung thực:
    - Nếu đã có trong cache đạt chuẩn (không trộn ngữ pháp, đúng ngôn ngữ), trả về ngay.
    - Nếu dịch thành công và qua khâu nghiệm thu (looks_vietnamese / not is_mixed), gắn nhãn 'machine'.
    - Nếu không dịch được hoặc lỗi, giữ nguyên bản gốc và KHÔNG gắn nhãn dịch máy.
    - Tuyệt đối không gắn tiền tố '[Bản dịch]' vào tiêu đề hay tóm tắt.
    """
    translator = translator or DEFAULT_TRANSLATOR
    target_lang = "vi" if orig_lang == "en" else "en"

    # 1. Kiểm tra cache hợp lệ (phải đã có nhãn dịch máy thực tế)
    if item_id in cache:
        c = cache[item_id]
        if c.get("translated", {}).get(target_lang) == "machine":
            t_vi = c.get("title", {}).get("vi", "")
            s_vi = c.get("summary", {}).get("vi", "")
            if not is_mixed(t_vi) and not is_mixed(s_vi) and not ("[Bản dịch]" in s_vi or "[Bản dịch]" in t_vi):
                return c["title"], c["summary"], c.get("translated", {})

    # 2. Khởi tạo cấu trúc mặc định
    title_dict = {orig_lang: orig_title, target_lang: orig_title}
    summary_dict = {orig_lang: orig_summary, target_lang: orig_summary}
    trans_meta = {}

    # 3. Tiến hành dịch nếu translator sẵn sàng
    batch_input = [{"id": item_id, "title": orig_title, "summary": orig_summary}]
    batch_res = translator.translate_batch(batch_input, source_lang=orig_lang, target_lang=target_lang)
    
    if batch_res:
        t_obj = batch_res[0]
        res_t = t_obj.get("title", "").strip()
        res_s = t_obj.get("summary", "").strip()

        # Nghiệm thu chất lượng bản dịch
        if target_lang == "vi":
            is_valid = looks_vietnamese(res_t) and not is_mixed(res_t) and not is_mixed(res_s)
        else:
            is_valid = looks_english(res_t) and not is_mixed(res_t) and not is_mixed(res_s)

        if is_valid:
            title_dict[target_lang] = res_t
            summary_dict[target_lang] = res_s
            trans_meta[target_lang] = "machine"
            # Chỉ lưu vào cache khi đã dịch thành công
            cache[item_id] = {
                "title": title_dict,
                "summary": summary_dict,
                "translated": trans_meta
            }

    return title_dict, summary_dict, trans_meta

def batch_translate_pending(
    items: list[dict],
    cache: dict,
    translator: Translator = None,
    batch_size: int = 5,
    max_items: int = 40
):
    """
    Dịch theo lô cho các bài viết chưa có bản dịch trong cache:
    - Ưu tiên dịch bài how-to, bài có điểm cao và mới nhất trước.
    - Cập nhật trực tiếp vào items và cache.
    """
    translator = translator or DEFAULT_TRANSLATOR
    
    # Tìm các bài chưa được dịch hợp lệ
    pending_en_to_vi = []
    pending_vi_to_en = []

    for it in items:
        iid = it["id"]
        orig_lang = it.get("original_lang", "en")
        target_lang = "vi" if orig_lang == "en" else "en"

        # Nếu đã có bản dịch hợp lệ trong cache
        if iid in cache and cache[iid].get("translated", {}).get(target_lang) == "machine":
            c = cache[iid]
            it["title"] = c["title"]
            it["summary"] = c["summary"]
            it["translated"] = c.get("translated", {})
            continue

        if it.get("translated", {}).get(target_lang) is False:
            continue

        raw_t = it.get("raw_title") or it["title"].get(orig_lang, "")
        raw_s = it.get("raw_summary") or it["summary"].get(orig_lang, "")

        record = {
            "id": iid,
            "title": raw_t,
            "summary": raw_s,
            "score": it.get("score", 0),
            "howto": it.get("howto", False),
            "published_at": it.get("published_at", "")
        }

        if orig_lang == "en":
            pending_en_to_vi.append(record)
        else:
            pending_vi_to_en.append(record)

    # Ưu tiên: bài how-to, điểm cao, bài mới trước
    pending_en_to_vi.sort(key=lambda x: (x["howto"], x["score"]), reverse=True)
    pending_vi_to_en.sort(key=lambda x: (x["howto"], x["score"]), reverse=True)

    # Apply one shared per-run quota across both translation directions.
    pending_all = sorted(
        [("en", x) for x in pending_en_to_vi] + [("vi", x) for x in pending_vi_to_en],
        key=lambda pair: (pair[1]["howto"], pair[1]["score"], pair[1]["published_at"]),
        reverse=True,
    )
    allowed_ids = {entry["id"] for _, entry in pending_all[:max_items]}
    pending_en_to_vi = [entry for entry in pending_en_to_vi if entry["id"] in allowed_ids]
    pending_vi_to_en = [entry for entry in pending_vi_to_en if entry["id"] in allowed_ids]
    print(f"[Translate] Đang xử lý tối đa {len(allowed_ids)} mục trong giới hạn {max_items}/lượt.")

    items_map = {it["id"]: it for it in items}

    # Xử lý dịch theo lô EN -> VI
    for i in range(0, len(pending_en_to_vi), batch_size):
        chunk = pending_en_to_vi[i:i + batch_size]
        input_payload = [{"id": x["id"], "title": x["title"], "summary": x["summary"]} for x in chunk]
        results = translator.translate_batch(input_payload, source_lang="en", target_lang="vi")

        res_map = {r["id"]: r for r in results if "id" in r}
        for orig in chunk:
            iid = orig["id"]
            it = items_map[iid]
            orig_t = orig["title"]
            orig_s = orig["summary"]

            if iid in res_map:
                res_item = res_map[iid]
                trans_t = res_item.get("title", "").strip()
                trans_s = res_item.get("summary", "").strip()

                if looks_vietnamese(trans_t) and not is_mixed(trans_t) and not is_mixed(trans_s):
                    it["title"]["vi"] = trans_t
                    it["summary"]["vi"] = trans_s
                    it.setdefault("translated", {})["vi"] = "machine"
                else:
                    it["title"]["vi"] = orig_t
                    it["summary"]["vi"] = orig_s
                    it.setdefault("translated", {})["vi"] = False
            else:
                it["title"]["vi"] = orig_t
                it["summary"]["vi"] = orig_s
                it.setdefault("translated", {})["vi"] = False

            if it.get("translated", {}).get("vi") == "machine":
                cache[iid] = {
                    "title": it["title"],
                    "summary": it["summary"],
                    "translated": it.get("translated", {})
                }

    # Xử lý dịch theo lô VI -> EN
    for i in range(0, len(pending_vi_to_en), batch_size):
        chunk = pending_vi_to_en[i:i + batch_size]
        input_payload = [{"id": x["id"], "title": x["title"], "summary": x["summary"]} for x in chunk]
        results = translator.translate_batch(input_payload, source_lang="vi", target_lang="en")

        res_map = {r["id"]: r for r in results if "id" in r}
        for orig in chunk:
            iid = orig["id"]
            it = items_map[iid]
            orig_t = orig["title"]
            orig_s = orig["summary"]

            if iid in res_map:
                res_item = res_map[iid]
                trans_t = res_item.get("title", "").strip()
                trans_s = res_item.get("summary", "").strip()

                if looks_english(trans_t) and not is_mixed(trans_t) and not is_mixed(trans_s):
                    it["title"]["en"] = trans_t
                    it["summary"]["en"] = trans_s
                    it.setdefault("translated", {})["en"] = "machine"
                else:
                    it["title"]["en"] = orig_t
                    it["summary"]["en"] = orig_s
                    it.setdefault("translated", {})["en"] = False
            else:
                it["title"]["en"] = orig_t
                it["summary"]["en"] = orig_s
                it.setdefault("translated", {})["en"] = False

            if it.get("translated", {}).get("en") == "machine":
                cache[iid] = {
                    "title": it["title"],
                    "summary": it["summary"],
                    "translated": it.get("translated", {})
                }
