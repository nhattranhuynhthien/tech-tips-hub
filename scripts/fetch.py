# scripts/fetch.py
import sys
import re
import html
import json
import time
from datetime import datetime, timezone
import requests
import feedparser
from bs4 import BeautifulSoup
from dedupe import canonical_url, generate_id
from textclean import clean_text, strip_title_prefix, unescape_all

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

USER_AGENT = "TechTipsHubBot/1.0 (+https://meocongnghe.vercel.app)"


class SourceFetchError(RuntimeError):
    """Raised when a source could not be fetched or parsed reliably."""


def source_weight(source: dict) -> float:
    if "weight" in source:
        return float(source["weight"])
    trust = max(1, min(5, int(source.get("trust", 3))))
    return 0.5 + (trust - 1) * 0.25


def _get_response(url: str, headers: dict, state_entry: dict | None = None):
    """Fetch with conditional headers and two retries for transient failures."""
    request_headers = dict(headers)
    state_entry = state_entry if state_entry is not None else {}
    if state_entry.get("etag"):
        request_headers["If-None-Match"] = state_entry["etag"]
    if state_entry.get("last_modified"):
        request_headers["If-Modified-Since"] = state_entry["last_modified"]

    session = requests.Session()
    last_error = None
    for attempt in range(3):
        try:
            response = session.get(url, headers=request_headers, timeout=10)
            if response.status_code == 304:
                state_entry["not_modified"] = True
                return response
            if response.status_code == 200:
                state_entry["not_modified"] = False
                if response.headers.get("ETag"):
                    state_entry["etag"] = response.headers["ETag"]
                if response.headers.get("Last-Modified"):
                    state_entry["last_modified"] = response.headers["Last-Modified"]
                return response
            if response.status_code != 429 and response.status_code < 500:
                raise SourceFetchError(f"HTTP {response.status_code}")
            last_error = f"HTTP {response.status_code}"
        except SourceFetchError:
            raise
        except requests.RequestException as e:
            last_error = str(e)
        if attempt < 2:
            time.sleep(0.5 * (2 ** attempt))
    raise SourceFetchError(last_error or "Request thất bại")

def parse_hn_summary(raw_summary: str, min_score: int = 100) -> tuple[int, str, int, str]:
    """
    Trích xuất points, comments_url, comments_count từ feed Hacker News.
    Trả về (points, comments_url, comments_count, clean_summary).
    Mặc định ngưỡng điểm tối thiểu là 100.
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

    # Tóm tắt sạch cho Hacker News (không dùng boilerplate URL)
    clean_summary = f"Thảo luận trên Hacker News ({points} điểm, {comments_count} bình luận)."
    return points, comments_url, comments_count, clean_summary

def fetch_feed_items(source: dict, max_entries: int = 25, state_entry: dict | None = None) -> list[dict]:
    """Tải và phân tích các bài viết mới từ nguồn RSS/Atom hoặc REST API."""
    items = []
    source_type = source.get("type", "rss")
    feed_url = source["url"]
    min_score = source.get("minScore", source.get("min_score", 100 if source["id"] == "hackernews" else 0))

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/json, application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
        "Cache-Control": "no-cache",
    }

    # === Trường hợp 1: REST API (Dev.to API) ===
    if source_type in ["devto_api", "json_api", "json-api"]:
        try:
            resp = _get_response(feed_url, headers, state_entry)
            if resp.status_code == 304:
                return []
            articles = resp.json()
            api = source.get("api", "devto")
            if api == "hn_algolia":
                articles = articles.get("hits", [])
            elif isinstance(articles, dict):
                articles = articles.get("articles", articles.get("items", []))
            if not isinstance(articles, list):
                raise ValueError("API response does not contain an item list")

            for a in articles[:max_entries]:
                if api == "hn_algolia":
                    raw_t = a.get("story_title") or a.get("title")
                    link = a.get("story_url") or a.get("url")
                    published = a.get("created_at") or ""
                    points = int(a.get("points") or 0)
                    if points < int(source.get("minScore", 0)):
                        continue
                    raw_desc = a.get("story_text") or f"Hacker News story with {points} points."
                    author = a.get("author")
                    reactions = points
                elif api == "stackexchange":
                    raw_t = a.get("title")
                    link = a.get("link")
                    published = datetime.fromtimestamp(a["creation_date"], timezone.utc).isoformat() if a.get("creation_date") else ""
                    raw_desc = a.get("body", "")
                    author = (a.get("owner") or {}).get("display_name")
                    reactions = a.get("score", 0)
                else:
                    link = a.get("url") or a.get("canonical_url")
                    raw_t = a.get("title")
                    published = a.get("published_at") or a.get("created_at") or ""
                    author_obj = a.get("user") or {}
                    author = author_obj.get("name") if isinstance(author_obj, dict) else a.get("author")
                    raw_desc = a.get("description") or a.get("summary") or ""
                    reactions = a.get("public_reactions_count", a.get("positive_reactions_count", 0)) or 0
                if not link or not raw_t:
                    continue
                if not published:
                    continue

                # Lọc bài Dev.to có lượt phản ứng quá thấp (< 3) để đảm bảo chất lượng
                if api == "devto" and reactions < 3:
                    continue

                c_url = canonical_url(link)
                iid = generate_id(c_url)
                
                title = clean_text(raw_t, limit=160)
                summary = clean_text(raw_desc, limit=280)
                summary = strip_title_prefix(summary, title)

                items.append({
                    "id": iid,
                    "url": c_url,
                    "source": {
                        "id": source["id"],
                        "name": source["name"],
                        "site_url": source.get("site_url", ""),
                        "kind": source.get("kind", "news")
                    },
                    "source_weight": source_weight(source),
                    "source_kind": source.get("kind", "tips" if source.get("tipOnly") else "news"),
                    "content_type": source.get("contentType", "article"),
                    "author": author,
                    "published_at": published,
                    "original_lang": source.get("lang", "en"),
                    "raw_title": title,
                    "raw_summary": summary,
                    "default_categories": source.get("categories", []),
                    "reactions": reactions
                })
            return items
        except Exception as e:
            if isinstance(e, SourceFetchError):
                raise
            raise SourceFetchError(f"Lỗi tải API {source['id']}: {e}") from e

    # === Trường hợp 2: RSS / Atom Feed chuẩn ===
    try:
        resp = _get_response(feed_url, headers, state_entry)
        if resp.status_code == 304:
            return []
        feed = None if source_type == "telegram" else feedparser.parse(resp.content)
    except Exception as e:
        if isinstance(e, SourceFetchError):
            raise
        raise SourceFetchError(f"Lỗi tải nguồn {source['id']}: {e}") from e

    if source_type == "telegram":
        try:
            soup = BeautifulSoup(resp.text, "html.parser")
            for node in soup.select(".tgme_widget_message")[:max_entries]:
                text_node = node.select_one(".tgme_widget_message_text")
                date_node = node.select_one(".tgme_widget_message_date")
                if not text_node or not date_node or not date_node.get("href"):
                    continue
                raw_summary = clean_text(text_node.get_text(" ", strip=True), limit=280)
                title = clean_text(raw_summary, limit=160)
                published = ""
                time_node = date_node.select_one("time")
                if time_node:
                    published = time_node.get("datetime", "")
                url = canonical_url(date_node["href"])
                if not title or not url or not published:
                    continue
                items.append({
                    "id": generate_id(url), "url": url,
                    "source": {"id": source["id"], "name": source["name"], "site_url": source.get("site_url", ""), "kind": source.get("kind", "news")},
                    "source_weight": source_weight(source),
                    "source_kind": source.get("kind", "news"), "content_type": "community",
                    "author": source["name"], "published_at": published,
                    "original_lang": source.get("lang", "en"), "raw_title": title,
                    "raw_summary": raw_summary, "default_categories": source.get("categories", [])
                })
            return items
        except Exception as e:
            raise SourceFetchError(f"Lỗi parse Telegram {source['id']}: {e}") from e

    if getattr(feed, "bozo", False) and not getattr(feed, "entries", []):
        raise SourceFetchError(f"RSS/Atom {source['id']} không phân tích được: {feed.bozo_exception}")

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

        # Xử lý đặc thù Hacker News: lọc ngưỡng điểm và lưu riêng metadata
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

        published = getattr(entry, "published", "") or getattr(entry, "updated", "")
        if source_type == "reddit" and min_score > 0:
            score = getattr(entry, "reddit_score", None) or getattr(entry, "score", None)
            if score is None:
                score_match = re.search(r"(?:score|points|upvotes):\s*(\d+)", raw_summary, re.IGNORECASE)
                score = int(score_match.group(1)) if score_match else None
            if score is not None and int(score) < min_score:
                continue
        if not published:
            continue
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
            "source_weight": source_weight(source),
            "source_kind": source.get("kind", "tips" if source.get("tipOnly") else "news"),
            "content_type": source.get("contentType", "article"),
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
