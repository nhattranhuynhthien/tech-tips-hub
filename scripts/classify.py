# scripts/classify.py
import re

CATS = {
    "android":  ["android", "pixel", "galaxy", "one ui", "adb", "apk", "samsung"],
    "ios":      ["ios", "iphone", "ipad", "icloud", "siri", "airpods", "airtag"],
    "windows":  ["windows", "win11", "win10", "powershell", "wsl", "registry", "regedit", "winget", "copilot+"],
    "macos":    ["macos", "macbook", "mac mini", "imac", "spotlight", "finder", "sequoia", "sonoma"],
    "linux":    ["linux", "ubuntu", "debian", "fedora", "arch", "systemd", "bash", "wayland", "distro"],
    "browser":  ["chrome", "firefox", "edge", "safari", "brave", "extension", "trình duyệt", "tab"],
    "office":   ["excel", "word", "outlook", "powerpoint", "google docs", "google sheets", "notion", "spreadsheet", "vlookup"],
    "security": ["password", "mật khẩu", "2fa", "passkey", "vpn", "malware", "privacy", "riêng tư", "phishing", "firewall"],
    "ai":       ["chatgpt", "gemini", "claude", "copilot", "llm", "prompt", "deepseek", "ollama"],
    "dev":      ["git", "docker", "vs code", "vscode", "python", "javascript", "typescript", "api", "terminal", "devops", "kubernetes"],
    "hardware": ["router", "wifi", "wi-fi", "ssd", "gpu", "pin", "battery", "bluetooth", "monitor", "ram", "cpu"],
}

PATTERNS = {
    c: re.compile(r"\b(" + "|".join(re.escape(kw) for kw in kws) + r")\b", re.IGNORECASE)
    for c, kws in CATS.items()
}

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
    Mỗi bài viết tối đa 1-2 danh mục.
    Danh mục mặc định của nguồn chỉ dùng làm dự phòng khi không khớp từ khóa nào.
    """
    fallback = fallback or []
    text = f"{title} {title} {summary}"
    scores = {c: len(p.findall(text)) for c, p in PATTERNS.items()}
    top = [c for c, s in sorted(scores.items(), key=lambda x: -x[1]) if s > 0][:max_cats]
    if top:
        return top
    return fallback[:1] if fallback else ["dev"]

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
