# scripts/run_pipeline.py
import sys
import json
import yaml
import time
from pathlib import Path
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fetch import fetch_feed_items
from dedupe import is_duplicate_title, is_blocked
from filters import accept, is_howto_match
from classify import classify, extract_tags
from score import calculate_score, detect_difficulty
from translate import load_cache, save_cache, process_item_bilingual

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
INDEX_PATH = DATA_DIR / "index.json"

def estimate_reading_time(text: str) -> int:
    """Ước lượng thời gian đọc (khoảng 150-200 từ/phút)."""
    words = len(text.split())
    return max(1, round(words / 35))

def diversify(items: list[dict], max_run: int = 2) -> list[dict]:
    """
    Xen kẽ nguồn để danh sách đa dạng và hấp dẫn:
    Không để quá max_run bài liên tiếp từ cùng một nguồn.
    """
    pending = sorted(items, key=lambda x: -x["score"])
    out = []
    while pending:
        for idx, it in enumerate(pending):
            run = 0
            for prev in reversed(out):
                if prev["source"]["id"] == it["source"]["id"]:
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

def main():
    print("=== [Tech Tips Hub] Bắt đầu tiến trình thu thập và xử lý thủ thuật ===")
    
    # 1. Đọc cấu hình
    with open("config/sources.yml", "r", encoding="utf-8") as f:
        sources = yaml.safe_load(f) or []
    with open("config/blocklist.yml", "r", encoding="utf-8") as f:
        blocklist = yaml.safe_load(f) or {}

    sources_map = {s["id"]: s for s in sources}

    # 2. Đọc index hiện tại
    index = {}
    if INDEX_PATH.exists():
        try:
            index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Lỗi đọc index.json: {e}")
            index = {}

    trans_cache = load_cache()
    fetched_count = 0
    new_added = 0
    blocked_count = 0
    duplicate_count = 0
    rejected_non_howto = 0

    now_iso = datetime.now(timezone.utc).isoformat()

    # 3. Quét từng nguồn
    for src in sources:
        print(f"-> Đang tải nguồn: {src['name']} ({src['id']}) [kind: {src.get('kind', 'news')}]...")
        items = fetch_feed_items(src, max_entries=20)
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

            # Kiểm tra trùng lặp tiêu đề với các bài đã có (fuzzy deduplication)
            is_dup = False
            for existing in index.values():
                existing_title = existing["title"].get(raw_item["original_lang"], "")
                if is_duplicate_title(title, existing_title):
                    is_dup = True
                    break
            if is_dup:
                duplicate_count += 1
                continue

            # Xác định bài viết có phải thủ thuật hay không
            is_howto = (src.get("kind") == "tips") or is_howto_match(title, summary)

            # Phân loại danh mục dựa trên nội dung (tối đa 1-2 danh mục)
            cats = classify(title, summary, fallback=raw_item["default_categories"], max_cats=2)
            tags = extract_tags(title, summary, max_tags=3)

            # Độ khó: chỉ gán cho bài how-to
            difficulty = detect_difficulty(title, summary, howto=is_howto)

            # Tính điểm chất lượng
            score = calculate_score(
                title=title,
                summary=summary,
                source_weight=raw_item["source_weight"],
                published_at=raw_item["published_at"],
                is_howto=is_howto
            )

            # Lọc bỏ bài có điểm quá thấp (< 0.35)
            if score < 0.35:
                continue

            # Dịch song ngữ & tóm tắt
            title_dict, summary_dict, trans_meta = process_item_bilingual(
                item_id=iid,
                orig_title=title,
                orig_summary=summary,
                orig_lang=raw_item["original_lang"],
                cache=trans_cache
            )

            index[iid] = {
                "id": iid,
                "url": url,
                "source": {
                    "id": raw_item["source"]["id"],
                    "name": raw_item["source"]["name"],
                    "site_url": raw_item["source"].get("site_url", ""),
                    "kind": src.get("kind", "news")
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

    # 4. Áp dụng giới hạn xen kẽ nguồn (diversify)
    all_items = list(index.values())
    diversified_items = diversify(all_items, max_run=2)
    reordered_index = {it["id"]: it for it in diversified_items}

    # 5. Ghi dữ liệu và cập nhật cache
    save_cache(trans_cache)
    INDEX_PATH.write_text(json.dumps(reordered_index, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== [Kết quả tổng hợp] ===")
    print(f"Tổng số mục quét: {fetched_count}")
    print(f"Loại bỏ theo blocklist: {blocked_count}")
    print(f"Loại bỏ tin tức không phải thủ thuật: {rejected_non_howto}")
    print(f"Loại bỏ trùng lặp: {duplicate_count}")
    print(f"Bài viết mới thêm vào: {new_added}")
    print(f"Tổng số thủ thuật trong kho: {len(reordered_index)}")

if __name__ == "__main__":
    main()
