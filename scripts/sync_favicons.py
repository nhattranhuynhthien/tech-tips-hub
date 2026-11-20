#!/usr/bin/env python3
"""Sync local cached favicons for all configured sources in config/sources.json.

Saves deterministic 32x32 PNG files into public/favicons/<source-id>.png so the
static site makes zero runtime requests to external favicon services. When a
remote favicon cannot be fetched or fails PNG validation, generates a clean,
deterministic 32x32 RGBA PNG badge using only Python stdlib (struct + zlib).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
import zlib
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCES_PATH = REPO_ROOT / "config" / "sources.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "public" / "favicons"

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MIN_PNG_BYTES = 100
GOOGLE_FAVICON_ENDPOINT = "https://www.google.com/s2/favicons"
USER_AGENT = (
    "TechTipsHub-FaviconSync/1.0 "
    "(+https://github.com/nhattranhuynhthien/tech-tips-hub)"
)
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

DEFAULT_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
  <rect x="1" y="1" width="30" height="30" rx="7" fill="#171A1E" stroke="#2A2F35" stroke-width="1.5"/>
  <path d="M9 10.5L15 16l-6 5.5" fill="none" stroke="#FFB547" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"/>
  <line x1="16.5" y1="21.5" x2="23" y2="21.5" stroke="#FFB547" stroke-width="2.75" stroke-linecap="round"/>
</svg>
"""

# Accent palette matching Tech Tips Hub's dark surface (#171A1E)
BADGE_ACCENT_PALETTE: tuple[tuple[int, int, int], ...] = (
    (255, 181, 71),   # Amber (#FFB547 - brand accent)
    (96, 165, 250),   # Sky blue
    (74, 222, 128),   # Emerald
    (192, 132, 252),  # Violet
    (244, 114, 182),  # Rose
    (45, 212, 191),   # Teal
    (251, 146, 60),   # Orange
    (129, 140, 248),  # Indigo
)

SURFACE_RGB = (23, 26, 30)  # #171A1E

# Compact 5x7 pixel bitmap font for crisp deterministic fallback badges
GLYPH_5X7: dict[str, tuple[str, ...]] = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("00111", "00010", "00010", "00010", "10010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "11011", "10001"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00110", "01000", "10000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("01110", "10000", "11110", "10001", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    # Default geometric prompt glyph
    "*": ("10000", "01000", "00100", "01000", "10000", "00000", "00111"),
}

COMMUNITY_GLYPH_7X7: tuple[str, ...] = (
    "0011100",
    "0011100",
    "0000000",
    "0111110",
    "1111111",
    "1100011",
    "1100011",
)


def is_valid_png(data: bytes) -> bool:
    """Return True if data looks like a valid non-trivial PNG binary."""
    return (
        len(data) > MIN_PNG_BYTES
        and data.startswith(PNG_MAGIC)
        and len(data) >= 24
        and data[12:16] == b"IHDR"
        and b"IEND" in data[-16:]
    )


def is_valid_png_file(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        return is_valid_png(path.read_bytes())
    except OSError:
        return False


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def _encode_rgba_png(width: int, height: int, rows: list[bytes]) -> bytes:
    raw_scanlines = b"".join(b"\x00" + row for row in rows)
    compressed = zlib.compress(raw_scanlines, level=9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        PNG_MAGIC
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", compressed)
        + _png_chunk(b"IEND", b"")
    )


def _inside_rounded_rect(x: int, y: int, size: int, radius: int) -> bool:
    if x < radius and y < radius:
        dx, dy = radius - 1 - x, radius - 1 - y
        return dx * dx + dy * dy <= radius * radius
    if x >= size - radius and y < radius:
        dx, dy = x - (size - radius), radius - 1 - y
        return dx * dx + dy * dy <= radius * radius
    if x < radius and y >= size - radius:
        dx, dy = radius - 1 - x, y - (size - radius)
        return dx * dx + dy * dy <= radius * radius
    if x >= size - radius and y >= size - radius:
        dx, dy = x - (size - radius), y - (size - radius)
        return dx * dx + dy * dy <= radius * radius
    return True


def _pick_glyph_char(source_id: str, label: str) -> str:
    for candidate in (label, source_id):
        for ch in candidate.upper():
            if ch in GLYPH_5X7:
                return ch
    return "*"


def generate_badge_png(
    source_id: str,
    label: str = "",
    *,
    accent_rgb: tuple[int, int, int] | None = None,
    bitmap: tuple[str, ...] | None = None,
) -> bytes:
    """Generate a deterministic 32x32 dark rounded bordered PNG badge (no Pillow)."""
    size = 32
    radius = 6
    border = 2

    if accent_rgb is None:
        digest = hashlib.sha256(source_id.encode("utf-8")).digest()
        accent_rgb = BADGE_ACCENT_PALETTE[digest[0] % len(BADGE_ACCENT_PALETTE)]

    glyph = bitmap if bitmap is not None else GLYPH_5X7[_pick_glyph_char(source_id, label)]
    glyph_h = len(glyph)
    glyph_w = len(glyph[0]) if glyph_h else 0
    scale = 2
    ox = (size - glyph_w * scale) // 2
    oy = (size - glyph_h * scale) // 2

    accent_rgba = bytes((*accent_rgb, 255))
    surface_rgba = bytes((*SURFACE_RGB, 255))
    transparent_rgba = b"\x00\x00\x00\x00"

    rows: list[bytes] = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            if not _inside_rounded_rect(x, y, size, radius):
                row.extend(transparent_rgba)
                continue

            is_border = (
                x < border
                or x >= size - border
                or y < border
                or y >= size - border
                or not _inside_rounded_rect(
                    x - border, y - border, size - 2 * border, max(1, radius - border)
                )
            )
            if is_border:
                row.extend(accent_rgba)
                continue

            gx = (x - ox) // scale
            gy = (y - oy) // scale
            if (
                0 <= gx < glyph_w
                and 0 <= gy < glyph_h
                and x >= ox
                and y >= oy
                and glyph[gy][gx] == "1"
            ):
                row.extend(accent_rgba)
            else:
                row.extend(surface_rgba)
        rows.append(bytes(row))

    png_bytes = _encode_rgba_png(size, size, rows)
    if not is_valid_png(png_bytes):
        raise RuntimeError(f"Generated invalid fallback PNG for {source_id!r}")
    return png_bytes


def extract_hostname(source: dict) -> str:
    """Resolve the best hostname for fetching a source's favicon."""
    site_url = str(source.get("site_url") or "").strip()
    feed_url = str(source.get("url") or "").strip()

    if site_url:
        host = (urlparse(site_url).hostname or "").strip().lower()
        if host:
            return host

    if not feed_url:
        return ""

    parsed = urlparse(feed_url)
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return ""

    if host == "api.stackexchange.com":
        site_param = parse_qs(parsed.query).get("site", [""])[0].strip().lower()
        if site_param == "superuser":
            return "superuser.com"
        if site_param == "stackoverflow":
            return "stackoverflow.com"
        if site_param:
            return f"{site_param}.stackexchange.com"
    if host == "hn.algolia.com":
        return "news.ycombinator.com"
    if host.startswith("feeds."):
        return host[len("feeds."):]

    return host


def fetch_google_favicon(
    session: requests.Session,
    hostname: str,
    timeout: float = 8.0,
) -> bytes | None:
    """Fetch 32px PNG favicon via Google's s2 favicon service."""
    if not hostname:
        return None
    try:
        response = session.get(
            GOOGLE_FAVICON_ENDPOINT,
            params={"domain": hostname, "sz": "32"},
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.RequestException:
        return None

    if response.status_code != 200:
        return None
    content = response.content
    if not is_valid_png(content):
        return None
    return content


def sync_favicons(
    sources_path: Path = DEFAULT_SOURCES_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    force: bool = False,
    timeout: float = 8.0,
) -> dict[str, int]:
    """Sync favicons for every source in sources.json plus community/default icons."""
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    if not isinstance(sources, list):
        raise ValueError(f"{sources_path} must contain a JSON array")

    output_dir.mkdir(parents=True, exist_ok=True)

    # Ensure crisp fallback default.svg exists
    default_svg_path = output_dir / "default.svg"
    if force or not default_svg_path.is_file():
        default_svg_path.write_text(DEFAULT_SVG, encoding="utf-8")

    stats = {"total": 0, "fetched": 0, "fallback": 0, "skipped": 0}
    domain_cache: dict[str, bytes | None] = {}

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "image/png,image/*;q=0.8"})

    try:
        for source in sources:
            source_id = str(source.get("id") or "").strip()
            if not source_id:
                continue
            if not SAFE_ID_RE.match(source_id):
                raise ValueError(f"Unsafe source id for filename: {source_id!r}")

            stats["total"] += 1
            dest_path = output_dir / f"{source_id}.png"
            if not force and is_valid_png_file(dest_path):
                stats["skipped"] += 1
                print(f"[skip]     {source_id}.png (already cached)")
                continue

            hostname = extract_hostname(source)
            if hostname not in domain_cache:
                domain_cache[hostname] = fetch_google_favicon(session, hostname, timeout=timeout)

            png_bytes = domain_cache[hostname]
            if png_bytes is not None:
                dest_path.write_bytes(png_bytes)
                stats["fetched"] += 1
                print(f"[fetched]  {source_id}.png <- {hostname} ({len(png_bytes)} bytes)")
            else:
                badge_bytes = generate_badge_png(source_id, str(source.get("name") or ""))
                dest_path.write_bytes(badge_bytes)
                stats["fallback"] += 1
                print(
                    f"[fallback] {source_id}.png <- generated badge "
                    f"(host={hostname or 'none'}, {len(badge_bytes)} bytes)"
                )

        # Ensure community.png exists for community-submitted tips (source.id == "community")
        community_path = output_dir / "community.png"
        if not force and is_valid_png_file(community_path):
            print("[skip]     community.png (already cached)")
        else:
            community_bytes = generate_badge_png(
                "community",
                "Community",
                accent_rgb=(255, 181, 71),
                bitmap=COMMUNITY_GLYPH_7X7,
            )
            community_path.write_bytes(community_bytes)
            print(f"[badge]    community.png ({len(community_bytes)} bytes)")
    finally:
        session.close()

    return stats


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="Download and cache local PNG favicons for all configured sources."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download/regenerate existing favicon files instead of skipping them.",
    )
    parser.add_argument(
        "--sources",
        type=Path,
        default=DEFAULT_SOURCES_PATH,
        help="Path to sources.json (default: config/sources.json).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Destination directory for cached favicons (default: public/favicons).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=8.0,
        help="HTTP request timeout in seconds (default: 8.0).",
    )
    args = parser.parse_args(argv)

    stats = sync_favicons(
        sources_path=args.sources,
        output_dir=args.output_dir,
        force=args.force,
        timeout=args.timeout,
    )
    print(
        f"Done: total={stats['total']} fetched={stats['fetched']} "
        f"fallback={stats['fallback']} skipped={stats['skipped']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
