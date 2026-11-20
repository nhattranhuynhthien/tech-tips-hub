# scripts/translate_all.py
import sys
import json
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from translate import load_cache, save_cache, batch_translate_pending
from slug import generate_seo_slug


def main():
    print("=== [Tech Tips Hub] Bắt đầu tiến trình dịch thuật các bài viết đang hiển thị ===")
    index_path = Path("data/index.json")
    if not index_path.exists():
        print("Không tìm thấy data/index.json!")
        return

    data = json.loads(index_path.read_text(encoding="utf-8"))
    cache = load_cache()

    visible_items = [it for it in data.values() if not it.get("hidden")]
    print(f"Tổng số bài viết hiển thị: {len(visible_items)}")

    # Tiến hành dịch theo lô các bài chưa có bản dịch
    batch_translate_pending(visible_items, cache, batch_size=10)

    # Cập nhật lại index và slug cho bài mới / bài tiếng Trung sau khi dịch
    for it in visible_items:
        iid = it["id"]
        orig_lang = str(it.get("original_lang", "en")).lower()
        curr_slug = it.get("slug") or ""
        if not curr_slug or curr_slug.startswith("tip-") or orig_lang.startswith("zh"):
            best_title = (
                (it.get("title", {}).get("vi") if it.get("translated", {}).get("vi") == "machine" else None)
                or (it.get("title", {}).get("en") if it.get("translated", {}).get("en") == "machine" else None)
                or it.get("title", {}).get("vi")
                or it.get("title", {}).get("en")
                or ""
            )
            if best_title:
                it["slug"] = generate_seo_slug(best_title, iid)
        data[iid] = it

    # Lưu cache và index
    save_cache(cache)
    index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n✅ Dịch thuật hoàn tất và đã cập nhật data/index.json!")


if __name__ == "__main__":
    main()
