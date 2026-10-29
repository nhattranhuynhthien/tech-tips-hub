# scripts/qa.py
import os
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

def summarize_rejections() -> str:
    """Tóm tắt dữ liệu từ chối bài viết từ data/logs/rejected.jsonl."""
    log_path = Path("data/logs/rejected.jsonl")
    if not log_path.exists():
        return "*(Chưa có bản ghi loại bỏ nào)*"
    
    source_stats = {}
    reason_stats = {}
    total_rejected = 0

    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                total_rejected += 1
                src = entry.get("source", "unknown")
                rsn = entry.get("reason", "unknown")
                source_stats[src] = source_stats.get(src, 0) + 1
                reason_stats[rsn] = reason_stats.get(rsn, 0) + 1
            except Exception:
                pass

    if total_rejected == 0:
        return "*(Không có bài viết nào bị loại)*"

    md = [f"**Tổng số bài bị loại trong đợt quét:** {total_rejected}\n"]
    md.append("| Lý do loại bỏ | Số lượng | Tỷ lệ |")
    md.append("|---|---|---|")
    for rsn, count in sorted(reason_stats.items(), key=lambda x: -x[1]):
        pct = (count / total_rejected) * 100
        md.append(f"| `{rsn}` | {count} | {pct:.1f}% |")

    md.append("\n**Top nguồn có bài bị loại:**\n")
    md.append("| Nguồn | Số bài bị loại | Tỷ lệ |")
    md.append("|---|---|---|")
    for src, count in sorted(source_stats.items(), key=lambda x: -x[1])[:10]:
        pct = (count / total_rejected) * 100
        md.append(f"| `{src}` | {count} | {pct:.1f}% |")

    return "\n".join(md)

def append_to_github_summary(content: str):
    """Ghi báo cáo Markdown vào GitHub Job Summary nếu đang chạy trên CI."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write(content + "\n")
        except Exception as e:
            print(f"[QA Warning] Không thể ghi vào GITHUB_STEP_SUMMARY: {e}")

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

    # Chỉ đánh giá các bài đang hiển thị (không bị ẩn)
    items = [it for it in data.values() if not it.get("hidden")]
    if not items:
        print("[QA Error] data/index.json không có dữ liệu hiển thị (tất cả bị ẩn hoặc rỗng)!")
        sys.exit(1)

    problems = []
    cat_total = 0
    howto_count = 0
    mixed_count = 0
    source_counts = {}

    for it in items:
        iid = it.get("id", "unknown")
        src_id = it.get("source", {}).get("id", "unknown")
        source_counts[src_id] = source_counts.get(src_id, 0) + 1
        
        # 1. Kiểm tra HTML entities & câu trộn trong tiêu đề
        for lang, text in it.get("title", {}).items():
            if not text or len(text.strip()) == 0:
                problems.append(f"Tiêu đề rỗng [{lang}] ({iid})")
            if ENTITY_REGEX.search(text):
                problems.append(f"Mã HTML entity trong tiêu đề [{lang}] ({iid}): {text[:50]}")
            if is_mixed(text):
                mixed_count += 1
                problems.append(f"Câu trộn tiếng Anh-Việt trong tiêu đề ({iid}): {text[:60]}")

        # 2. Kiểm tra HTML entities, câu trộn & độ dài tóm tắt
        for lang, text in it.get("summary", {}).items():
            if not text or len(text.strip()) == 0:
                problems.append(f"Tóm tắt rỗng [{lang}] ({iid})")
            if len(text) > 500:
                problems.append(f"Tóm tắt quá dài ({len(text)} ký tự > 500) [{lang}] ({iid}): {text[:60]}")
            if ENTITY_REGEX.search(text):
                problems.append(f"Mã HTML entity trong tóm tắt [{lang}] ({iid}): {text[:50]}")
            if is_mixed(text):
                mixed_count += 1
                problems.append(f"Câu trộn tiếng Anh-Việt trong tóm tắt ({iid}): {text[:60]}")
            for bp in BOILERPLATE_PATTERNS:
                if bp.search(text):
                    problems.append(f"Boilerplate/rác trong tóm tắt [{lang}] ({iid}): {bp.pattern}")

        # 3. Kiểm tra danh mục
        cats = it.get("categories", [])
        cat_total += len(cats)
        if len(cats) > 2:
            problems.append(f"Bài có hơn 2 danh mục ({iid}): {cats}")

        # 4. Kiểm tra nhãn dịch máy sai sự thật
        trans_meta = it.get("translated", {})
        if trans_meta.get("vi") == "machine":
            vi_title = it.get("title", {}).get("vi", "")
            if not looks_vietnamese(vi_title):
                problems.append(f"Gắn nhãn dịch máy tiếng Việt nhưng nội dung không phải tiếng Việt ({iid}): {vi_title[:50]}")

        # 5. Kiểm tra blocklist (quảng cáo, deal, tuyển dụng)
        if BLOCKLIST_CHECK.search(it.get("title", {}).get("en", "")):
            problems.append(f"Chứa từ khóa bị chặn trong tiêu đề ({iid}): {it.get('title', {}).get('en', '')[:50]}")

        # 6. Đếm bài howto / thủ thuật từ nguồn chuyên tips
        if it.get("howto") or it.get("difficulty") or it.get("source", {}).get("kind") == "tips":
            howto_count += 1

    avg_cats = cat_total / max(len(items), 1)
    howto_ratio = howto_count / max(len(items), 1)

    print("=== [Tech Tips Hub - Báo cáo chất lượng dữ liệu QA] ===")
    print(f"- Tổng số bài viết hiển thị: {len(items)}")
    print(f"- Danh mục trung bình / bài: {avg_cats:.2f} (chuẩn: <= 2.00)")
    print(f"- Tỉ lệ bài thủ thuật / hướng dẫn: {howto_ratio * 100:.1f}% (chuẩn: >= 80.0%)")
    print(f"- Số câu dịch trộn: {mixed_count} (chuẩn: 0)")
    print(f"- Tổng số lỗi vi phạm phát hiện: {len(problems)}")

    # Tạo nội dung báo cáo cho GitHub Job Summary
    status_icon = "✅" if not problems and avg_cats <= 2.0 and howto_ratio >= 0.8 else "❌"
    summary_md = [
        f"## {status_icon} Tech Tips Hub — Báo cáo Kiểm định Dữ liệu (QA Report)\n",
        "| Chỉ số kiểm định | Kết quả thực tế | Tiêu chuẩn nghiệm thu | Trạng thái |",
        "|---|---|---|---|",
        f"| **Tổng số thủ thuật hợp lệ** | `{len(items)} bài` | `> 0 bài` | {'✅ Đạt' if len(items) > 0 else '❌ Hỏng'} |",
        f"| **Danh mục trung bình / bài** | `{avg_cats:.2f}` | `≤ 2.00` | {'✅ Đạt' if avg_cats <= 2.0 else '❌ Hỏng'} |",
        f"| **Tỷ lệ thủ thuật / hướng dẫn** | `{howto_ratio * 100:.1f}%` | `≥ 80.0%` | {'✅ Đạt' if howto_ratio >= 0.8 else '❌ Hỏng'} |",
        f"| **Số câu dịch trộn (Mixed)** | `{mixed_count}` | `0 câu` | {'✅ Đạt' if mixed_count == 0 else '❌ Hỏng'} |",
        f"| **Tổng số lỗi vi phạm phát hiện** | `{len(problems)}` | `0 lỗi` | {'✅ Đạt' if len(problems) == 0 else '❌ Hỏng'} |\n",
        "### 📊 Phân tích Bộ lọc và Loại bỏ bài viết\n",
        summarize_rejections()
    ]

    if problems:
        summary_md.append("\n### ⚠️ Danh sách lỗi vi phạm (20 lỗi đầu tiên):")
        for p in problems[:20]:
            summary_md.append(f"- ❌ {p}")

    append_to_github_summary("\n".join(summary_md))

    if problems:
        print("\n--- [Chi tiết 20 lỗi đầu tiên] ---")
        for p in problems[:20]:
            print(f"❌ {p}")
        print("\n=> QA THẤT BẠI! Dữ liệu không đạt tiêu chuẩn. Hủy commit dữ liệu để bảo vệ hệ thống.")
        sys.exit(1)

    print("\n✅ QA THÀNH CÔNG: Dữ liệu đạt 100% tiêu chí chất lượng!")
    sys.exit(0)

if __name__ == "__main__":
    main()
