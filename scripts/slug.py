# scripts/slug.py
import re
import unicodedata

def generate_seo_slug(title: str, item_id: str) -> str:
    """Tạo SEO-friendly slug kết hợp tiêu đề không dấu và 6 ký tự hash ID."""
    if not title:
        return f"tip-{item_id[:6]}"
    
    text = unicodedata.normalize("NFD", title)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "d")
    text = re.sub(r"[^a-zA-Z0-9\s-]", "", text).lower().strip()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)[:60].rstrip("-")
    short_hash = item_id[:6]
    return f"{text or 'tip'}-{short_hash}"
