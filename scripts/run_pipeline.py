# scripts/run_pipeline.py
import sys
import json
import math
import yaml
import time
import random
from urllib.parse import urlsplit
from pathlib import Path
from datetime import datetime, timezone, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fetch import fetch_feed_items, SourceFetchError
from dedupe import canonical_url, is_duplicate_title, is_blocked
from filters import accept, is_howto_match, log_rejection
from classify import classify, extract_tags
from score import calculate_score, detect_difficulty, parse_published_time, normalize_published_iso
from slug import generate_seo_slug
from textclean import clean_text, clean_title
from translate import (
    load_cache,
    save_cache,
    process_item_bilingual,
    batch_translate_pending,
    normalize_key_points_map,
)

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
INDEX_PATH = DATA_DIR / "index.json"
STATE_PATH = DATA_DIR / "state.json"
COMMUNITY_PATH = DATA_DIR / "community.json"
HEALTH_PATH = DATA_DIR / "health.json"

def estimate_reading_time(text: str) -> int:
    """Ước lượng thời gian đọc (khoảng 150-200 từ/phút)."""
    words = len(text.split())
    return max(1, round(words / 175))


def sync_item_key_points(item: dict, cache_entry: dict | None = None) -> None:
    """Bảo toàn và chuẩn hóa key_points từ kết quả dịch hoặc cache; bỏ hẳn trường nếu rỗng."""
    merged = normalize_key_points_map((cache_entry or {}).get("key_points"))
    merged.update(normalize_key_points_map(item.get("key_points")))
    if merged:
        item["key_points"] = merged
    else:
        item.pop("key_points", None)

def _is_community_item(item: dict) -> bool:
    """Kiểm tra bài viết có thuộc nguồn cộng đồng (Reddit, HN, Dev.to, Community...) hay không."""
    src = item.get("source") or {}
    return (
        src.get("content_type") == "community"
        or item.get("content_type") == "community"
        or "reddit" in str(src.get("id", "")).lower()
    )


def _safe_score(item: dict) -> float:
    """Chuyển điểm số về float hữu hạn an toàn (chống score=None/NaN/Inf gây lỗi sắp xếp)."""
    val = item.get("score")
    try:
        f = float(val)
        return f if math.isfinite(f) else 0.0
    except (TypeError, ValueError):
        return 0.0


def diversify(items: list[dict], max_run: int = 2, max_community_per_window: int = 3, window_size: int = 20) -> list[dict]:
    """
    Xen kẽ nguồn để danh sách đa dạng và hấp dẫn:
    1. Không để quá max_run bài liên tiếp từ cùng một nguồn.
    2. Giới hạn tỷ lệ nguồn Cộng đồng (Reddit, Telegram, Facebook...) không quá max_community_per_window
       trong mỗi cửa sổ window_size bài (tối đa ~15% trang) để không lấn át báo chí công nghệ.
    """
    pending = sorted(items, key=lambda x: -_safe_score(x))
    out = []
    while pending:
        for idx, it in enumerate(pending):
            run = 0
            for prev in reversed(out):
                prev_src = prev.get("source", {}).get("id")
                curr_src = it.get("source", {}).get("id")
                if prev_src and curr_src and prev_src == curr_src:
                    run += 1
                else:
                    break
            
            # Kiểm tra tỷ lệ nguồn cộng đồng trong window_size gần nhất
            is_community = _is_community_item(it)
            recent_window = out[-(window_size - 1):] if window_size > 1 else []
            community_count = sum(1 for x in recent_window if _is_community_item(x))

            if run < max_run and (not is_community or community_count < max_community_per_window):
                out.append(pending.pop(idx))
                break
        else:
            # Nếu không tìm được phần tử thỏa mãn hoàn toàn, lấy phần tử đầu tiên
            out.append(pending.pop(0))
    return out


def write_health_report(
    sources: list[dict],
    state: dict,
    now_dt: datetime | None = None,
    path: Path = HEALTH_PATH,
) -> dict:
    """Ghi báo cáo sức khỏe các nguồn đang bật vào data/health.json theo đặc tả SPEC.md."""
    now_dt = now_dt or datetime.now(timezone.utc)
    report_sources: dict[str, dict] = {}

    for src in sources:
        sid = src["id"]
        st = state.get(sid) if isinstance(state.get(sid), dict) else {}
        failure_count = int(st.get("failure_count", 0) or 0)
        last_success = st.get("last_success") or None
        last_failure = st.get("last_failure") or None
        paused_until = st.get("paused_until") or None
        last_error = st.get("last_error") or None

        is_paused = False
        if paused_until:
            try:
                paused_dt = datetime.fromisoformat(str(paused_until).replace("Z", "+00:00"))
                if paused_dt.tzinfo is None:
                    paused_dt = paused_dt.replace(tzinfo=timezone.utc)
                if paused_dt > now_dt:
                    is_paused = True
                else:
                    paused_until = None
            except ValueError:
                paused_until = None

        if is_paused:
            status = "paused"
        elif failure_count > 0:
            status = "degraded"
        else:
            status = "ok"

        report_sources[sid] = {
            "status": status,
            "failure_count": failure_count,
            "last_success": last_success,
            "last_failure": last_failure,
            "paused_until": paused_until,
            "last_error": last_error,
        }

    report = {
        "updated_at": now_dt.replace(microsecond=0).isoformat(),
        "sources": report_sources,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report

def update_featured_history(items: list[dict]):
    """Cập nhật lịch sử 'Mẹo hay hôm nay' để không lặp lại trong 14 ngày."""
    history_file = DATA_DIR / "history_featured.json"
    history = []
    if history_file.exists():
        try:
            history = json.loads(history_file.read_text(encoding="utf-8"))
        except Exception:
            history = []
    
    # Loại bỏ lịch sử cũ hơn 14 ngày
    now_dt = datetime.now(timezone.utc)
    cutoff = now_dt.timestamp() - (14 * 86400)
    history = [
        h for h in history
        if parse_published_time(h.get("featured_at", "")).timestamp() >= cutoff
    ]
    history_ids = {h["id"] for h in history}

    # Ứng viên: howto == True, <= 72h, không bị hidden, chưa từng featured trong 14 ngày
    # VÀ BẮT BUỘC phải có bản dịch tiếng Việt hợp lệ nếu là nguồn quốc tế (tránh hiển thị tiếng Anh trên /vi/)
    candidates = []
    for it in items:
        if not it.get("howto") or it.get("hidden"):
            continue
        if it["id"] in history_ids:
            continue
        # Ưu tiên bài đã có tiếng Việt hoặc đã dịch tiếng Việt hoàn tất
        has_vi = bool(it.get("original_lang") == "vi" or it.get("translated", {}).get("vi") == "machine")
        if not has_vi:
            continue
        pub_dt = parse_published_time(it.get("published_at", ""))
        age_hours = (now_dt - pub_dt).total_seconds() / 3600.0
        if 0 <= age_hours <= 72:
            candidates.append(it)
    
    if candidates:
        # Sắp xếp ưu tiên nguồn tips và điểm score cao nhất
        candidates.sort(key=lambda x: (x.get("source", {}).get("kind") == "tips", x.get("score", 0)), reverse=True)
        chosen = candidates[0]
        today_str = now_dt.strftime("%Y-%m-%d")
        already_today = any(h.get("date") == today_str for h in history)
        if not already_today:
            history.append({
                "id": chosen["id"],
                "title": chosen.get("title", {}).get("vi") or chosen.get("title", {}).get("en") or "",
                "featured_at": now_dt.isoformat(),
                "date": today_str
            })
            history_file.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

def main():
    print("=== [Tech Tips Hub] Bắt đầu tiến trình thu thập và xử lý thủ thuật ===")
    
    # 1. Đọc cấu hình
    with open("config/sources.json", "r", encoding="utf-8") as f:
        sources = json.load(f) or []
    sources = [source for source in sources if source.get("enabled", False)]
    with open("config/blocklist.yml", "r", encoding="utf-8") as f:
        blocklist = yaml.safe_load(f) or {}
    if not sources:
        raise RuntimeError("Không có nguồn nào được bật trong config/sources.json.")

    # 2. Đọc index hiện tại
    index = {}
    if INDEX_PATH.exists():
        try:
            index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Lỗi đọc index.json: {e}")
            raise RuntimeError("Dừng pipeline vì data/index.json lỗi; không ghi đè kho dữ liệu hiện tại.") from e

    state = {}
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[State Warning] Không đọc được state: {e}; khởi tạo state mới.")
            state = {}

    trans_cache = load_cache()
    fetched_count = 0
    successful_sources = 0
    failed_sources = []
    attempted_sources = 0
    paused_sources = []
    last_host = None
    new_added = 0
    blocked_count = 0
    duplicate_count = 0
    rejected_non_howto = 0

    now_iso = datetime.now(timezone.utc).isoformat()

    # 3. Quét từng nguồn
    for src in sources:
        print(f"-> Đang tải nguồn: {src['name']} ({src['id']}) [kind: {src.get('kind', 'news')}]...")
        src_state = state.setdefault(src["id"], {})
        paused_until = src_state.get("paused_until")
        if paused_until:
            try:
                paused_dt = datetime.fromisoformat(paused_until.replace("Z", "+00:00"))
                if paused_dt.tzinfo is None:
                    paused_dt = paused_dt.replace(tzinfo=timezone.utc)
                if paused_dt > datetime.now(timezone.utc):
                    paused_sources.append(src["id"])
                    print(f"[Fetch Paused] {src['id']} tạm dừng tới {paused_until}")
                    continue
            except ValueError:
                src_state.pop("paused_until", None)

        host = urlsplit(src.get("url", "")).hostname
        if host and host == last_host:
            time.sleep(random.uniform(0.2, 0.8))
        last_host = host
        attempted_sources += 1
        try:
            items = fetch_feed_items(src, max_entries=int(src.get("maxPerRun", 20)), state_entry=src_state)
            successful_sources += 1
            src_state["failure_count"] = 0
            src_state.pop("paused_until", None)
            src_state.pop("last_error", None)
            src_state["last_success"] = datetime.now(timezone.utc).isoformat()
        except SourceFetchError as e:
            failed_sources.append(src["id"])
            src_state["failure_count"] = int(src_state.get("failure_count", 0)) + 1
            src_state["last_error"] = str(e)[:300]
            src_state["last_failure"] = datetime.now(timezone.utc).isoformat()
            if src_state["failure_count"] >= 5:
                src_state["paused_until"] = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
            print(f"[Fetch Warning] {e}")
            continue
        fetched_count += len(items)

        for raw_item in items:
            iid = raw_item["id"]
            title = raw_item["raw_title"]
            summary = raw_item["raw_summary"]
            url = raw_item["url"]

            # Chặn sớm tóm tắt rỗng trước khi nạp vào index (tránh làm hỏng qa.py)
            if not summary or not summary.strip():
                log_rejection(raw_item, src, "empty-summary")
                rejected_non_howto += 1
                continue

            # Kiểm tra bộ lọc chấp nhận (Section 3: filters.accept)
            is_ok, reason = accept(raw_item, src)
            if not is_ok:
                if reason.startswith("blocklist"):
                    blocked_count += 1
                else:
                    rejected_non_howto += 1
                continue

            # Kiểm tra blocklist bổ sung từ blocklist.yml
            if is_blocked(title, summary, url, blocklist):
                blocked_count += 1
                continue

            # Kiểm tra trùng ID đã tồn tại
            if iid in index:
                continue

            # Gộp bài có tiêu đề gần giống trong 7 ngày (bỏ qua bài hidden để không nuốt bài hợp lệ mới).
            is_dup = False
            for existing in index.values():
                if existing.get("hidden"):
                    continue
                existing_title = existing["title"].get(raw_item["original_lang"], "")
                existing_date = parse_published_time(existing.get("published_at", ""))
                new_date = parse_published_time(raw_item.get("published_at", ""))
                within_week = abs((new_date - existing_date).total_seconds()) <= 7 * 86400
                if within_week and is_duplicate_title(title, existing_title, threshold=0.85):
                    also_from = existing.setdefault("alsoFrom", [])
                    if not any(entry.get("url") == url for entry in also_from):
                        also_from.append({"sourceName": raw_item["source"]["name"], "url": url})
                    is_dup = True
                    break
            if is_dup:
                duplicate_count += 1
                continue

            # Xác định bài viết có phải thủ thuật hay không
            is_howto = is_howto_match(title, summary)

            # Phân loại danh mục dựa trên nội dung (tối đa 1-2 danh mục)
            cats = classify(title, summary, fallback=raw_item["default_categories"], max_cats=2)
            tags = extract_tags(title, summary, max_tags=3)

            # Độ khó: chỉ gán cho bài how-to
            difficulty = detect_difficulty(title, summary, howto=is_howto)

            # Tính điểm chất lượng
            community_val = raw_item.get("hn_points", 0) or raw_item.get("reactions", 0)
            score = calculate_score(
                title=title,
                summary=summary,
                source_weight=raw_item["source_weight"],
                published_at=raw_item["published_at"],
                is_howto=is_howto,
                community_signal=community_val
            )

            # Lọc bỏ bài có điểm quá thấp (< 0.35)
            if score < 0.35:
                continue

            # Khởi tạo dữ liệu song ngữ từ cache nếu có
            orig_l = raw_item["original_lang"]
            fallback_titles = {orig_l: title}
            fallback_summaries = {orig_l: summary}
            if str(orig_l).lower().startswith("zh"):
                fallback_titles.update({"vi": title, "en": title})
                fallback_summaries.update({"vi": summary, "en": summary})
            else:
                target_l = "vi" if orig_l == "en" else "en"
                fallback_titles[target_l] = title
                fallback_summaries[target_l] = summary
            if iid in trans_cache:
                c_entry = trans_cache[iid]
                title_dict = {**fallback_titles, **c_entry.get("title", {})}
                summary_dict = {**fallback_summaries, **c_entry.get("summary", {})}
                trans_meta = dict(c_entry.get("translated", {}))
                cached_key_points = normalize_key_points_map(c_entry.get("key_points"))
            else:
                title_dict = fallback_titles
                summary_dict = fallback_summaries
                trans_meta = {}
                cached_key_points = {}

            index[iid] = {
                "id": iid,
                "slug": generate_seo_slug(title, iid),
                "url": url,
                "source": {
                    "id": raw_item["source"]["id"],
                    "name": raw_item["source"]["name"],
                    "site_url": raw_item["source"].get("site_url", ""),
                    "kind": src.get("kind", "tips" if src.get("tipOnly") else "news"),
                    "content_type": src.get("contentType", "article")
                },
                "author": raw_item["author"],
                "published_at": raw_item["published_at"],
                "fetched_at": now_iso,
                "original_lang": raw_item["original_lang"],
                "title": title_dict,
                "summary": summary_dict,
                "categories": cats,
                "tags": tags,
                "difficulty": difficulty,
                "score": score,
                "howto": is_howto,
                "reading_time_min": estimate_reading_time(summary),
                "translated": trans_meta
            }
            if cached_key_points:
                index[iid]["key_points"] = cached_key_points
            if "hn_points" in raw_item:
                index[iid]["hn_points"] = raw_item["hn_points"]
            if "hn_comments_url" in raw_item:
                index[iid]["hn_comments_url"] = raw_item["hn_comments_url"]

            new_added += 1

        time.sleep(0.3)

    # 3b. Bài cộng đồng chỉ xuất hiện ở đây sau khi quản trị viên duyệt qua Telegram.
    community_items = []
    if COMMUNITY_PATH.exists():
        try:
            community_items = json.loads(COMMUNITY_PATH.read_text(encoding="utf-8"))
            if not isinstance(community_items, list):
                raise ValueError("data/community.json must contain an array")
        except Exception as e:
            raise RuntimeError(f"Không đọc được {COMMUNITY_PATH}; dừng để bảo toàn dữ liệu.") from e

        for entry in community_items:
            iid = str(entry.get("id", "")).strip()
            url = canonical_url(str(entry.get("url", "")))
            lang = entry.get("originalLang", "vi")
            lang = lang if lang in ("vi", "en") else "vi"
            raw_title_map = entry.get("title") if isinstance(entry.get("title"), dict) else {}
            raw_summary_map = entry.get("summary") if isinstance(entry.get("summary"), dict) else {}
            title = clean_title(str(raw_title_map.get(lang) or ""), limit=160)
            summary = clean_text(str(raw_summary_map.get(lang) or ""), limit=300)
            if not iid or not url or not title or not summary or iid in index:
                continue
            default_author = "Community" if lang == "en" else "Cộng đồng đóng góp"
            author = clean_text(str(entry.get("submittedBy") or ""), limit=80) or default_author
            source_name = clean_text(str(entry.get("sourceName") or default_author), limit=100) or default_author
            published_at = normalize_published_iso(
                entry.get("publishedAt") or entry.get("approvedAt") or now_iso
            ) or now_iso

            # Bài cộng đồng đã qua quản trị viên duyệt: chỉ chặn các tên miền bị cấm cứng (không chặn từ khóa biên tập/khuyến mãi)
            domain_blocklist = {"domains": blocklist.get("domains", [])}
            if is_blocked("", "", url, domain_blocklist):
                print(f"[Community] Bỏ qua {iid}: blocked-domain")
                continue

            duplicate = False
            for existing in index.values():
                if existing.get("hidden"):
                    continue
                existing_url = existing.get("url", "")
                existing_title = existing.get("title", {}).get(lang, "")
                if existing_url == url or is_duplicate_title(title, existing_title, threshold=0.9):
                    existing.setdefault("alsoFrom", [])
                    if not any(source.get("url") == url for source in existing["alsoFrom"]):
                        existing["alsoFrom"].append({"sourceName": source_name, "url": url})
                    duplicate = True
                    break
            if duplicate:
                duplicate_count += 1
                continue

            target_lang = "en" if lang == "vi" else "vi"
            provided_tags = entry.get("tags", [])
            raw_tags = [str(tag).strip().lower()[:32] for tag in provided_tags[:10]] if isinstance(provided_tags, list) else []
            mapped_tags = ["browser" if tag == "web" else tag for tag in raw_tags if tag != "khac"]
            valid_cat_ids = {
                "android", "ios", "windows", "macos", "linux", "browser", "office", "security", "ai", "dev", "hardware"
            }
            categories = []
            for tag in mapped_tags:
                if tag in valid_cat_ids and tag not in categories:
                    categories.append(tag)
                if len(categories) >= 2:
                    break
            if not categories:
                categories = classify(title, summary, fallback=[], max_cats=2)
            tags = [tag for tag in mapped_tags if tag not in categories][:4]
            index[iid] = {
                "id": iid, "slug": generate_seo_slug(title, iid), "url": url,
                "source": {"id": "community", "name": source_name, "site_url": url,
                           "kind": "tips", "content_type": "community"},
                "author": author, "published_at": published_at,
                "fetched_at": now_iso, "original_lang": lang,
                "title": {lang: title, target_lang: title},
                "summary": {lang: summary, target_lang: summary},
                "categories": categories, "tags": tags, "difficulty": None,
                "score": 0.75, "howto": True,
                "reading_time_min": estimate_reading_time(summary), "translated": {},
                "source_type": entry.get("sourceType", "community-web"),
                "approved_at": entry.get("approvedAt", "")
            }
            new_added += 1

    if failed_sources:
        print(f"[Fetch Warning] {len(failed_sources)}/{len(sources)} nguồn lỗi: {', '.join(failed_sources)}")
    if paused_sources:
        print(f"[Fetch Paused] {len(paused_sources)} nguồn đang tạm dừng: {', '.join(paused_sources)}")
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    write_health_report(sources, state)
    if attempted_sources == 0 and not community_items:
        print("Không có nguồn đến hạn chạy; giữ nguyên kho hiện tại.")
        return
    if successful_sources == 0 and not community_items:
        raise RuntimeError("Tất cả nguồn dữ liệu đều lỗi; dừng để tránh ghi đè bằng lượt quét thất bại.")

    # 4. Dịch thuật theo lô CHỈ cho các bài đang hiển thị (không tiêu tốn hạn mức vào bài hidden)
    print("\n-> Đang kiểm tra và dịch thuật theo lô...")
    all_items = list(index.values())
    visible_items = [it for it in all_items if not it.get("hidden")]
    hidden_items = [it for it in all_items if it.get("hidden")]
    batch_translate_pending(visible_items, trans_cache, batch_size=5)

    # Các trường này chỉ cần trong lúc xử lý; tiêu đề và tóm tắt gốc đã được lưu trong title/summary.
    # Đồng thời cập nhật lại SEO slug cho bài mới hoặc bài tiếng Trung sau khi đã có bản dịch Latin.
    for item in all_items:
        item.pop("raw_title", None)
        item.pop("raw_summary", None)
        if item.get("hidden"):
            continue
        sync_item_key_points(item, trans_cache.get(item.get("id")))
        orig_lang = str(item.get("original_lang", "")).lower()
        curr_slug = item.get("slug") or ""
        is_zh = orig_lang.startswith("zh")
        has_latin_trans = item.get("translated", {}).get("vi") == "machine" or item.get("translated", {}).get("en") == "machine"
        if not curr_slug or curr_slug.startswith("tip-") or (is_zh and has_latin_trans):
            best_title = (
                (item.get("title", {}).get("vi") if item.get("translated", {}).get("vi") == "machine" else None)
                or (item.get("title", {}).get("en") if item.get("translated", {}).get("en") == "machine" else None)
                or item.get("title", {}).get("vi")
                or item.get("title", {}).get("en")
                or ""
            )
            item["slug"] = generate_seo_slug(best_title, item["id"])

    # Chỉ tính bài hiển thị vào ngưỡng 2.000 bài hoạt động; các bài cũ hơn được chuyển vào archive theo tháng.
    if len(visible_items) > 2000:
        visible_items.sort(key=lambda it: parse_published_time(it.get("published_at", "")), reverse=True)
        removed = visible_items[2000:]
        visible_items = visible_items[:2000]
        archive_dir = DATA_DIR / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_groups = {}
        for item in removed:
            month = parse_published_time(item.get("published_at", "")).strftime("%Y-%m")
            archive_groups.setdefault(month, {})[item["id"]] = item
        for month, group in archive_groups.items():
            archive_path = archive_dir / f"{month}.json"
            existing_archive = json.loads(archive_path.read_text(encoding="utf-8")) if archive_path.exists() else {}
            existing_archive.update(group)
            archive_path.write_text(json.dumps(existing_archive, ensure_ascii=False, indent=2), encoding="utf-8")

    # Giữ tối đa 2.000 mục hidden mới nhất làm tombstone chống quét trùng mà không ảnh hưởng giới hạn bài hiển thị.
    if len(hidden_items) > 2000:
        hidden_items.sort(
            key=lambda it: parse_published_time(it.get("fetched_at") or it.get("published_at", "")),
            reverse=True,
        )
        hidden_items = hidden_items[:2000]

    # 5. Áp dụng giới hạn xen kẽ nguồn (diversify) trên các bài đang hiển thị
    diversified_items = diversify(visible_items, max_run=2)
    reordered_index = {it["id"]: it for it in diversified_items + hidden_items}

    # 6. Ghi dữ liệu, cập nhật featured history, health report và cache
    save_cache(trans_cache)
    INDEX_PATH.write_text(json.dumps(reordered_index, ensure_ascii=False, indent=2), encoding="utf-8")
    update_featured_history(diversified_items)
    write_health_report(sources, state)

    print("\n=== [Kết quả tổng hợp] ===")
    print(f"Tổng số mục quét: {fetched_count}")
    print(f"Loại bỏ theo blocklist: {blocked_count}")
    print(f"Loại bỏ tin tức không phải thủ thuật: {rejected_non_howto}")
    print(f"Loại bỏ trùng lặp: {duplicate_count}")
    print(f"Bài viết mới thêm vào: {new_added}")
    print(f"Tổng số thủ thuật trong kho: {len(reordered_index)}")

if __name__ == "__main__":
    main()
