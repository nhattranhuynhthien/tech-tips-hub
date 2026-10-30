import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fetch import SourceFetchError, fetch_feed_items
from filters import accept

SOURCES_PATH = Path("config/sources.json")
NOTES_PATH = Path("config/sources.notes.md")


def check_source(source: dict) -> tuple[bool, list[dict], str]:
    try:
        entries = fetch_feed_items(source, max_entries=min(20, int(source.get("maxPerRun", 20))), state_entry={})
    except SourceFetchError as exc:
        return False, [], str(exc)

    valid = [
        item for item in entries
        if item.get("raw_title") and item.get("url") and item.get("published_at")
    ]
    if not valid:
        return False, [], "HTTP 200 nhưng không parse được mục có title, link và date."
    accepted = [item for item in valid if accept(item, source, enable_logging=False)[0]]
    return True, accepted[:3], f"HTTP 200; parsed {len(valid)} entries"


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: npm run check-source -- <source-id>")
        return 2

    sources = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    source = next((item for item in sources if item.get("id") == sys.argv[1]), None)
    if source is None:
        print(f"Unknown source id: {sys.argv[1]}")
        return 2

    ok, samples, message = check_source(source)
    source["enabled"] = ok
    SOURCES_PATH.write_text(json.dumps(sources, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if ok:
        print(f"PASS {source['id']}: {message}; {len(samples)} sample(s) after filtering")
        for sample in samples:
            print(f"- {sample['raw_title']}\n  {sample['url']}\n  {sample['published_at']}")
        if not samples:
            print("No item passed the current quality filters; source is enabled for future checks.")
    else:
        print(f"FAIL {source['id']}: {message}; source disabled")
        NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with NOTES_PATH.open("a", encoding="utf-8") as notes:
            notes.write(f"\n- {checked_at}: `{source['id']}` disabled by `check-source`: {message}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
