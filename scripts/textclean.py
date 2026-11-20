# scripts/textclean.py
import html
import re

BOILERPLATE = [
    r"The post .*? appeared first on .*?\.?$",
    r"Article URL:\s*https?://\S+(\s*Comments URL:\s*https?://\S+)?(\s*Points:\s*\d+)?(\s*#\s*Comments:\s*\d+)?",
    r"Originally published at \S+",
    r"\s*submitted by\s+/u/\S+.*$",
    r"\s*\[link\]\s*\[comments\].*$",
    r"\s*\[comments\].*$",
    r"\s*more…\s*$",
    r"\s*\[(\.\.\.|…)\]\s*$",
    r"\s*\(\.\.\.\)\s*$",
    r"\s*\.\.\.\s*$",
]

SCRIPT_STYLE_RE = re.compile(r"<\s*(script|style)\b[^>]*>.*?<\s*/\s*\1\s*>", flags=re.I | re.S)
HTML_TAG_RE = re.compile(r"</?[a-zA-Z!][^>]*>")
ESCAPED_BLOCK_HTML_RE = re.compile(
    r"<\s*/\s*[a-zA-Z0-9]+\s*>|<\s*(?:p|div|br|hr|img|a|ul|ol|li|blockquote|table|tr|td|th|figure|iframe|section|article)\b[^>]*>",
    flags=re.I,
)


def unescape_all(t: str) -> str:
    """Giải mã HTML entities triệt để, xử lý cả mã hóa kép (&amp;ecirc; -> &ecirc; -> ê)."""
    if not t:
        return ""
    prev = None
    curr = t
    for _ in range(5):
        if prev == curr:
            break
        prev = curr
        curr = html.unescape(curr)
    return curr


def clean_text(t: str, limit: int = 300) -> str:
    """Làm sạch văn bản, gỡ mã HTML thực sự (giữ nguyên <int>, x < 10), loại bỏ boilerplate và cắt gọt chuẩn câu."""
    if not t:
        return ""
    # 1. Xóa trọn khối <script>/<style> và gỡ thẻ HTML thật TRƯỚC khi giải mã entities
    #    để giữ nguyên các ký hiệu kỹ thuật đã escape như std::vector&lt;int&gt; hoặc x &lt; 10.
    t = SCRIPT_STYLE_RE.sub(" ", t)
    t = HTML_TAG_RE.sub(" ", t)

    # 2. Giải mã HTML entities (kể cả mã hóa kép)
    t = unescape_all(t)

    # 3. Dọn các thẻ HTML khối nếu nguồn RSS bị mã hóa kép (&lt;p&gt;...&lt;/p&gt;),
    #    nhưng không chạm vào <int>, <String>, <T>, hay phép so sánh x < 10 and y > 20.
    t = SCRIPT_STYLE_RE.sub(" ", t)
    t = ESCAPED_BLOCK_HTML_RE.sub(" ", t)

    # 4. Chuẩn hóa khoảng trắng & loại bỏ boilerplate
    t = re.sub(r"\s+", " ", t).strip()
    for p in BOILERPLATE:
        t = re.sub(p, "", t, flags=re.I | re.S).strip()

    if len(t) > limit:
        window = t[:limit]
        last_space = window.rfind(" ")
        cut = window[:last_space] if last_space >= int(limit * 0.6) else window
        t = cut.rstrip(",;:-–—、，。 ") + "…"
    return t


def clean_title(title: str, limit: int = 160) -> str:
    """Làm sạch tiêu đề: loại bỏ tiền tố thừa như LPT:, chuẩn hóa khoảng trắng và độ dài."""
    if not title:
        return ""
    t = clean_text(title, limit=limit)
    t = re.sub(r"^LPT\s*[:\-]?\s*", "", t, flags=re.IGNORECASE).strip()
    return t


def strip_title_prefix(summary: str, title: str) -> str:
    """Nếu tóm tắt bắt đầu bằng tiêu đề thì cắt bỏ phần trùng."""
    if not summary or not title:
        return summary or ""
    s, t = summary.strip(), title.strip()
    prefix_len = min(len(t), 40)
    if prefix_len > 10 and s.lower().startswith(t.lower()[:prefix_len]):
        if s.lower().startswith(t.lower()):
            s = s[len(t):].lstrip(" -–—:.\n")
        else:
            idx = s.find(" - ")
            if 0 < idx < len(t) + 10:
                s = s[idx + 3:].strip()
    return s
