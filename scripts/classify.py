# scripts/classify.py
import re

CATS = {
    "android":  ["android", "pixel", "google pixel", "galaxy", "samsung galaxy", "one ui", "adb", "apk", "play store"],
    "ios":      ["ios", "iphone", "ipad", "icloud", "siri", "airpods", "airtag", "ios 18", "ios 17"],
    "windows":  ["windows", "windows 11", "windows 10", "win11", "win10", "microsoft", "powershell", "wsl", "registry", "regedit", "winget", "copilot+", "powertoys", "bsod"],
    "macos":    ["macos", "macbook", "mac mini", "imac", "apple", "spotlight", "finder", "sequoia", "sonoma", "homebrew"],
    "linux":    ["linux", "ubuntu", "debian", "fedora", "arch", "systemd", "bash", "wayland", "distro", "kernel", "foss", "open source", "open-source", "gnome", "kde"],
    "browser":  ["chrome", "firefox", "edge", "safari", "brave", "extension", "trình duyệt", "tab"],
    "office":   ["excel", "word", "outlook", "powerpoint", "google docs", "google sheets", "notion", "spreadsheet", "vlookup", "văn phòng"],
    "security": ["bảo mật", "mã độc", "hacker", "lỗ hổng", "cve", "ransomware", "password", "mật khẩu", "2fa", "passkey", "vpn", "malware", "privacy", "riêng tư", "phishing", "firewall"],
    "ai":       ["ai", "artificial intelligence", "trí tuệ nhân tạo", "chatgpt", "gemini", "claude", "copilot", "llm", "llms", "openai", "machine learning", "prompt", "deepseek", "ollama", "học máy"],
    "dev":      ["git", "docker", "vs code", "vscode", "python", "javascript", "typescript", "api", "terminal", "devops", "kubernetes", "lập trình", "code"],
    "hardware": ["router", "wifi", "wi-fi", "ssd", "gpu", "pin", "battery", "bluetooth", "monitor", "ram", "cpu", "phần cứng"],
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
    
    # Gỡ bỏ việc gán cứng android khi bài viết không có từ khóa liên quan
    clean_fallback = [f for f in fallback if f != "android"]
    if clean_fallback:
        return clean_fallback[:1]
    return ["general"]

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

