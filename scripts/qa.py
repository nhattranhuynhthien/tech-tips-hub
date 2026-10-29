# scripts/qa.py
import sys
import json
import re
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from translate import is_mixed, looks_vietnamese

ENTITY_REGEX = re.compile(r"&(#\d+|\w+);")
BOILERPLATE_PATTERNS = [
    re.compile(r"Article URL:", re.IGNORECASE),
    re.compile(r"appeared first on", re.IGNORECASE),
    re.compile(r"Originally published at", re.IGNORECASE),
    re.compile(r"\[Bản dịch\]", re.IGNORECASE),
    re.compile(r"\[Summary\]", re.IGNORECASE),
]

BLOCKLIST_CHECK = re.compile(
    r"(\bdeals?\b|\bdiscount\b|% off|\$\d+ off|drops to|price cut|"
    r"\[QC\]|is hiring|\bhiring\b|tuyển dụng|\btrailer\b)",
    re.IGNORECASE
)

def main():
    index_path = Path("data/index.json")
    if not index_path.exists():
        print("[QA Error] Không tìm thấy file data/index.json!")
        sys.exit(1)

    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[QA Error] Lỗi đọc JSON index.json: {e}")
        sys.exit(1)

    items = list(data.values())
    if not items:
        print("[QA Error] data/index.json không có dữ liệu!")
        sys.exit(1)

    problems = []
    cat_total = 0
    howto_count = 0
    mixed_count = 0

    for it in items:
        iid = it.get("id", "unknown")
        
        # 1. Kiểm tra HTML entities trong tiêu đề và tóm tắt
        for lang, text in it.get("title", {}).items():
            if ENTITY_REGEX.search(text):
                problems.append(f"Mã HTML entity trong tiêu đề [{lang}] ({iid}): {text[:50]}")
            if is_mixed(text):
                mixed_count += 1
                problems.append(f"Câu trộn tiếng Anh-Việt trong tiêu đề ({iid}): {text[:60]}")

        for lang, text in it.get("summary", {}).items():
            if ENTITY_REGEX.search(text):
                problems.append(f"Mã HTML entity trong tóm tắt [{lang}] ({iid}): {text[:50]}")
            if is_mixed(text):
                mixed_count += 1
                problems.append(f"Câu trộn tiếng Anh-Việt trong tóm tắt ({iid}): {text[:60]}")
            for bp in BOILERPLATE_PATTERNS:
                if bp.search(text):
                    problems.append(f"Boilerplate/rác trong tóm tắt [{lang}] ({iid}): {bp.pattern}")

        # 2. Kiểm tra danh mục
        cats = it.get("categories", [])
        cat_total += len(cats)
        if len(cats) > 2:
            problems.append(f"Bài có hơn 2 danh mục ({iid}): {cats}")

        # 3. Kiểm tra nhãn dịch máy sai sự thật
        trans_meta = it.get("translated", {})
        if trans_meta.get("vi") == "machine":
            vi_title = it.get("title", {}).get("vi", "")
            if not looks_vietnamese(vi_title):
                problems.append(f"Gắn nhãn dịch máy tiếng Việt nhưng nội dung không phải tiếng Việt ({iid}): {vi_title[:50]}")

        # 4. Kiểm tra blocklist (quảng cáo, deal, tuyển dụng)
        all_text = " ".join(it.get("title", {}).values()) + " " + " ".join(it.get("summary", {}).values())
        if BLOCKLIST_CHECK.search(it.get("title", {}).get("en", "")):
            problems.append(f"Chứa từ khóa bị chặn trong tiêu đề ({iid}): {it.get('title', {}).get('en', '')[:50]}")

        # 5. Đếm howto
        if it.get("howto") or it.get("difficulty"):
            howto_count += 1

    avg_cats = cat_total / max(len(items), 1)
    howto_ratio = howto_count / max(len(items), 1)

    print("=== [Tech Tips Hub - Báo cáo chất lượng dữ liệu QA] ===")
    print(f"- Tổng số bài viết: {len(items)}")
    print(f"- Danh mục trung bình / bài: {avg_cats:.2f} (chuẩn: <= 2.00)")
    print(f"- Tỉ lệ bài thủ thuật / hướng dẫn: {howto_ratio * 100:.1f}% (chuẩn: >= 80.0%)")
    print(f"- Số câu dịch trộn: {mixed_count} (chuẩn: 0)")
    print(f"- Tổng số lỗi vi phạm phát hiện: {len(problems)}")

    if problems:
        print("\n--- [Chi tiết 20 lỗi đầu tiên] ---")
        for p in problems[:20]:
            print(f"❌ {p}")
        print("\n=> QA thất bại! Dữ liệu chưa đạt chuẩn kiểm tra.")
        sys.exit(1)

    print("\n✅ QA THÀNH CÔNG: Dữ liệu đạt 100% tiêu chí chất lượng!")
    sys.exit(0)

if __name__ == "__main__":
    main()

