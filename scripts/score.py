# scripts/score.py
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

ADV = re.compile(r"\b(terminal|sudo|registry|regedit|powershell|docker|kernel|root|ssh|script|cli|bash)\b", re.IGNORECASE)
EASY = re.compile(r"\b(settings?|enable|disable|shortcut|toggle|bật|tắt|phím tắt|cài đặt)\b", re.IGNORECASE)

TUTORIAL_KEYWORDS = [
    # English
    "how to", "how-to", "tutorial", "guide", "tip", "tips", "trick", "tricks", "shortcut",
    "shortcuts", "hidden", "secret", "best way to", "fix", "troubleshoot",
    "speed up", "optimize", "customize", "tweak", "setup", "cheat sheet",
    # Tiếng Việt
    "cách", "hướng dẫn", "thủ thuật", "mẹo", "phím tắt", "tinh chỉnh", "tối ưu",
    "khắc phục", "sửa lỗi", "bật tính năng", "ẩn", "cài đặt", "tiết kiệm", "tăng tốc"
]

def parse_published_time(date_str: str) -> datetime:
    """Chuyển đổi chuỗi ngày tháng đa định dạng về datetime UTC."""
    if not date_str:
        return datetime.now(timezone.utc)
    try:
        return parsedate_to_datetime(date_str).astimezone(timezone.utc)
    except Exception:
        pass
    try:
        clean_str = date_str.replace("Z", "+00:00")
        return datetime.fromisoformat(clean_str).astimezone(timezone.utc)
    except Exception:
        pass
    return datetime.now(timezone.utc)

def calculate_score(title: str, summary: str, source_weight: float, published_at: str, is_howto: bool = False) -> float:
    """
    Tính điểm chất lượng và mức độ hữu ích của thủ thuật:
    Score = Trọng số nguồn x Hệ số độ mới x Điểm chất lượng nội dung
    """
    text = f"{title} {summary}".lower()
    
    # 1. Hệ số hướng dẫn (tutorial signals)
    signal_count = sum(1 for kw in TUTORIAL_KEYWORDS if kw in text)
    if is_howto:
        signal_count += 2
    tutorial_multiplier = 1.0 + min(signal_count * 0.12, 0.5)

    # 2. Hệ số độ mới (Recency)
    pub_dt = parse_published_time(published_at)
    now_dt = datetime.now(timezone.utc)
    age_hours = max(0.0, (now_dt - pub_dt).total_seconds() / 3600.0)
    
    if age_hours <= 24:
        recency_multiplier = 1.25
    elif age_hours <= 72:
        recency_multiplier = 1.15
    elif age_hours <= 168:  # 7 ngày
        recency_multiplier = 1.0
    elif age_hours <= 720:  # 30 ngày
        recency_multiplier = 0.85
    else:
        recency_multiplier = 0.65

    # 3. Điểm cơ sở
    base_score = float(source_weight) * 0.75

    # 4. Kiểm tra độ dài có ích của tóm tắt
    length_bonus = 0.08 if len(summary.strip()) >= 60 else -0.1

    final_score = (base_score + length_bonus) * tutorial_multiplier * recency_multiplier
    return round(max(0.1, min(final_score, 1.5)), 2)

def detect_difficulty(title: str, summary: str, howto: bool = True):
    """
    Xác định độ khó: easy (dễ), medium (vừa), advanced (nâng cao).
    Chỉ gán cho bài howto thật. Bài khác trả về None.
    """
    if not howto:
        return None
    text = f"{title} {summary}".lower()
    if ADV.search(text):
        return "advanced"
    if EASY.search(text):
        return "easy"
    return "medium"
