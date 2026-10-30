# scripts/run_pipeline.py
import sys
import json
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
from dedupe import is_duplicate_title, is_blocked
from filters import accept, is_howto_match
from classify import classify, extract_tags
from score import calculate_score, detect_difficulty, parse_published_time
from slug import generate_seo_slug
from translate import load_cache, save_cache, process_item_bilingual, batch_translate_pending

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
INDEX_PATH = DATA_DIR / "index.json"
STATE_PATH = DATA_DIR / "state.json"
COMMUNITY_PATH = DATA_DIR / "community.json"

def estimate_reading_time(text: str) -> int:
    """Ước lượng thời gian đọc (khoảng 150-200 từ/phút)."""
    words = len(text.split())
    return max(1, round(words / 175))

def diversify(items: list[dict], max_run: int = 2) -> list[dict]:
    """
    Xen kẽ nguồn để danh sách đa dạng và hấp dẫn:
    Không để quá max_run bài liên tiếp từ cùng một nguồn.
    """
    pending = sorted(items, key=lambda x: -x.get("score", 0))
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
            if run < max_run:
                out.append(pending.pop(idx))
                break
        else:
            # Nếu không còn lựa chọn nào khác nguồn, đành lấy phần tử đầu
            out.append(pending.pop(0))
    return out

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
    candidates = []
    for it in items:
        if not it.get("howto") or it.get("hidden"):
            continue
        if it["id"] in history_ids:
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
                if datetime.fromisoformat(paused_until.replace("Z", "+00:00")) > datetime.now(timezone.utc):
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

            # Gộp bài có tiêu đề gần giống trong 7 ngày, giữ nguồn bổ sung làm alsoFrom.
            is_dup = False
            for existing in index.values():
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
            target_l = "vi" if orig_l == "en" else "en"
            if iid in trans_cache:
                c_entry = trans_cache[iid]
                title_dict = c_entry.get("title", {orig_l: title, target_l: title})
                summary_dict = c_entry.get("summary", {orig_l: summary, target_l: summary})
                trans_meta = c_entry.get("translated", {})
            else:
                title_dict = {orig_l: title, target_l: title}
                summary_dict = {orig_l: summary, target_l: summary}
                trans_meta = {}

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
            iid = str(entry.get("id", ""))
            url = entry.get("url", "")
            title = entry.get("title", {}).get(entry.get("originalLang", "vi"))
            summary = entry.get("summary", {}).get(entry.get("originalLang", "vi"))
            if not iid or not url or not title or iid in index:
                continue
            lang = entry.get("originalLang", "vi")
            lang = lang if lang in ("vi", "en") else "vi"
            summary = str(summary or title)[:300]
            source_name = str(entry.get("sourceName") or "Cộng đồng đóng góp")[:100]
            raw_item = {
                "id": iid, "url": url, "raw_title": str(title)[:160],
                "raw_summary": summary, "original_lang": lang,
                "published_at": entry.get("publishedAt") or entry.get("approvedAt") or now_iso,
                "source_weight": 1.0, "source_kind": "tips", "content_type": "community",
                "author": entry.get("submittedBy") or "Cộng đồng đóng góp",
                "default_categories": [], "source": {
                    "id": "community", "name": source_name, "site_url": url,
                    "kind": "tips", "content_type": "community"
                }
            }
            is_ok, reason = accept(raw_item, {"id": "community", "kind": "tips"})
            if not is_ok or is_blocked(title, summary, url, blocklist):
                print(f"[Community] Bỏ qua {iid}: {reason if not is_ok else 'blocklist'}")
                continue
            duplicate = False
            for existing in index.values():
                existing_url = existing.get("url", "")
                existing_title = existing.get("title", {}).get(lang, "")
                if existing_url == url or is_duplicate_title(str(title), existing_title, threshold=0.9):
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
            tags = [str(tag)[:32] for tag in provided_tags[:10]] if isinstance(provided_tags, list) else []
            categories = [tag for tag in tags if tag in {
                "android", "ios", "windows", "macos", "linux", "browser", "office", "security", "ai", "dev", "hardware"
            }][:2]
            if not categories:
                categories = ["browser"]
            index[iid] = {
                "id": iid, "slug": generate_seo_slug(str(title), iid), "url": url,
                "source": {"id": "community", "name": source_name, "site_url": url,
                           "kind": "tips", "content_type": "community"},
                "author": "Cộng đồng đóng góp", "published_at": raw_item["published_at"],
                "fetched_at": now_iso, "original_lang": lang,
                "title": {lang: str(title)[:160], target_lang: str(title)[:160]},
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
    if attempted_sources == 0 and not community_items:
        print("Không có nguồn đến hạn chạy; giữ nguyên kho hiện tại.")
        return
    if successful_sources == 0 and not community_items:
        raise RuntimeError("Tất cả nguồn dữ liệu đều lỗi; dừng để tránh ghi đè bằng lượt quét thất bại.")

    # 4. Dịch thuật theo lô cho các bài chưa có bản dịch (ưu tiên how-to và điểm cao)
    print("\n-> Đang kiểm tra và dịch thuật theo lô...")
    all_items = list(index.values())
    batch_translate_pending(all_items, trans_cache, batch_size=5)

    # Các trường này chỉ cần trong lúc xử lý; tiêu đề và tóm tắt gốc đã được lưu trong title/summary.
    for item in all_items:
        item.pop("raw_title", None)
        item.pop("raw_summary", None)

    # Giữ kho hoạt động ở mức 2.000 bài; các bài cũ được chuyển vào archive theo tháng.
    if len(all_items) > 2000:
        all_items.sort(key=lambda it: parse_published_time(it.get("published_at", "")), reverse=True)
        removed = all_items[2000:]
        all_items = all_items[:2000]
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

    # 5. Áp dụng giới hạn xen kẽ nguồn (diversify)
    diversified_items = diversify(all_items, max_run=2)
    reordered_index = {it["id"]: it for it in diversified_items}

    # 6. Ghi dữ liệu, cập nhật featured history và cache
    save_cache(trans_cache)
    INDEX_PATH.write_text(json.dumps(reordered_index, ensure_ascii=False, indent=2), encoding="utf-8")
    update_featured_history(diversified_items)

    print("\n=== [Kết quả tổng hợp] ===")
    print(f"Tổng số mục quét: {fetched_count}")
    print(f"Loại bỏ theo blocklist: {blocked_count}")
    print(f"Loại bỏ tin tức không phải thủ thuật: {rejected_non_howto}")
    print(f"Loại bỏ trùng lặp: {duplicate_count}")
    print(f"Bài viết mới thêm vào: {new_added}")
    print(f"Tổng số thủ thuật trong kho: {len(reordered_index)}")

if __name__ == "__main__":
    main()
