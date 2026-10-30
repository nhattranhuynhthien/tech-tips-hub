# scripts/filters.py
import re
import json
from pathlib import Path
from datetime import datetime, timezone

LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
REJECTED_LOG = LOG_DIR / "rejected.jsonl"
FILTER_CONFIG_PATH = Path("config/filters.json")
try:
    FILTER_CONFIG = json.loads(FILTER_CONFIG_PATH.read_text(encoding="utf-8"))
except Exception:
    FILTER_CONFIG = {}

KEEP_TERMS = [term for values in FILTER_CONFIG.get("keepKeywords", {}).values() for term in values]
BLOCK_TERMS = FILTER_CONFIG.get("blockKeywords", [])
REVIEW_ALLOW_TERMS = FILTER_CONFIG.get("reviewAllowKeywords", ["tip", "mẹo"])
MIN_TITLE_LENGTH = int(FILTER_CONFIG.get("minTitleLength", 15))


def _term_pattern(terms: list[str]) -> re.Pattern:
    if not terms:
        return re.compile(r"(?!)")
    return re.compile(r"(?:" + "|".join(re.escape(term) for term in sorted(terms, key=len, reverse=True)) + r")", re.IGNORECASE)

HOWTO = re.compile(
    r"\b(how to|how-to|tips?|tricks?|guide|tutorial|fix(es|ing)?|set ?up|"
    r"enable|disable|hidden|settings?|shortcuts?|things to do|walkthrough|"
    r"install|configure|build|create|optimize|speed up|"
    r"cách|mẹo|hướng dẫn|thủ thuật|sửa lỗi|thiết lập|chỉnh|phím tắt|tinh chỉnh|cài đặt|tối ưu)\b",
    re.IGNORECASE
)
CONFIG_HOWTO = _term_pattern(KEEP_TERMS)
CONFIG_BLOCK = _term_pattern(BLOCK_TERMS)
REVIEW = re.compile(r"\breviews?\b", re.IGNORECASE)
REVIEW_ALLOW = _term_pattern(REVIEW_ALLOW_TERMS)

EDITORIAL_OR_REVIEW = re.compile(
    r"\b(weekly|roundup|newsletter|edition|podcast|interview|released?|releases|announces?|announcing|unveils?|changelog|đánh giá|trên tay|tổng hợp tuần|ra mắt|phát hành)\b",
    re.IGNORECASE
)

BLOCK = re.compile(
    r"(\bdeals?\b|\bdiscount\b|\bcoupon\b|% off|\$\d+ off|drops to|price cut|"
    r"\bsale\b|giảm giá|khuyến mãi|\[QC\]|sponsored|giveaway|"
    r"is hiring|\bhiring\b|tuyển dụng|\btrailer\b|unboxing|đập hộp)",
    re.IGNORECASE
)

DEVTO_SELF_PROMO = re.compile(
    r"(originally published at (https?://)?(?!dev\.to)[a-zA-Z0-9.-]+\.vercel\.app|"
    r"originally published at (https?://)?(?!dev\.to)[a-zA-Z0-9.-]+\.pages\.dev|"
    r"originally published at (https?://)?(?!dev\.to)[a-zA-Z0-9.-]+\.netlify\.app)",
    re.IGNORECASE
)

OUT_OF_SCOPE = re.compile(
    r"\b(nông nghiệp|chăn nuôi|gene bò|bò h'mông|thực vật|khảo cổ|động vật hoang dã|gia súc|gia cầm|thời tiết|thiên tai|bệnh viện|y tế|thuốc lá|sốt xuất huyết|dịch sởi|ung thư|bệnh nhân|sản khoa|phụ sản|sinh học)\b",
    re.IGNORECASE
)

def is_howto_match(title: str, summary: str = "") -> bool:
    """Kiểm tra bài viết có dấu hiệu là thủ thuật / hướng dẫn (how-to) hay không."""
    if EDITORIAL_OR_REVIEW.search(title) or (REVIEW.search(title) and not REVIEW_ALLOW.search(title)):
        return False
    return bool(HOWTO.search(title) or CONFIG_HOWTO.search(title)) or bool(HOWTO.search(summary[:140]) or CONFIG_HOWTO.search(summary[:140]))

def log_rejection(item: dict, source: dict, reason: str):
    """Ghi lại lý do bài bị loại vào data/logs/rejected.jsonl để tinh chỉnh bộ lọc sau."""
    try:
        title = item.get("raw_title") or item.get("title", "")
        if isinstance(title, dict):
            title = " ".join(str(v) for v in title.values())
        url = item.get("url", "")
        src_id = source.get("id") if isinstance(source, dict) else str(source)
        
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": src_id,
            "title": title[:120],
            "url": url,
            "reason": reason
        }
        with open(REJECTED_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

def accept(item: dict, source: dict, enable_logging: bool = True) -> tuple[bool, str]:
    """
    Quyết định nhận hay loại bài viết.
    Trả về (accept_bool, reason_string).
    """
    title = item.get("raw_title") or item.get("title", "")
    if isinstance(title, dict):
        title = " ".join(str(v) for v in title.values())
    
    summary = item.get("raw_summary") or item.get("summary", "")
    if isinstance(summary, dict):
        summary = " ".join(str(v) for v in summary.values())

    if len(title.strip()) < MIN_TITLE_LENGTH:
        reason = "title-too-short"
        if enable_logging:
            log_rejection(item, source, reason)
        return False, reason
    
    # 0. Kiểm tra bài viết ngoài phạm vi công nghệ (nông nghiệp, chăn nuôi, y tế...)
    if OUT_OF_SCOPE.search(title) or OUT_OF_SCOPE.search(summary[:300]):
        reason = "out-of-scope"
        if enable_logging:
            log_rejection(item, source, reason)
        return False, reason

    # 1. Kiểm tra blocklist (quảng cáo, deal, khuyến mãi, tuyển dụng, trailer, review, weekly)
    review_exception = bool(REVIEW.search(title) and REVIEW_ALLOW.search(title))
    if BLOCK.search(title) or CONFIG_BLOCK.search(title) or EDITORIAL_OR_REVIEW.search(title) or (REVIEW.search(title) and not review_exception):
        reason = "blocklist-title"
        if enable_logging:
            log_rejection(item, source, reason)
        return False, reason

    if BLOCK.search(summary[:200]) or CONFIG_BLOCK.search(summary[:200]):
        reason = "blocklist-summary"
        if enable_logging:
            log_rejection(item, source, reason)
        return False, reason

    # 2. Kiểm tra bài tự quảng bá cá nhân (đặc thù Dev.to)
    if DEVTO_SELF_PROMO.search(summary) or DEVTO_SELF_PROMO.search(title):
        reason = "self-promotion"
        if enable_logging:
            log_rejection(item, source, reason)
        return False, reason

    # 3. Kiểm tra nguồn tips vs nguồn news
    kind = source.get("kind", "news") if isinstance(source, dict) else "news"
    if kind == "tips":
        return True, "tips-source"
    if source.get("allowNews"):
        return True, "news-source"
    
    # 4. Nguồn tin tức chung: bắt buộc phải khớp từ khóa how-to
    if HOWTO.search(title) or CONFIG_HOWTO.search(title) or HOWTO.search(summary[:140]) or CONFIG_HOWTO.search(summary[:140]):
        return True, "howto-match"
        
    reason = "not-howto"
    if enable_logging:
        log_rejection(item, source, reason)
    return False, reason
