# scripts/score.py
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

TUTORIAL_KEYWORDS = [
    # English
    "how to", "tutorial", "guide", "tip", "tips", "trick", "tricks", "shortcut",
    "shortcuts", "hidden", "secret", "best way to", "fix", "troubleshoot",
    "speed up", "optimize", "customize", "tweak", "setup", "cheat sheet",
    # Tiếng Việt
    "cách", "hướng dẫn", "thủ thuật", "mẹo", "phím tắt", "tinh chỉnh", "tối ưu",
    "khắc phục", "sửa lỗi", "bật tính năng", "ẩn", "cài đặt", "tiết kiệm", "tăng tốc"
]

ADVANCED_KEYWORDS = [
    "terminal", "registry", "powershell", "bash", "root", "jailbreak", "kernel",
    "docker", "kubernetes", "compile", "bios", "uefi", "wireshark", "reverse engineering",
    "quản trị", "nâng cao", "dòng lệnh", "mã nguồn"
]

EASY_KEYWORDS = [
    "beginner", "basic", "simple", "easy", "quick", "shortcut", "settings",
    "cơ bản", "đơn giản", "nhanh", "người mới", "phím tắt"
]

def parse_published_time(date_str: str) -> datetime:
    """Chuyển đổi chuỗi ngày tháng đa định dạng về datetime UTC."""
    if not date_str:
        return datetime.now(timezone.utc)
    try:
        # Định dạng RFC 2822 chuẩn của RSS
        return parsedate_to_datetime(date_str).astimezone(timezone.utc)
    except Exception:
        pass
    try:
        # ISO format
        clean_str = date_str.replace("Z", "+00:00")
        return datetime.fromisoformat(clean_str).astimezone(timezone.utc)
    except Exception:
        pass
    return datetime.now(timezone.utc)

def calculate_score(title: str, summary: str, source_weight: float, published_at: str) -> float:
    """
    Tính điểm chất lượng thủ thuật:
    Score = Trọng số nguồn x Hệ số độ mới x Điểm chất lượng nội dung
    """
    text = f"{title} {summary}".lower()
    
    # 1. Hệ số hướng dẫn (tutorial signals)
    signal_count = sum(1 for kw in TUTORIAL_KEYWORDS if kw in text)
    tutorial_multiplier = 1.0 + min(signal_count * 0.15, 0.6) # Max +60%

    # 2. Hệ số độ mới (Recency)
    pub_dt = parse_published_time(published_at)
    now_dt = datetime.now(timezone.utc)
    age_hours = max(0.0, (now_dt - pub_dt).total_seconds() / 3600.0)
    
    if age_hours <= 24:
        recency_multiplier = 1.2
    elif age_hours <= 72:
        recency_multiplier = 1.1
    elif age_hours <= 168: # 7 ngày
        recency_multiplier = 1.0
    elif age_hours <= 720: # 30 ngày
        recency_multiplier = 0.85
    else:
        recency_multiplier = 0.7

    # 3. Điểm cơ sở
    base_score = float(source_weight) * 0.7

    # 4. Kiểm tra độ dài có ích của tóm tắt
    length_bonus = 0.1 if len(summary.strip()) >= 60 else -0.15

    final_score = (base_score + length_bonus) * tutorial_multiplier * recency_multiplier
    return round(max(0.1, min(final_score, 1.5)), 2)

def detect_difficulty(title: str, summary: str) -> str:
    """Xác định độ khó: easy (dễ), medium (vừa), advanced (nâng cao)."""
    text = f"{title} {summary}".lower()
    if any(kw in text for kw in ADVANCED_KEYWORDS):
        return "advanced"
    if any(kw in text for kw in EASY_KEYWORDS):
        return "easy"
    return "medium"

def extract_categories_and_tags(title: str, summary: str, configured_categories: list, default_cats: list) -> tuple[list[str], list[str]]:
    """Tự động phân loại danh mục và gán tags dựa trên cấu hình keywords."""
    text = f"{title} {summary}".lower()
    matched_cats = set(default_cats or [])
    matched_tags = set()

    for cat in configured_categories:
        cat_id = cat["id"]
        for kw in cat.get("keywords", []):
            pattern = r"\b" + re.escape(kw.lower()) + r"\b"
            if re.search(pattern, text):
                matched_cats.add(cat_id)
                matched_tags.add(kw.lower())

    if not matched_cats:
        matched_cats.add("windows" if "pc" in text else "browser")

    # Thêm tag độ khó và định dạng
    if "shortcut" in text or "phím tắt" in text:
        matched_tags.add("shortcut")
    if "battery" in text or "pin" in text:
        matched_tags.add("battery")
    if "privacy" in text or "bảo mật" in text:
        matched_tags.add("privacy")
    if "performance" in text or "tăng tốc" in text:
        matched_tags.add("performance")

    return sorted(list(matched_cats)), sorted(list(matched_tags))[:5]

