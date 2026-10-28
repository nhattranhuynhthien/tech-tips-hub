# scripts/dedupe.py
import re
import hashlib
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "ref", "source", "mc_cid", "mc_eid"
}

def canonical_url(url: str) -> str:
    """Chuẩn hóa URL, loại bỏ toàn bộ tham số tracking và trailing slash."""
    if not url:
        return ""
    p = urlsplit(url.strip())
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=False) if k.lower() not in TRACKING_PARAMS]
    clean_query = urlencode(q)
    clean_path = p.path.rstrip("/")
    if not clean_path:
        clean_path = "/"
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), clean_path, clean_query, ""))

def generate_id(url: str) -> str:
    """Tạo ID cố định 16 ký tự từ canonical URL."""
    c_url = canonical_url(url)
    return hashlib.sha1(c_url.encode("utf-8")).hexdigest()[:16]

def normalize_title(title: str) -> str:
    """Chuẩn hóa chuỗi tiêu đề để so sánh trùng lặp."""
    t = (title or "").lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def is_duplicate_title(title1: str, title2: str, threshold: float = 0.8) -> bool:
    """So sánh độ trùng lặp 2 tiêu đề theo Jaccard coefficient của tập từ vựng."""
    w1 = set(normalize_title(title1).split())
    w2 = set(normalize_title(title2).split())
    if not w1 or not w2:
        return False
    intersection = len(w1 & w2)
    union = len(w1 | w2)
    similarity = intersection / union if union > 0 else 0
    return similarity >= threshold

def is_blocked(title: str, summary: str, url: str, blocklist: dict) -> bool:
    """Kiểm tra xem bài viết có vi phạm blocklist (deal, quảng cáo, spam domain) không."""
    combined = f"{title} {summary}".lower()
    
    # 1. Kiểm tra domain
    blocked_domains = blocklist.get("domains", [])
    for d in blocked_domains:
        if d.lower() in url.lower():
            return True

    # 2. Kiểm tra từ khóa quảng cáo / deal
    blocked_keywords = blocklist.get("keywords", [])
    for kw in blocked_keywords:
        pattern = r"\b" + re.escape(kw.lower()) + r"\b"
        if re.search(pattern, combined):
            return True

    # 3. Kiểm tra regex tiêu đề
    title_patterns = blocklist.get("title_patterns", [])
    for p in title_patterns:
        try:
            if re.search(p, title, flags=re.IGNORECASE):
                return True
        except Exception:
            continue

    return False
