# scripts/classify.py
import re

CATS = {
    "android":  ["android", "pixel", "google pixel", "galaxy", "samsung", "samsung galaxy", "one ui", "adb", "apk", "play store", "xiaomi", "redmi", "鸿蒙", "安卓"],
    "ios":      ["ios", "iphone", "ipad", "icloud", "siri", "airpods", "airtag", "ios 18", "ios 17", "face id"],
    "windows":  ["windows", "windows 11", "windows 10", "win11", "win10", "microsoft", "powershell", "wsl", "registry", "regedit", "winget", "copilot+", "powertoys", "bsod", "微软"],
    "macos":    ["macos", "macbook", "mac mini", "imac", "apple", "spotlight", "finder", "sequoia", "sonoma", "homebrew", "苹果"],
    "linux":    ["linux", "ubuntu", "debian", "fedora", "arch", "systemd", "bash", "wayland", "distro", "kernel", "foss", "open source", "open-source", "gnome", "kde", "开源"],
    "browser":  ["chrome", "firefox", "edge", "safari", "brave", "extension", "trình duyệt", "tab", "bookmarks", "devtools", "浏览器"],
    "office":   ["excel", "word", "outlook", "powerpoint", "google docs", "google sheets", "notion", "spreadsheet", "vlookup", "pdf", "văn phòng", "办公"],
    "security": ["bảo mật", "mã độc", "hacker", "lỗ hổng", "cve", "ransomware", "password", "mật khẩu", "2fa", "passkey", "vpn", "malware", "privacy", "riêng tư", "phishing", "firewall", "网络安全", "隐私", "漏洞"],
    "ai":       ["ai", "artificial intelligence", "trí tuệ nhân tạo", "chatgpt", "gemini", "claude", "copilot", "llm", "llms", "openai", "machine learning", "prompt", "deepseek", "ollama", "học máy", "人工智能", "大模型", "智能体"],
    "dev":      ["git", "docker", "vs code", "vscode", "python", "javascript", "typescript", "api", "terminal", "devops", "kubernetes", "lập trình", "code", "github", "开发者", "编程", "代码"],
    "hardware": ["router", "wifi", "wi-fi", "ssd", "gpu", "pin", "battery", "bluetooth", "monitor", "ram", "cpu", "phần cứng", "显卡", "电池", "路由器", "芯片"],
}

VALID_CATEGORIES = set(CATS.keys())
CJK_RE = re.compile(r"[\u3400-\u9fff]")


def _build_cat_pattern(kws: list[str]) -> re.Pattern:
    parts = []
    for kw in sorted(kws, key=len, reverse=True):
        escaped = re.escape(kw)
        parts.append(escaped if CJK_RE.search(kw) else rf"\b{escaped}\b")
    return re.compile(r"(?:" + "|".join(parts) + r")", re.IGNORECASE)


PATTERNS = {c: _build_cat_pattern(kws) for c, kws in CATS.items()}

TAG_KEYWORDS = [
    "docker", "git", "python", "vscode", "terminal", "bash", "powershell", "registry",
    "chrome", "firefox", "edge", "safari", "vpn", "password", "2fa", "privacy",
    "excel", "notion", "chatgpt", "claude", "gemini", "wifi", "battery", "backup",
    "shortcut", "phím tắt", "tinh chỉnh", "sửa lỗi", "bảo mật"
]

TAG_PATTERNS = {
    tag: re.compile(r"\b" + re.escape(tag) + r"\b", re.IGNORECASE)
    for tag in TAG_KEYWORDS
}


def classify(title: str, summary: str, fallback: list[str] = None, max_cats: int = 2) -> list[str]:
    """
    Phân loại danh mục dựa trên nội dung tiêu đề và tóm tắt.
    Tiêu đề được nhân đôi trọng số.
    Mỗi bài viết tối đa 1-2 danh mục hợp lệ trong config/categories.yml.
    """
    fallback = fallback or []
    text = f"{title} {title} {summary}"
    scores = {c: len(p.findall(text)) for c, p in PATTERNS.items()}
    top = [c for c, s in sorted(scores.items(), key=lambda x: -x[1]) if s > 0][:max_cats]
    if top:
        return top

    valid_fallback = [f for f in fallback if f in VALID_CATEGORIES]
    if len(valid_fallback) == 1:
        return valid_fallback
    if len(valid_fallback) > 1:
        non_android = [f for f in valid_fallback if f != "android"]
        return [non_android[0] if non_android else valid_fallback[0]]

    return ["browser"]


def extract_tags(title: str, summary: str, max_tags: int = 4) -> list[str]:
    """Trích xuất tags cụ thể từ tiêu đề và tóm tắt."""
    text = f"{title} {summary}"
    found = []
    for tag, pattern in TAG_PATTERNS.items():
        if pattern.search(text):
            found.append(tag.lower())
            if len(found) >= max_tags:
                break
    return found
