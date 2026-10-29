# scripts/fetch.py
import sys
import re
import html
import requests
import feedparser
from bs4 import BeautifulSoup
from dedupe import canonical_url, generate_id
from textclean import clean_text, strip_title_prefix, unescape_all

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

def parse_hn_summary(raw_summary: str, min_score: int = 30) -> tuple[int, str, int, str]:
    """
    Trích xuất points, comments_url, comments_count từ feed Hacker News.
    Trả về (points, comments_url, comments_count, clean_summary).
    """
    points = 0
    comments_url = ""
    comments_count = 0

    pts_match = re.search(r"Points:\s*(\d+)", raw_summary)
    if pts_match:
        points = int(pts_match.group(1))

    cmt_url_match = re.search(r"Comments URL:\s*(https?://\S+)", raw_summary)
    if cmt_url_match:
        comments_url = cmt_url_match.group(1).rstrip(">\"' ")

    cmt_count_match = re.search(r"# Comments:\s*(\d+)", raw_summary)
    if cmt_count_match:
        comments_count = int(cmt_count_match.group(1))

    # Tóm tắt sạch cho Hacker News
    clean_summary = f"Thảo luận trên Hacker News ({points} điểm, {comments_count} bình luận)."
    return points, comments_url, comments_count, clean_summary

def fetch_feed_items(source: dict, max_entries: int = 25) -> list[dict]:
    """Tải và phân tích các bài viết mới từ nguồn RSS/Atom hoặc REST API."""
    items = []
    source_type = source.get("type", "rss")
    feed_url = source["url"]
    min_score = source.get("min_score", 0)

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/json, application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
        "Cache-Control": "no-cache",
    }

    # === Trường hợp 1: REST API (ví dụ Dev.to API) ===
    if source_type in ["devto_api", "json_api"]:
        try:
            session = requests.Session()
            resp = session.get(feed_url, headers=headers, timeout=12)
            if resp.status_code != 200:
                print(f"[Fetch Warning] API {source['id']} trả về status {resp.status_code}")
                return []
            articles = resp.json()
            if not isinstance(articles, list):
                articles = articles.get("articles", articles.get("items", []))

            for a in articles[:max_entries]:
                link = a.get("url") or a.get("canonical_url")
                raw_t = a.get("title")
                if not link or not raw_t:
                    continue

                c_url = canonical_url(link)
                iid = generate_id(c_url)
                
                title = clean_text(raw_t, limit=160)
                raw_desc = a.get("description") or a.get("summary") or ""
                summary = clean_text(raw_desc, limit=280)
                summary = strip_title_prefix(summary, title)

                published = a.get("published_at") or a.get("created_at") or ""
                author_obj = a.get("user") or {}
                author = author_obj.get("name") if isinstance(author_obj, dict) else a.get("author")

                items.append({
                    "id": iid,
                    "url": c_url,
                    "source": {
                        "id": source["id"],
                        "name": source["name"],
                        "site_url": source.get("site_url", ""),
                        "kind": source.get("kind", "news")
                    },
                    "source_weight": source.get("weight", 1.0),
                    "source_kind": source.get("kind", "news"),
                    "author": author,
                    "published_at": published,
                    "original_lang": source.get("lang", "en"),
                    "raw_title": title,
                    "raw_summary": summary,
                    "default_categories": source.get("categories", []),
                })
            return items
        except Exception as e:
            print(f"[Fetch Warning] Lỗi tải API {source['id']}: {e}")
            return []

    # === Trường hợp 2: RSS / Atom Feed chuẩn ===
    try:
        session = requests.Session()
        resp = session.get(feed_url, headers=headers, timeout=12)
        if resp.status_code != 200:
            print(f"[Fetch Warning] Nguồn {source['id']} trả về status code {resp.status_code}")
            return []
        feed = feedparser.parse(resp.content)
    except Exception as e:
        print(f"[Fetch Warning] Lỗi tải nguồn {source['id']}: {e}")
        return []

    entries = feed.entries[:max_entries] if hasattr(feed, "entries") else []
    for entry in entries:
        link = getattr(entry, "link", None)
        raw_t = getattr(entry, "title", None)
        if not link or not raw_t:
            continue

        c_url = canonical_url(link)
        if not c_url:
            continue
        iid = generate_id(c_url)

        raw_summary = getattr(entry, "summary", "") or getattr(entry, "description", "")

        # Xử lý đặc biệt cho Hacker News
        hn_points = 0
        hn_comments_url = None
        if source["id"] == "hackernews":
            hn_points, hn_comments_url, hn_comments_count, hn_clean_summ = parse_hn_summary(raw_summary, min_score)
            if min_score > 0 and hn_points < min_score:
                continue
            summary = hn_clean_summ
        else:
            summary = clean_text(raw_summary, limit=280)

        title = clean_text(raw_t, limit=160)
        summary = strip_title_prefix(summary, title)

        # Ngày đăng
        published = getattr(entry, "published", "") or getattr(entry, "updated", "")
        
        # Tác giả nếu có
        author = getattr(entry, "author", None)

        item = {
            "id": iid,
            "url": c_url,
            "source": {
                "id": source["id"],
                "name": source["name"],
                "site_url": source.get("site_url", ""),
                "kind": source.get("kind", "news")
            },
            "source_weight": source.get("weight", 1.0),
            "source_kind": source.get("kind", "news"),
            "author": author,
            "published_at": published,
            "original_lang": source.get("lang", "en"),
            "raw_title": title,
            "raw_summary": summary,
            "default_categories": source.get("categories", []),
        }
        if hn_points > 0:
            item["hn_points"] = hn_points
        if hn_comments_url:
            item["hn_comments_url"] = hn_comments_url

        items.append(item)

    return items
