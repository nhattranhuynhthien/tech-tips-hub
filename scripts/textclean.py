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

# Danh sách thẻ HTML5 thực thụ (loại trừ kiểu generic như <int>, <String>, <T>)
_HTML_TAG_NAMES = (
    r"a|abbr|address|area|article|aside|audio|b|base|bdi|bdo|blockquote|body|br|button|"
    r"canvas|caption|cite|code|col|colgroup|data|datalist|dd|del|details|dfn|dialog|div|"
    r"dl|dt|em|embed|fieldset|figcaption|figure|footer|form|h[1-6]|head|header|hgroup|hr|"
    r"html|i|iframe|img|input|ins|kbd|label|legend|li|link|main|map|mark|marquee|math|menu|"
    r"meta|meter|nav|noscript|object|ol|optgroup|option|output|p|param|picture|pre|progress|"
    r"q|rp|rt|ruby|s|samp|script|search|section|select|slot|small|source|span|strong|style|"
    r"sub|summary|sup|svg|table|tbody|td|template|textarea|tfoot|th|thead|time|title|tr|"
    r"track|u|ul|var|video|wbr"
)

# Giá trị thuộc tính HTML5 chống ReDoS (dùng nhóm nguyên tử & lượng từ possessive của Python 3.11+,
# hỗ trợ '>' nằm trong nháy kép/đơn và thuộc tính ngăn cách bằng '/')
_HTML_ATTR_VAL = r'(?>"[^"]*+"|\'[^\']*+\'|https?://[^\s"\'<>`]++|[^\s"\'=<>`/]++)'
_HTML_ATTR_BOOL_ONLY = r'(?>[\s/]++[a-zA-Z_:][a-zA-Z0-9_.:-]*+(?!\s*+=))'
_HTML_ATTR_REQUIRED_EQ = rf'(?>[\s/]++[a-zA-Z_:][a-zA-Z0-9_.:-]*+\s*+=\s*+{_HTML_ATTR_VAL})'
_HTML_ATTR_OPT = rf'(?>[\s/]++[a-zA-Z_:][a-zA-Z0-9_.:-]*+(?>\s*+=\s*+{_HTML_ATTR_VAL})?+)'

# Khối <script>/<style> đóng đầy đủ và cả dạng mở không đóng đến cuối chuỗi
SCRIPT_STYLE_RE = re.compile(
    rf"<\s*+(script|style)(?:{_HTML_ATTR_OPT})*+\s*+>.*?<\s*+/\s*+\1\s*+>",
    flags=re.IGNORECASE | re.DOTALL,
)
UNCLOSED_SCRIPT_STYLE_RE = re.compile(
    r"<\s*+(?:script|style)(?=[\s/>]|$).*$",
    flags=re.IGNORECASE | re.DOTALL,
)

# Bộ nhận diện thẻ HTML thô dùng chung cho textclean.py, translate.py và qa.py:
# - Bắt comment HTML, thẻ đóng, thẻ <script>/<style> chưa đóng, mọi thẻ HTML5 chuẩn (kể cả slash-attrs & '>' trong nháy)
#   và thẻ tùy biến có thuộc tính '='.
# - Bảo toàn nguyên vẹn C++ generics (std::vector<int>, Map<String, T>) và phép so sánh (x < 10, (a<b && c>d)).
RAW_HTML_TAG_RE = re.compile(
    r"<!--.*?-->|"
    r"</\s*+[a-zA-Z][a-zA-Z0-9-]*+\s*+>|"
    r"<\s*+(?:script|style)(?=[\s/>]|$)|"
    rf"<\s*+(?:{_HTML_TAG_NAMES})(?:{_HTML_ATTR_OPT})*+\s*+/?+>|"
    rf"<\s*+[a-zA-Z][a-zA-Z0-9-]*+(?:{_HTML_ATTR_BOOL_ONLY})*+{_HTML_ATTR_REQUIRED_EQ}(?:{_HTML_ATTR_OPT})*+\s*+/?+>",
    flags=re.IGNORECASE | re.DOTALL,
)

URL_TOKEN_RE = re.compile(r"https?://[^\s)\]}>\"']+", flags=re.IGNORECASE)


def is_url_only_text(text: str) -> bool:
    """Trả về True nếu văn bản chỉ gồm một hoặc nhiều URL trần (kèm khoảng trắng/dấu câu/ngoặc/dấu ba chấm)."""
    if not isinstance(text, str) or not text.strip():
        return False
    if not URL_TOKEN_RE.search(text):
        return False
    remainder = URL_TOKEN_RE.sub(" ", text)
    return re.search(r"[^\W_]", remainder, re.UNICODE) is None


def strip_html_tags(text: str) -> str:
    """Gỡ triệt để <script>/<style> (kể cả chưa đóng) và mọi thẻ HTML thực sự mà vẫn giữ generics & phép so sánh."""
    if not text:
        return ""
    text = SCRIPT_STYLE_RE.sub(" ", text)
    text = UNCLOSED_SCRIPT_STYLE_RE.sub(" ", text)
    text = RAW_HTML_TAG_RE.sub(" ", text)
    return text


def unescape_all(t: str) -> str:
    """Giải mã HTML entities triệt để, xử lý cả mã hóa sâu nhiều tầng (&amp;...&lt; -> <)."""
    if not t:
        return ""
    prev = None
    curr = t
    for _ in range(12):
        if prev == curr:
            break
        prev = curr
        curr = html.unescape(curr)
    return curr


def clean_text(t: str, limit: int = 300) -> str:
    """Làm sạch văn bản, gỡ mã HTML thực sự (giữ nguyên <int>, (a<b && c>d)), loại bỏ boilerplate và cắt gọt chuẩn câu."""
    if not t:
        return ""
    # 1. Xóa trọn khối <script>/<style> (đóng hoặc chưa đóng) và thẻ HTML thật TRƯỚC khi giải mã entities
    t = strip_html_tags(t)

    # 2. Giải mã HTML entities nhiều tầng (kể cả mã hóa lồng sâu 6x+)
    t = unescape_all(t)

    # 3. Gỡ tiếp mọi <script>/<style> và thẻ HTML thật vừa lộ ra sau khi unescape,
    #    nhưng vẫn giữ nguyên <int>, <String>, <T>, x < 10 and y > 20, và (a<b && c>d).
    t = strip_html_tags(t)

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
