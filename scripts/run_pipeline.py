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
from score import calculate_score, detect_difficulty, extract_categories_and_tags
from translate import load_cache, save_cache, process_item_bilingual

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
INDEX_PATH = DATA_DIR / "index.json"

def estimate_reading_time(text: str) -> int:
    """Ước lượng thời gian đọc dựa trên số từ (200 từ/phút)."""
    words = len(text.split())
    return max(1, round(words / 40)) # Tóm tắt ngắn nên tính thời gian đọc bài gốc ước lượng

def main():
    print("=== [Tech Tips Hub] Bắt đầu tiến trình thu thập và xử lý thủ thuật ===")
    
    # 1. Đọc cấu hình
    with open("config/sources.yml", "r", encoding="utf-8") as f:
        sources = yaml.safe_load(f) or []
    with open("config/categories.yml", "r", encoding="utf-8") as f:
        categories_data = yaml.safe_load(f) or {}
        categories_list = categories_data.get("categories", [])
    with open("config/blocklist.yml", "r", encoding="utf-8") as f:
        blocklist = yaml.safe_load(f) or {}

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

    now_iso = datetime.now(timezone.utc).isoformat()

    # 3. Quét từng nguồn
    for src in sources:
        print(f"-> Đang tải nguồn: {src['name']} ({src['id']})...")
        items = fetch_feed_items(src, max_entries=20)
        fetched_count += len(items)

        for raw_item in items:
            iid = raw_item["id"]
            title = raw_item["raw_title"]
            summary = raw_item["raw_summary"]
            url = raw_item["url"]

            # Kiểm tra blocklist (quảng cáo, deal, giveaway)
            if is_blocked(title, summary, url, blocklist):
                blocked_count += 1
                continue

            # Kiểm tra trùng ID đã tồn tại
            if iid in index:
                continue

            # Kiểm tra trùng lặp tiêu đề với các bài đã có (fuzzy deduplication)
            is_dup = False
            for existing in index.values():
                if is_duplicate_title(title, existing["title"].get(raw_item["original_lang"], "")):
                    is_dup = True
                    break
            if is_dup:
                duplicate_count += 1
                continue

            # Tính điểm chất lượng
            score = calculate_score(
                title=title,
                summary=summary,
                source_weight=raw_item["source_weight"],
                published_at=raw_item["published_at"]
            )

            # Lọc bỏ bài có điểm quá thấp (< 0.35)
            if score < 0.35:
                continue

            # Phân loại danh mục & tags
            cats, tags = extract_categories_and_tags(
                title=title,
                summary=summary,
                configured_categories=categories_list,
                default_cats=raw_item["default_categories"]
            )

            difficulty = detect_difficulty(title, summary)

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
                "source": raw_item["source"],
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
                "reading_time_min": estimate_reading_time(summary),
                "translated": trans_meta
            }
            new_added += 1

        time.sleep(0.5) # Thân thiện với mạng

    # 4. Ghi dữ liệu và cập nhật cache
    save_cache(trans_cache)
    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== [Kết quả tổng hợp] ===")
    print(f"Tổng số mục quét: {fetched_count}")
    print(f"Loại bỏ theo blocklist: {blocked_count}")
    print(f"Loại bỏ trùng lặp: {duplicate_count}")
    print(f"Bài viết mới thêm vào: {new_added}")
    print(f"Tổng số thủ thuật trong kho: {len(index)}")

if __name__ == "__main__":
    main()
