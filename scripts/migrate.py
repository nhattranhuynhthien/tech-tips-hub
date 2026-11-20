# scripts/migrate.py
import sys
import json
import shutil
import yaml
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fetch import source_weight
from textclean import clean_text, strip_title_prefix
from filters import accept, is_howto_match
from dedupe import is_blocked
from classify import classify, extract_tags
from score import calculate_score, detect_difficulty
from slug import generate_seo_slug
from translate import is_mixed, looks_vietnamese, looks_english

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

    migrated_count = 0
    hidden_count = 0

    for iid, item in data.items():
        orig_lang = item.get("original_lang", "en")
        src_id = item.get("source", {}).get("id", "")
        source_cfg = sources_map.get(src_id, item.get("source", {}))

        # Lấy tiêu đề và tóm tắt gốc
        orig_title = item.get("raw_title") or item.get("title", {}).get(orig_lang) or item.get("title", {}).get("en") or item.get("title", {}).get("vi", "")
        orig_summary = item.get("raw_summary") or item.get("summary", {}).get(orig_lang) or item.get("summary", {}).get("en") or item.get("summary", {}).get("vi", "")

        # 2. Làm sạch văn bản triệt để
        clean_t = clean_text(orig_title, limit=160)
        clean_s = clean_text(orig_summary, limit=300)
        clean_s = strip_title_prefix(clean_s, clean_t)

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
        is_ok, _reason = accept(filter_item, source_cfg, enable_logging=False)
        if not is_ok or is_blocked(clean_t, clean_s, item.get("url", ""), blocklist):
            item["hidden"] = True
            hidden_count += 1
            continue

        # 5. Xác định how-to & Phân loại lại danh mục (dùng cả bản dịch nếu bài gốc là tiếng Trung)
        vi_or_en_t = item.get("title", {}).get("vi") or item.get("title", {}).get("en") or ""
        vi_or_en_s = item.get("summary", {}).get("vi") or item.get("summary", {}).get("en") or ""
        classify_t = f"{clean_t} {vi_or_en_t}".strip() if str(orig_lang).lower().startswith("zh") else clean_t
        classify_s = f"{clean_s} {vi_or_en_s}".strip() if str(orig_lang).lower().startswith("zh") else clean_s

        is_howto = is_howto_match(classify_t, classify_s)
        cats = classify(classify_t, classify_s, fallback=source_cfg.get("categories", []), max_cats=2)
        tags = extract_tags(classify_t, classify_s, max_tags=3)

        # 6. Tính lại độ khó và điểm chất lượng
        difficulty = detect_difficulty(classify_t, classify_s, howto=is_howto)
        community_val = item.get("hn_points", 0) or item.get("reactions", 0)
        weight = source_weight(source_cfg) if "trust" in source_cfg or "weight" in source_cfg else item.get("source_weight", 1.0)
        score = calculate_score(
            title=classify_t,
            summary=classify_s,
            source_weight=weight,
            published_at=item.get("published_at", ""),
            is_howto=is_howto,
            community_signal=community_val
        )

        if score < 0.35:
            item["hidden"] = True
            hidden_count += 1
            continue

        # 7. Xử lý bản dịch an toàn cho cả EN, VI và ZH-CN
        curr_trans = item.get("translated", {}) or {}
        item.setdefault("title", {})[orig_lang] = clean_t
        item.setdefault("summary", {})[orig_lang] = clean_s

        target_langs = ("vi", "en") if str(orig_lang).lower().startswith("zh") else (("vi",) if orig_lang == "en" else ("en",))
        for t_lang in target_langs:
            curr_t = item.get("title", {}).get(t_lang, "")
            curr_s = item.get("summary", {}).get(t_lang, "")
            bad_mix = is_mixed(curr_t) or is_mixed(curr_s) or "[Bản dịch]" in curr_t or "[Bản dịch]" in curr_s
            bad_machine = (
                curr_trans.get(t_lang) == "machine"
                and ((t_lang == "vi" and not looks_vietnamese(curr_t)) or (t_lang == "en" and not looks_english(curr_t)))
            )
            if bad_mix or bad_machine or not curr_t or not curr_s:
                item["title"][t_lang] = clean_t
                item["summary"][t_lang] = clean_s
                curr_trans.pop(t_lang, None)

        item.pop("raw_title", None)
        item.pop("raw_summary", None)
        item["categories"] = cats
        item["tags"] = tags
        item["difficulty"] = difficulty
        item["score"] = score
        item["howto"] = is_howto
        item["hidden"] = False
        slug_title = (
            (item["title"].get("vi") if curr_trans.get("vi") == "machine" or orig_lang == "vi" else None)
            or (item["title"].get("en") if curr_trans.get("en") == "machine" or orig_lang == "en" else None)
            or item["title"].get("vi")
            or item["title"].get("en")
            or clean_t
        )
        item["slug"] = generate_seo_slug(slug_title, iid)
        item["translated"] = curr_trans

        # Cập nhật thông tin nguồn chuẩn từ config/sources.json
        item["source"]["kind"] = source_cfg.get("kind", item["source"].get("kind", "news"))
        item["source"]["name"] = source_cfg.get("name", item["source"].get("name"))
        if source_cfg.get("site_url"):
            item["source"]["site_url"] = source_cfg["site_url"]
        if source_cfg.get("contentType") or item["source"].get("content_type"):
            item["source"]["content_type"] = source_cfg.get("contentType", item["source"].get("content_type", "article"))

        migrated_count += 1

    # 8. Lưu index mới
    INDEX_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n✅ Migration hoàn tất!")
    print(f"- Số bài viết hoạt động hợp lệ: {migrated_count}")
    print(f"- Số bài viết bị ẩn (hidden: true): {hidden_count}")


if __name__ == "__main__":
    main()
