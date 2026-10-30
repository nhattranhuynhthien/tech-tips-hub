# scripts/migrate.py
import sys
import json
import shutil
import yaml
from pathlib import Path
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from textclean import clean_text, strip_title_prefix
from filters import accept, is_howto_match
from dedupe import is_blocked
from classify import classify, extract_tags
from score import calculate_score, detect_difficulty
from slug import generate_seo_slug
from translate import is_mixed, looks_vietnamese, looks_english, load_cache, save_cache

DATA_DIR = Path("data")
INDEX_PATH = DATA_DIR / "index.json"
BACKUP_PATH = DATA_DIR / "index.backup.json"

def main():
    print("=== [Tech Tips Hub] Bắt đầu tiến trình Migration Dữ Liệu Cũ ===")
    
    if not INDEX_PATH.exists():
        print("[Error] Không tìm thấy data/index.json để migrate!")
        sys.exit(1)

    # 1. Sao lưu an toàn trước khi thực hiện
    print(f"-> Tạo bản sao lưu tại {BACKUP_PATH}...")
    shutil.copy2(INDEX_PATH, BACKUP_PATH)

    with open("config/sources.json", "r", encoding="utf-8") as f:
        sources_list = json.load(f) or []
    sources_map = {s["id"]: s for s in sources_list}

    with open("config/blocklist.yml", "r", encoding="utf-8") as f:
        blocklist = yaml.safe_load(f) or {}

    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    print(f"-> Đang xử lý {len(data)} bài viết trong kho...")

    trans_cache = load_cache()
    migrated_count = 0
    hidden_count = 0

    for iid, item in data.items():
        # Giữ nguyên ID gốc để bảo toàn liên kết và bookmark của người dùng
        orig_lang = item.get("original_lang", "en")
        src_id = item.get("source", {}).get("id", "")
        source_cfg = sources_map.get(src_id, item.get("source", {}))

        # Lấy tiêu đề và tóm tắt gốc
        orig_title = item.get("raw_title") or item["title"].get(orig_lang, "")
        orig_summary = item.get("raw_summary") or item["summary"].get(orig_lang, "")

        # 2. Làm sạch văn bản triệt để
        clean_t = clean_text(orig_title, limit=160)
        clean_s = clean_text(orig_summary, limit=300)
        clean_s = strip_title_prefix(clean_s, clean_t)

        item["raw_title"] = clean_t
        item["raw_summary"] = clean_s

        # 3. Kiểm tra tính hợp lệ: nếu tóm tắt rỗng -> ẩn bài
        if not clean_s or len(clean_s.strip()) == 0:
            item["hidden"] = True
            hidden_count += 1
            continue

        # 4. Kiểm tra bộ lọc accept() và blocklist
        filter_item = {
            "title": clean_t,
            "raw_title": clean_t,
            "summary": clean_s,
            "raw_summary": clean_s,
            "url": item.get("url", "")
        }
        is_ok, reason = accept(filter_item, source_cfg, enable_logging=False)
        if not is_ok or is_blocked(clean_t, clean_s, item.get("url", ""), blocklist):
            item["hidden"] = True
            hidden_count += 1
            continue

        # 5. Xác định how-to & Phân loại lại danh mục
        is_howto = is_howto_match(clean_t, clean_s)
        cats = classify(clean_t, clean_s, fallback=source_cfg.get("categories", []), max_cats=2)
        tags = extract_tags(clean_t, clean_s, max_tags=3)

        # 6. Tính lại độ khó và điểm chất lượng
        difficulty = detect_difficulty(clean_t, clean_s, howto=is_howto)
        community_val = item.get("hn_points", 0) or item.get("reactions", 0)
        score = calculate_score(
            title=clean_t,
            summary=clean_s,
            source_weight=source_cfg.get("weight", item.get("source_weight", 1.0)),
            published_at=item.get("published_at", ""),
            is_howto=is_howto,
            community_signal=community_val
        )

        if score < 0.35:
            item["hidden"] = True
            hidden_count += 1
            continue

        # 7. Xử lý bản dịch: Xóa toàn bộ bản dịch cũ bị trộn ngữ pháp hoặc giả mạo nhãn
        target_lang = "vi" if orig_lang == "en" else "en"
        curr_t_vi = item.get("title", {}).get("vi", "")
        curr_s_vi = item.get("summary", {}).get("vi", "")
        curr_trans = item.get("translated", {})

        # Nếu bản dịch bị trộn hoặc dính [Bản dịch] -> Revert về bản gốc
        if is_mixed(curr_t_vi) or is_mixed(curr_s_vi) or "[Bản dịch]" in curr_t_vi or "[Bản dịch]" in curr_s_vi:
            item["title"][target_lang] = clean_t
            item["summary"][target_lang] = clean_s
            curr_trans.pop(target_lang, None)
        elif curr_trans.get(target_lang) == "machine":
            # Nếu đã gắn nhãn dịch máy, kiểm tra xem có đúng tiếng Việt không
            if target_lang == "vi" and not looks_vietnamese(curr_t_vi):
                item["title"]["vi"] = clean_t
                item["summary"]["vi"] = clean_s
                curr_trans.pop("vi", None)

        item["title"][orig_lang] = clean_t
        item["summary"][orig_lang] = clean_s
        item["categories"] = cats
        item["tags"] = tags
        item["difficulty"] = difficulty
        item["score"] = score
        item["howto"] = is_howto
        item["hidden"] = False
        item["slug"] = generate_seo_slug(item["title"].get("vi") or item["title"].get("en") or clean_t, iid)
        item["translated"] = curr_trans

        # Cập nhật thông tin nguồn
        item["source"]["kind"] = source_cfg.get("kind", "news")
        item["source"]["name"] = source_cfg.get("name", item["source"].get("name"))

        migrated_count += 1

    # 8. Lưu index mới
    INDEX_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ Migration hoàn tất!")
    print(f"- Số bài viết hoạt động hợp lệ: {migrated_count}")
    print(f"- Số bài viết bị ẩn (hidden: true): {hidden_count}")

if __name__ == "__main__":
    main()
