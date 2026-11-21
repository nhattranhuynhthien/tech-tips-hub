# scripts/score.py
import calendar
import math
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

ADV = re.compile(r"\b(terminal|sudo|registry|regedit|powershell|docker|kernel|root|ssh|script|cli|bash)\b", re.IGNORECASE)
EASY = re.compile(r"\b(settings?|enable|disable|shortcut|toggle|bật|tắt|phím tắt|cài đặt)\b", re.IGNORECASE)

UNICODE_SPACES_RE = re.compile(r"[\u00a0\u2007\u2009\u202f]+")
SHORT_RFC_TZ_RE = re.compile(r"(?<=\s)([+-]\d{2})$")
SHORT_ISO_TZ_RE = re.compile(r"(?<=\d)([+-]\d{2})$")
MAX_FUTURE_SKEW = timedelta(days=7)

LOCALE_DATE_FORMATS = (
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %I:%M:%S %p",
    "%Y/%m/%d %H:%M:%S",
)

TUTORIAL_KEYWORDS = [
    # English
    "how to", "how-to", "tutorial", "guide", "tip", "tips", "trick", "tricks", "shortcut",
    "shortcuts", "hidden", "secret", "best way to", "fix", "troubleshoot",
    "speed up", "optimize", "customize", "tweak", "setup", "cheat sheet",
    # Tiếng Việt
    "cách", "hướng dẫn", "thủ thuật", "mẹo", "phím tắt", "tinh chỉnh", "tối ưu",
    "khắc phục", "sửa lỗi", "bật tính năng", "ẩn", "cài đặt", "tiết kiệm", "tăng tốc"
]


def _coerce_tz(default_tz=None) -> timezone:
    """Chuẩn hóa tham số múi giờ mặc định về đối tượng datetime.timezone."""
    if default_tz is None:
        return timezone.utc
    if isinstance(default_tz, timezone):
        return default_tz
    if isinstance(default_tz, timedelta):
        return timezone(default_tz)
    if isinstance(default_tz, (int, float)):
        return timezone(timedelta(hours=default_tz))
    if isinstance(default_tz, str):
        token = default_tz.strip().lower()
        if token in ("vi", "tuoitre", "tuoitre-nsso", "+07:00", "+0700", "+07", "asia/ho_chi_minh"):
            return timezone(timedelta(hours=7))
    return timezone.utc


def _normalize_date_text(date_str: str) -> str:
    """Chuẩn hóa khoảng trắng Unicode (như \\u202f, \\u00a0, \\u2009) về dấu cách ASCII chuẩn."""
    if not isinstance(date_str, str):
        return ""
    cleaned = UNICODE_SPACES_RE.sub(" ", date_str)
    return re.sub(r"\s+", " ", cleaned).strip()


def _is_reasonable_date(dt: datetime) -> bool:
    """Từ chối mốc thời gian tương lai quá xa (ví dụ năm 2099) gây đầu độc thứ tự sắp xếp và điểm độ mới."""
    now_utc = datetime.now(timezone.utc)
    return dt.year >= 1970 and dt <= now_utc + MAX_FUTURE_SKEW


def _parse_datetime_or_none(date_str: str, default_tz=None) -> datetime | None:
    """Phân tích chuỗi ngày tháng đa định dạng về datetime UTC; trả về None nếu không hợp lệ hoặc quá xa tương lai."""
    cleaned = _normalize_date_text(date_str)
    if not cleaned:
        return None
    tz = _coerce_tz(default_tz)

    # 1. RFC 2822 (chuẩn hóa offset 2 chữ số kiểu '+07' -> '+0700' trước khi parse)
    rfc_candidate = SHORT_RFC_TZ_RE.sub(r"\g<1>00", cleaned)
    try:
        dt = parsedate_to_datetime(rfc_candidate)
        if dt is not None:
            dt_utc = dt.replace(tzinfo=tz).astimezone(timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
            return dt_utc if _is_reasonable_date(dt_utc) else None
    except Exception:
        pass

    # 2. ISO-8601 (hỗ trợ cả 'T' và 't' theo RFC 3339, kể cả offset 2 chữ số kiểu '-05')
    iso_candidate = re.sub(r"[zZ]$", "+00:00", cleaned)
    if "t" in iso_candidate.lower() or re.match(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}", iso_candidate):
        iso_candidate = SHORT_ISO_TZ_RE.sub(r"\g<1>:00", iso_candidate)
    try:
        dt = datetime.fromisoformat(iso_candidate)
        dt_utc = dt.replace(tzinfo=tz).astimezone(timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        return dt_utc if _is_reasonable_date(dt_utc) else None
    except Exception:
        pass

    # 3. Các định dạng ngày địa phương / US (ví dụ Tuổi Trẻ: '10/16/2026 8:42:00 AM')
    for fmt in LOCALE_DATE_FORMATS:
        try:
            dt = datetime.strptime(cleaned, fmt)
            dt_utc = dt.replace(tzinfo=tz).astimezone(timezone.utc)
            return dt_utc if _is_reasonable_date(dt_utc) else None
        except ValueError:
            continue

    return None


def parse_published_time(date_str: str, default_tz=None) -> datetime:
    """Chuyển đổi chuỗi ngày tháng đa định dạng về datetime UTC (coi chuỗi không múi giờ theo default_tz, mặc định UTC)."""
    dt = _parse_datetime_or_none(date_str, default_tz=default_tz)
    return dt if dt is not None else datetime.now(timezone.utc)


def normalize_published_iso(date_str: str, parsed_struct=None, default_offset_hours: int = 0) -> str:
    """Chuẩn hóa mọi định dạng ngày của feed (kể cả time.struct_time từ feedparser) về ISO-8601 UTC."""
    default_tz = timezone(timedelta(hours=default_offset_hours)) if default_offset_hours else timezone.utc
    dt = _parse_datetime_or_none(date_str, default_tz=default_tz)
    if dt is not None:
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()

    if parsed_struct is not None:
        try:
            if len(parsed_struct) >= 6:
                ts = calendar.timegm(tuple(int(x) for x in parsed_struct[:6]) + (0, 0, 0))
                dt_struct = datetime.fromtimestamp(ts, tz=timezone.utc)
                if _is_reasonable_date(dt_struct):
                    return dt_struct.replace(microsecond=0).isoformat()
        except Exception:
            pass

    return ""

def calculate_score(
    title: str,
    summary: str,
    source_weight: float,
    published_at: str,
    is_howto: bool = False,
    community_signal: int = 0
) -> float:
    """
    Tính điểm chất lượng và mức độ hữu ích của thủ thuật:
    Score = (Trọng số nguồn + Tín hiệu cộng đồng + Chất lượng tóm tắt) x Hệ số hướng dẫn x Hệ số độ mới
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

    # 3. Điểm cơ sở từ trọng số nguồn (chống NaN/Inf/âm)
    try:
        sw = float(source_weight)
    except (TypeError, ValueError):
        sw = 0.0
    if not math.isfinite(sw) or sw < 0:
        sw = 0.0
    base_score = sw * 0.75

    # 4. Thưởng tín hiệu cộng đồng (HN points, Dev.to reactions)
    comm_bonus = 0.0
    try:
        cs = float(community_signal)
    except (TypeError, ValueError):
        cs = 0.0
    if math.isfinite(cs) and cs > 0:
        comm_bonus = min(0.2, (cs / 200.0) * 0.1)

    # 5. Kiểm tra độ dài có ích của tóm tắt
    length_bonus = 0.08 if len(summary.strip()) >= 60 else -0.1

    final_score = (base_score + length_bonus + comm_bonus) * tutorial_multiplier * recency_multiplier
    if not math.isfinite(final_score):
        return 0.1
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
