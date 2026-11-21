# scripts/qa.py
import os
import sys
import json
import re
import yaml
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dedupe import canonical_url
from textclean import RAW_HTML_TAG_RE, is_url_only_text
from translate import (
    is_mixed,
    looks_vietnamese,
    looks_english,
    non_url_alpha_count,
    LANG_CODE_RE,
    DANGEROUS_URI_RE,
)

ENTITY_REGEX = re.compile(r"&(#\d+|\w+);")
MOJIBAKE_WORD_REGEX = re.compile(r"[A-Za-zÀ-ỹ]\?[A-Za-zÀ-ỹ]")
URL_ONLY_REGEX = re.compile(r"^\s*https?://\S+\s*$", re.IGNORECASE)
ISO_DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
BOILERPLATE_PATTERNS = [
    re.compile(r"Article URL:", re.IGNORECASE),
    re.compile(r"appeared first on", re.IGNORECASE),
    re.compile(r"Originally published at", re.IGNORECASE),
    re.compile(r"\[Bản dịch\]", re.IGNORECASE),
    re.compile(r"\[Summary\]", re.IGNORECASE),
]

BLOCKLIST_CHECK = re.compile(
    r"(\bdeals?\b|\bdiscount\b|% off|\$\d+ off|drops to|price cut|"
    r"\[QC\]|is hiring|\bhiring\b|\btuyển dụng\b|\btrailer\b|"
    r"双十一|双11|喜加一|官方补贴|\d+(?:\.\d+)?\s*折(?!叠))",
    re.IGNORECASE
)


def load_valid_categories() -> set[str]:
    cat_path = Path("config/categories.yml")
    if not cat_path.exists():
        return set()
    doc = yaml.safe_load(cat_path.read_text(encoding="utf-8")) or {}
    return {c["id"] for c in doc.get("categories", []) if c.get("id")}


def validate_machine_translation(item: dict) -> list[str]:
    """Kiểm định tính trung thực của nhãn translated[lang] == 'machine' trên cả tiêu đề và tóm tắt."""
    iid = item.get("id", "unknown")
    orig_lang = str(item.get("original_lang") or "").strip()
    trans_meta = item.get("translated") if isinstance(item.get("translated"), dict) else {}
    titles = item.get("title") if isinstance(item.get("title"), dict) else {}
    summaries = item.get("summary") if isinstance(item.get("summary"), dict) else {}
    errors: list[str] = []

    for lang in ("vi", "en"):
        if trans_meta.get(lang) != "machine":
            continue
        t = str(titles.get(lang) or "")
        s = str(summaries.get(lang) or "")

        if orig_lang and orig_lang.lower() != lang:
            orig_t = str(titles.get(orig_lang) or "")
            orig_s = str(summaries.get(orig_lang) or "")
            if t.strip() == orig_t.strip() and s.strip() == orig_s.strip():
                errors.append(
                    f"Gắn nhãn dịch máy [{lang}] nhưng nội dung giống hệt bản gốc [{orig_lang}] ({iid}): {t[:50]}"
                )

        if lang == "vi":
            if not looks_vietnamese(t):
                errors.append(
                    f"Gắn nhãn dịch máy tiếng Việt nhưng nội dung không phải tiếng Việt ({iid}): {t[:50]}"
                )
            if non_url_alpha_count(s) >= 15 and not looks_vietnamese(s):
                errors.append(
                    f"Gắn nhãn dịch máy tiếng Việt nhưng tóm tắt không phải tiếng Việt ({iid}): {s[:60]}"
                )
        else:
            if not looks_english(t):
                errors.append(
                    f"Gắn nhãn dịch máy tiếng Anh nhưng nội dung không phải tiếng Anh ({iid}): {t[:50]}"
                )
            if non_url_alpha_count(s) >= 15 and not looks_english(s):
                errors.append(
                    f"Gắn nhãn dịch máy tiếng Anh nhưng tóm tắt không phải tiếng Anh ({iid}): {s[:60]}"
                )

    return errors


def validate_key_points(item: dict) -> list[str]:
    """Kiểm định trường key_points tùy chọn nếu có mặt trên bài viết."""
    if "key_points" not in item:
        return []

    iid = item.get("id", "unknown")
    kp = item.get("key_points")
    errors: list[str] = []

    if not isinstance(kp, dict):
        errors.append(f"key_points phải là dict theo mã ngôn ngữ ({iid})")
        return errors

    if not kp:
        errors.append(f"key_points không được là dict rỗng ({iid})")
        return errors

    for lang, points in kp.items():
        if not isinstance(lang, str) or not LANG_CODE_RE.match(lang):
            errors.append(f"Mã ngôn ngữ key_points không hợp lệ ({iid}): {lang!r}")
            continue
        if not isinstance(points, list):
            errors.append(f"key_points [{lang}] phải là danh sách ({iid})")
            continue
        if len(points) == 0:
            errors.append(f"key_points [{lang}] không được là danh sách rỗng ({iid})")
            continue
        if len(points) > 4:
            errors.append(f"key_points [{lang}] có quá 4 mục ({len(points)} > 4) ({iid})")

        for idx, point in enumerate(points):
            if not isinstance(point, str):
                errors.append(f"key_points [{lang}][{idx}] phải là chuỗi ({iid})")
                continue
            if not point.strip():
                errors.append(f"key_points [{lang}][{idx}] rỗng ({iid})")
                continue
            if len(point) > 200:
                errors.append(
                    f"key_points [{lang}][{idx}] quá dài ({len(point)} ký tự > 200) ({iid}): {point[:50]}"
                )
            if RAW_HTML_TAG_RE.search(point):
                errors.append(f"key_points [{lang}][{idx}] chứa thẻ HTML thô ({iid}): {point[:50]}")
            if DANGEROUS_URI_RE.search(point):
                errors.append(f"key_points [{lang}][{idx}] chứa URI nguy hiểm ({iid}): {point[:50]}")

    return errors


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

    md = [f"**Tổng số bài bị loại ghi nhận trong nhật ký:** {total_rejected}\n"]
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

    valid_categories = load_valid_categories()

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
        src = it.get("source", {})
        src_id = src.get("id", "unknown")
        src_name = src.get("name", "")
        source_counts[src_id] = source_counts.get(src_id, 0) + 1

        if MOJIBAKE_WORD_REGEX.search(src_name):
            problems.append(f"Tên nguồn bị lỗi mã hóa '?' ({iid}): {src_name}")

        # 0. Kiểm tra URL hợp lệ (chỉ chấp nhận http/https) và định dạng ngày xuất bản ISO-8601
        item_url = str(it.get("url") or "").strip()
        if not canonical_url(item_url):
            problems.append(f"URL không hợp lệ hoặc giao thức không an toàn ({iid}): {item_url!r}")

        pub_at = str(it.get("published_at") or "").strip()
        if not ISO_DATE_REGEX.match(pub_at):
            problems.append(f"Ngày published_at không đúng chuẩn ISO-8601 ({iid}): {pub_at!r}")
        else:
            try:
                datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
            except ValueError:
                problems.append(f"Ngày published_at không phân tích được ({iid}): {pub_at!r}")

        # 1. Kiểm tra cấu trúc, HTML thô, HTML entities, câu trộn & blocklist trong tiêu đề mọi ngôn ngữ
        titles_map = it.get("title")
        if not isinstance(titles_map, dict) or not titles_map:
            problems.append(f"Thiếu hoặc rỗng trường title ({iid})")
        else:
            for lang, text in titles_map.items():
                if not isinstance(text, str) or not text.strip():
                    problems.append(f"Tiêu đề rỗng [{lang}] ({iid})")
                    continue
                if RAW_HTML_TAG_RE.search(text):
                    problems.append(f"Chứa thẻ HTML thô trong tiêu đề [{lang}] ({iid}): {text[:50]}")
                if ENTITY_REGEX.search(text):
                    problems.append(f"Mã HTML entity trong tiêu đề [{lang}] ({iid}): {text[:50]}")
                if is_mixed(text):
                    mixed_count += 1
                    problems.append(f"Câu trộn tiếng Anh-Việt trong tiêu đề ({iid}): {text[:60]}")
                if BLOCKLIST_CHECK.search(text):
                    problems.append(f"Chứa từ khóa bị chặn trong tiêu đề [{lang}] ({iid}): {text[:50]}")

        # 2. Kiểm tra cấu trúc, HTML thô, HTML entities, câu trộn, URL trần & độ dài tóm tắt
        summaries_map = it.get("summary")
        if not isinstance(summaries_map, dict) or not summaries_map:
            problems.append(f"Thiếu hoặc rỗng trường summary ({iid})")
        else:
            for lang, text in summaries_map.items():
                if not isinstance(text, str) or not text.strip():
                    problems.append(f"Tóm tắt rỗng [{lang}] ({iid})")
                    continue
                if RAW_HTML_TAG_RE.search(text):
                    problems.append(f"Chứa thẻ HTML thô trong tóm tắt [{lang}] ({iid}): {text[:50]}")
                if is_url_only_text(text):
                    problems.append(f"Tóm tắt chỉ chứa URL trần [{lang}] ({iid}): {text[:60]}")
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

        # 3. Kiểm tra danh mục hợp lệ
        cats = it.get("categories", [])
        cat_total += len(cats)
        if not cats:
            problems.append(f"Bài không có danh mục ({iid})")
        if len(cats) > 2:
            problems.append(f"Bài có hơn 2 danh mục ({iid}): {cats}")
        if valid_categories:
            invalid_cats = [c for c in cats if c not in valid_categories]
            if invalid_cats:
                problems.append(f"Danh mục không hợp lệ ({iid}): {invalid_cats}")

        # 4. Kiểm tra nhãn dịch máy sai sự thật (cả tiêu đề, tóm tắt & bản sao nguyên văn)
        problems.extend(validate_machine_translation(it))

        # 5. Kiểm định key_points tùy chọn nếu có
        problems.extend(validate_key_points(it))

        # 6. Đếm bài howto / thủ thuật từ nguồn chuyên tips
        if it.get("howto") or it.get("difficulty") or src.get("kind") == "tips":
            howto_count += 1

    avg_cats = cat_total / max(len(items), 1)
    howto_ratio = howto_count / max(len(items), 1)
    if avg_cats > 2.0:
        problems.append(f"Số danh mục trung bình vượt ngưỡng ({avg_cats:.2f} > 2.00)")
    if howto_ratio < 0.8:
        problems.append(f"Tỷ lệ bài thủ thuật / hướng dẫn dưới ngưỡng ({howto_ratio * 100:.1f}% < 80.0%)")

    print("=== [Tech Tips Hub - Báo cáo chất lượng dữ liệu QA] ===")
    print(f"- Tổng số bài viết hiển thị: {len(items)}")
    print(f"- Danh mục trung bình / bài: {avg_cats:.2f} (chuẩn: <= 2.00)")
    print(f"- Tỉ lệ bài thủ thuật / hướng dẫn: {howto_ratio * 100:.1f}% (chuẩn: >= 80.0%)")
    print(f"- Số câu dịch trộn: {mixed_count} (chuẩn: 0)")
    print(f"- Tổng số lỗi vi phạm phát hiện: {len(problems)}")

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
