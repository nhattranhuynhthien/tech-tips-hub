# scripts/filters.py
import re
import json
from pathlib import Path
from datetime import datetime, timezone

LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
REJECTED_LOG = LOG_DIR / "rejected.jsonl"

HOWTO = re.compile(
    r"\b(how to|how-to|tips?|tricks?|guide|tutorial|fix(es|ing)?|set ?up|"
    r"enable|disable|hidden|settings?|shortcuts?|things to do|walkthrough|"
    r"cách|mẹo|hướng dẫn|thủ thuật|sửa lỗi|thiết lập|chỉnh|phím tắt|tinh chỉnh)\b",
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

def is_howto_match(title: str, summary: str = "") -> bool:
    """Kiểm tra bài viết có dấu hiệu là thủ thuật / hướng dẫn (how-to) hay không."""
    return bool(HOWTO.search(title)) or bool(HOWTO.search(summary[:140]))

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
    
    # 1. Kiểm tra blocklist (quảng cáo, deal, khuyến mãi, tuyển dụng, trailer)
    if BLOCK.search(title):
        reason = "blocklist-title"
        if enable_logging:
            log_rejection(item, source, reason)
        return False, reason

    if BLOCK.search(summary[:200]):
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
    
    # 4. Nguồn tin tức chung: bắt buộc phải khớp từ khóa how-to
    if HOWTO.search(title) or HOWTO.search(summary[:140]):
        return True, "howto-match"
        
    reason = "not-howto"
    if enable_logging:
        log_rejection(item, source, reason)
    return False, reason
