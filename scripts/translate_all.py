# scripts/translate_all.py
import sys
import json
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from translate import load_cache, save_cache, batch_translate_pending
from slug import generate_seo_slug

def main():
    print("=== [Tech Tips Hub] Bắt đầu tiến trình dịch thuật toàn bộ bài viết ===")
    index_path = Path("data/index.json")
    if not index_path.exists():
        print("Không tìm thấy data/index.json!")
        return

    data = json.loads(index_path.read_text(encoding="utf-8"))
    cache = load_cache()

    items = list(data.values())
    print(f"Tổng số bài viết trong kho: {len(items)}")

    # Tiến hành dịch theo lô các bài chưa có bản dịch
    batch_translate_pending(items, cache, batch_size=10)

    # Cập nhật lại index và slug nếu cần
    for it in items:
        iid = it["id"]
        # Nếu đã có bản dịch tiếng Việt và slug cũ chưa phải tiếng Việt, có thể cập nhật
        orig_lang = it.get("original_lang", "en")
        if it.get("translated", {}).get("vi") == "machine":
            vi_title = it.get("title", {}).get("vi")
            if vi_title:
                it["slug"] = generate_seo_slug(vi_title, iid)
        data[iid] = it

    # Lưu cache và index
    save_cache(cache)
    index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ Dịch thuật hoàn tất và đã cập nhật data/index.json!")

if __name__ == "__main__":
    main()

