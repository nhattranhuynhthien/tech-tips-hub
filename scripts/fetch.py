# scripts/fetch.py
import sys
import re
import html
import requests
import feedparser
from bs4 import BeautifulSoup
from dedupe import canonical_url, generate_id

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

def clean_html(raw_html: str, max_chars: int = 350) -> str:
    """Làm sạch HTML hoàn toàn, chỉ giữ lại văn bản thuần túy."""
    if not raw_html:
        return ""
    try:
        soup = BeautifulSoup(raw_html, "html.parser")
        for s in soup(["script", "style", "iframe", "form", "svg"]):
            s.decompose()
        text = soup.get_text(separator=" ", strip=True)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", raw_html)
    
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "..."
    return text

def fetch_feed_items(source: dict, max_entries: int = 25) -> list[dict]:
    """Tải và phân tích các bài viết mới từ một nguồn RSS/Atom."""
    items = []
    feed_url = source["url"]
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
        "Cache-Control": "no-cache",
    }

    try:
        session = requests.Session()
        resp = session.get(feed_url, headers=headers, timeout=10)
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
        title = getattr(entry, "title", None)
        if not link or not title:
            continue

        c_url = canonical_url(link)
        if not c_url:
            continue
        iid = generate_id(c_url)

        # Trích xuất tóm tắt từ description hoặc summary
        raw_summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
        summary = clean_html(raw_summary)

        # Ngày đăng
        published = getattr(entry, "published", "") or getattr(entry, "updated", "")
        
        # Tác giả nếu có
        author = getattr(entry, "author", None)

        items.append({
            "id": iid,
            "url": c_url,
            "source": {
                "id": source["id"],
                "name": source["name"],
                "site_url": source.get("site_url", "")
            },
            "source_weight": source.get("weight", 1.0),
            "author": author,
            "published_at": published,
            "original_lang": source.get("lang", "en"),
            "raw_title": title.strip(),
            "raw_summary": summary,
            "default_categories": source.get("categories", []),
        })

    return items
