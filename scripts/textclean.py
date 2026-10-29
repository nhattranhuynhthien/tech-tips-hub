# scripts/textclean.py
import html
import re

BOILERPLATE = [
    r"The post .*? appeared first on .*?\.?$",
    r"Article URL:\s*https?://\S+(\s*Comments URL:\s*https?://\S+)?(\s*Points:\s*\d+)?(\s*#\s*Comments:\s*\d+)?",
    r"Originally published at \S+",
    r"\s*more…\s*$",
    r"\s*\[(\.\.\.|…)\]\s*$",
    r"\s*\(\.\.\.\)\s*$",
    r"\s*\.\.\.\s*$",
]

def unescape_all(t: str) -> str:
    """Giải mã HTML entities triệt để, xử lý cả mã hóa kép (&amp;ecirc; -> &ecirc; -> ê)."""
    if not t:
        return ""
    prev = None
    curr = t
    # Lặp tối đa 5 lần tránh vòng lặp vô tận
    for _ in range(5):
        if prev == curr:
            break
        prev = curr
        curr = html.unescape(curr)
    return curr

def clean_text(t: str, limit: int = 300) -> str:
    """Làm sạch văn bản, gỡ mã HTML, loại bỏ boilerplate và cắt gọt chuẩn câu."""
    if not t:
        return ""
    t = unescape_all(t)
    # Loại bỏ tag HTML
    t = re.sub(r"<[^>]+>", " ", t)
    # Chuẩn hóa khoảng trắng
    t = re.sub(r"\s+", " ", t).strip()
    # Loại bỏ boilerplate text
    for p in BOILERPLATE:
        t = re.sub(p, "", t, flags=re.I | re.S).strip()
    
    if len(t) > limit:
        cut = t[:limit].rsplit(" ", 1)[0]
        t = cut.rstrip(",;:-–— ") + "…"
    return t

def strip_title_prefix(summary: str, title: str) -> str:
    """Nếu tóm tắt bắt đầu bằng tiêu đề thì cắt bỏ phần trùng."""
    if not summary or not title:
        return summary or ""
    s, t = summary.strip(), title.strip()
    # So sánh phần đầu khoảng 40 ký tự
    prefix_len = min(len(t), 40)
    if prefix_len > 10 and s.lower().startswith(t.lower()[:prefix_len]):
        if s.lower().startswith(t.lower()):
            s = s[len(t):].lstrip(" -–—:.\n")
        else:
            # Cắt tới dấu phân cách đầu tiên
            idx = s.find(" - ")
            if 0 < idx < len(t) + 10:
                s = s[idx + 3:].strip()
    return s

