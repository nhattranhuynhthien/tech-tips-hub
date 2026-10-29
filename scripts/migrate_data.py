# scripts/migrate_data.py
import sys
import json
import yaml
import shutil
import re
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from textclean import clean_text, strip_title_prefix, unescape_all
from filters import accept, is_howto_match, BLOCK
from classify import classify, extract_tags
from score import calculate_score, detect_difficulty
from translate import is_mixed, looks_vietnamese
from run_pipeline import diversify, estimate_reading_time

DATA_PATH = Path("data/index.json")
BACKUP_PATH = Path("data/index.backup.json")
CACHE_PATH = Path("data/cache/translations.json")

def clean_boilerplate_str(text: str) -> str:
    """Loại bỏ tiền tố giả [Bản dịch], [Summary], mã HTML entity và khoảng trắng dư thừa."""
    if not text:
        return ""
    t = unescape_all(text)
    t = re.sub(r"^\s*\[Bản dịch\]\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^\s*\[Summary\]\s*", "", t, flags=re.IGNORECASE)
    t = clean_text(t, limit=300)
    return t

def main():
    print("=== BẮT ĐẦU MIGRATION LÀM SẠCH KHO DỮ LIỆU TECH TIPS HUB ===")
    if not DATA_PATH.exists():
        print("Không tìm thấy data/index.json!")
        return

    # 1. Sao lưu dữ liệu cũ
    shutil.copy2(DATA_PATH, BACKUP_PATH)
    print(f"-> Đã sao lưu dữ liệu gốc vào: {BACKUP_PATH}")

    # Đọc cấu hình nguồn
    with open("config/sources.yml", "r", encoding="utf-8") as f:
        sources_list = yaml.safe_load(f) or []
    sources_map = {s["id"]: s for s in sources_list}

    raw_data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    original_count = len(raw_data)
    print(f"-> Tổng số bài trong kho trước khi lọc: {original_count}")

    cleaned_items = []
    dropped_blocklist = 0
    dropped_non_howto = 0
    cleaned_mixed_translations = 0

    for iid, it in raw_data.items():
        src_info = it.get("source", {})
        src_id = src_info.get("id")
        src_cfg = sources_map.get(src_id, {
            "id": src_id,
            "name": src_info.get("name", src_id),
            "kind": "news",
            "weight": 0.8,
            "categories": it.get("categories", [])
        })

        # Lấy tiêu đề và tóm tắt theo ngôn ngữ gốc
        orig_lang = it.get("original_lang", "en")
        raw_title_orig = it.get("title", {}).get(orig_lang, "") or list(it.get("title", {}).values())[0]
        raw_summ_orig = it.get("summary", {}).get(orig_lang, "") or list(it.get("summary", {}).values())[0]

        # 1. Làm sạch văn bản và gỡ bỏ mã HTML
        clean_title_orig = clean_boilerplate_str(raw_title_orig)
        clean_summ_orig = clean_boilerplate_str(raw_summ_orig)
        clean_summ_orig = strip_title_prefix(clean_summ_orig, clean_title_orig)

        # 2. Kiểm tra bộ lọc accept
        mock_raw_item = {
            "raw_title": clean_title_orig,
            "raw_summary": clean_summ_orig,
        }
        is_ok, reason = accept(mock_raw_item, src_cfg)
        if not is_ok:
            if reason.startswith("blocklist"):
                dropped_blocklist += 1
            else:
                dropped_non_howto += 1
            continue

        # 3. Xử lý bản dịch: Xóa bỏ triệt để các câu dịch chắp vá trộn tiếng Anh-Việt
        title_dict = {orig_lang: clean_title_orig}
        summary_dict = {orig_lang: clean_summ_orig}
        trans_meta = {}

        if orig_lang == "en":
            existing_vi_title = clean_boilerplate_str(it.get("title", {}).get("vi", ""))
            existing_vi_summ = clean_boilerplate_str(it.get("summary", {}).get("vi", ""))

            # Nếu bản dịch cũ bị trộn (is_mixed) hoặc không phải tiếng Việt thật sự:
            if (
                is_mixed(existing_vi_title) or
                is_mixed(existing_vi_summ) or
                not looks_vietnamese(existing_vi_title)
            ):
                # Khôi phục về nguyên bản tiếng Anh, KHÔNG gắn nhãn dịch máy
                title_dict["vi"] = clean_title_orig
                summary_dict["vi"] = clean_summ_orig
                cleaned_mixed_translations += 1
            else:
                # Tiếng Việt chuẩn (từ Gemini hoặc biên dịch thủ công)
                title_dict["vi"] = existing_vi_title
                summary_dict["vi"] = existing_vi_summ
                trans_meta["vi"] = "machine"
        else:
            # Bài gốc tiếng Việt
            existing_en_title = clean_boilerplate_str(it.get("title", {}).get("en", ""))
            existing_en_summ = clean_boilerplate_str(it.get("summary", {}).get("en", ""))
            if existing_en_title and not is_mixed(existing_en_title) and not looks_vietnamese(existing_en_title):
                title_dict["en"] = existing_en_title
                summary_dict["en"] = existing_en_summ
                trans_meta["en"] = "machine"
            else:
                title_dict["en"] = clean_title_orig
                summary_dict["en"] = clean_summ_orig

        # 4. Phân loại danh mục theo nội dung (tối đa 2 danh mục)
        fallback_cats = src_cfg.get("categories", it.get("categories", []))
        new_cats = classify(clean_title_orig, clean_summ_orig, fallback=fallback_cats, max_cats=2)
        new_tags = extract_tags(clean_title_orig, clean_summ_orig, max_tags=3)

        # 5. Xác định howto và độ khó
        is_howto = (src_cfg.get("kind") == "tips") or is_howto_match(clean_title_orig, clean_summ_orig)
        difficulty = detect_difficulty(clean_title_orig, clean_summ_orig, howto=is_howto)

        # 6. Tính điểm chất lượng
        score = calculate_score(
            title=clean_title_orig,
            summary=clean_summ_orig,
            source_weight=src_cfg.get("weight", 1.0),
            published_at=it.get("published_at", ""),
            is_howto=is_howto
        )

        cleaned_item = {
            "id": iid,
            "url": it["url"],
            "source": {
                "id": src_cfg["id"],
                "name": src_cfg["name"],
                "site_url": src_cfg.get("site_url", ""),
                "kind": src_cfg.get("kind", "news")
            },
            "author": it.get("author"),
            "published_at": it.get("published_at"),
            "fetched_at": it.get("fetched_at"),
            "original_lang": orig_lang,
            "title": title_dict,
            "summary": summary_dict,
            "categories": new_cats,
            "tags": new_tags,
            "difficulty": difficulty,
            "score": score,
            "howto": is_howto,
            "reading_time_min": estimate_reading_time(clean_summ_orig),
            "translated": trans_meta
        }
        if "hn_points" in it:
            cleaned_item["hn_points"] = it["hn_points"]
        if "hn_comments_url" in it:
            cleaned_item["hn_comments_url"] = it["hn_comments_url"]

        cleaned_items.append(cleaned_item)

    # 7. Áp dụng giới hạn xen kẽ nguồn (diversify, tối đa 2 bài liên tiếp cùng nguồn)
    diversified = diversify(cleaned_items, max_run=2)
    new_index = {item["id"]: item for item in diversified}

    # 8. Ghi lại dữ liệu chuẩn
    DATA_PATH.write_text(json.dumps(new_index, ensure_ascii=False, indent=2), encoding="utf-8")

    # 9. Làm sạch cache dịch thuật cũ nếu có
    if CACHE_PATH.exists():
        CACHE_PATH.unlink()
        print("-> Đã xóa cache bản dịch cũ chứa rác.")

    print("\n=== KẾT QUẢ MIGRATION ===")
    print(f"- Số bài ban đầu: {original_count}")
    print(f"- Đã loại bỏ do vi phạm blocklist (deal/QC/tuyển dụng): {dropped_blocklist}")
    print(f"- Đã loại bỏ do là tin tức chung, không phải thủ thuật: {dropped_non_howto}")
    print(f"- Đã khôi phục câu dịch trộn về nguyên bản tiếng Anh: {cleaned_mixed_translations}")
    print(f"- Số thủ thuật tinh chọn đạt chuẩn còn lại: {len(new_index)}")

if __name__ == "__main__":
    main()
