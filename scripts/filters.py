# scripts/filters.py
import re

HOWTO = re.compile(
    r"\b(how to|how-to|tips?|tricks?|guide|tutorial|fix(es|ing)?|set ?up|"
    r"enable|disable|hidden|settings?|shortcuts?|things to do|"
    r"cách|mẹo|hướng dẫn|thủ thuật|sửa lỗi|thiết lập|chỉnh|phím tắt)\b",
    re.IGNORECASE
)

BLOCK = re.compile(
    r"(\bdeals?\b|\bdiscount\b|\bcoupon\b|% off|\$\d+ off|drops to|price cut|"
    r"\bsale\b|giảm giá|khuyến mãi|\[QC\]|sponsored|giveaway|"
    r"is hiring|\bhiring\b|tuyển dụng|\btrailer\b)",
    re.IGNORECASE
)

def is_howto_match(title: str, summary: str = "") -> bool:
    """Kiểm tra bài viết có dấu hiệu là thủ thuật / hướng dẫn (how-to) hay không."""
    return bool(HOWTO.search(title)) or bool(HOWTO.search(summary[:120]))

def accept(item: dict, source: dict) -> tuple[bool, str]:
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
        return False, "blocklist-title"
    if BLOCK.search(summary[:200]):
        return False, "blocklist-summary"

    # 2. Kiểm tra nguồn tips vs nguồn news
    kind = source.get("kind", "news") if isinstance(source, dict) else "news"
    if kind == "tips":
        return True, "tips-source"
    
    # 3. Nguồn tin tức chung: bắt buộc phải khớp từ khóa how-to
    if HOWTO.search(title) or HOWTO.search(summary[:120]):
        return True, "howto-match"
        
    return False, "not-howto"
