# Tech Tips Hub 💡

> **Web tự động tổng hợp trick và thủ thuật công nghệ từ khắp nơi trên thế giới, hiển thị song ngữ English / Tiếng Việt, luôn ghi nguồn gốc, chi phí vận hành 0đ.**

[![CI Build & Test](https://github.com/your-username/tech-tips-hub/actions/workflows/ci.yml/badge.svg)](https://github.com/your-username/tech-tips-hub/actions/workflows/ci.yml)
[![Update Tips](https://github.com/your-username/tech-tips-hub/actions/workflows/update.yml/badge.svg)](https://github.com/your-username/tech-tips-hub/actions/workflows/update.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-amber.svg)](LICENSE)
[![Operating Cost: 0đ](https://img.shields.io/badge/Chi_phí-0đ-success.svg)](https://techtipshub.pages.dev/vi/about)

---

## 📖 1. Giới thiệu

**Tech Tips Hub** là trang web aggregator tổng hợp thủ thuật thực chiến cho:
* **Hệ điều hành:** Windows, macOS, Linux, Android, iOS
* **Công cụ làm việc:** Trình duyệt web, ứng dụng văn phòng (Excel, Docs, Sheets, Notion)
* **Kỹ thuật & An toàn:** Bảo mật & Quyền riêng tư, Công cụ AI (Prompt, ChatGPT, Claude, Ollama), Lập trình & DevOps, Phần cứng & Mạng.

### 5 Nguyên tắc cốt lõi:
1. **0đ tuyệt đối:** Hoạt động hoàn toàn trên các tầng miễn phí (Cloudflare Pages, GitHub Actions, Git storage). Không cần thẻ tín dụng.
2. **Hợp pháp (Fair Use):** Chỉ lưu tiêu đề chuẩn hóa, tóm tắt ngắn (dưới 350 ký tự) và đường link trực tiếp về bài gốc. Không bao giờ cào toàn bộ nội dung.
3. **Tôn trọng bản quyền:** Luôn ghi rõ tên nguồn, favicon, tác giả và tuân thủ `robots.txt`.
4. **Tĩnh trước, động sau:** Sinh mã tĩnh (SSG) bằng Astro để đạt tốc độ tải cực nhanh (&lt; 1s), bảo mật cao, không lo sập database.
5. **Chất lượng hơn số lượng:** Lọc trùng lặp tiêu đề, loại bỏ tin quảng cáo/deal/giảm giá bằng blocklist, chấm điểm thuật toán trước khi đăng.

---

## ✨ 2. Tính năng nổi bật

* 🌐 **Song ngữ hoàn chỉnh (VI / EN):** Chuyển đổi ngôn ngữ mượt mà giữa `/vi` và `/en` giữ nguyên đường dẫn hiện tại.
* ⚡ **Tìm kiếm tức thì (Instant Client Search):** Tìm kiếm toàn văn phía client qua phím tắt `/` hoặc `Ctrl + K`.
* 🌙 **Dark mode & Light mode:** Thiết kế riêng theo phong cách *"Sổ tay thủ thuật của dân công nghệ"*, sử dụng CSS Variables, đạt chuẩn tương phản WCAG AA, không chớp trắng khi tải trang.
* 🌟 **Trick of the Day:** Tự động chọn lọc thủ thuật hay nhất trong ngày đưa lên vị trí nổi bật.
* 🔖 **Lưu bài xem sau (Bookmarks) & Đã đọc:** Lưu trữ cục bộ an toàn trong `localStorage` không cần đăng nhập hay backend.
* 🏷️ **Phím tắt trực quan:** Tự động định dạng các tổ hợp phím như `<kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>T</kbd>`.
* 📡 **Nguồn cấp RSS riêng:** Cung cấp RSS 2.0 đầy đủ tại `/vi/rss.xml`, `/en/rss.xml` và `/rss.xml`.
* 📋 **Minh bạch & Gỡ bài:** Trang danh sách toàn bộ nguồn tin theo dõi (`/sources`), chính sách bản quyền (`/copyright`) và bảo mật không cookie (`/privacy`).

---

## 🏗️ 3. Cấu trúc thư mục

```text
tech-tips-hub/
├── .github/workflows/
│   ├── update.yml              # Cronjob tự động thu thập mỗi 4 giờ
│   └── ci.yml                  # Kiểm tra cú pháp script & build Astro
├── config/
│   ├── sources.yml             # Danh mục 15+ nguồn RSS/API uy tín
│   ├── categories.yml          # Định nghĩa 11 danh mục và từ khóa lọc
│   └── blocklist.yml           # Từ khóa quảng cáo, deal, tên miền bị chặn
├── scripts/
│   ├── fetch.py                # Thu thập dữ liệu từ các nguồn RSS
│   ├── dedupe.py               # Chuẩn hóa URL, lọc trùng lặp & kiểm tra blocklist
│   ├── score.py                # Chấm điểm độ hữu ích và phân loại tags
│   ├── translate.py            # Dịch song ngữ (Gemini API + Offline rules) có cache
│   ├── run_pipeline.py         # Điều phối toàn bộ quy trình thu thập
│   └── requirements.txt        # Thư viện Python
├── data/
│   ├── index.json              # Kho dữ liệu thủ thuật đã chuẩn hóa
│   └── cache/translations.json # Bộ nhớ cache bản dịch
├── src/
│   ├── i18n/                   # Từ điển giao diện EN / VI
│   │   ├── en.json
│   │   └── vi.json
│   ├── layouts/
│   │   └── Layout.astro        # Layout chính (Header, Footer, Theme, Meta)
│   ├── components/
│   │   ├── TipCard.astro       # Thẻ hiển thị thủ thuật
│   │   ├── TrickOfTheDay.astro # Thẻ thủ thuật nổi bật trong ngày
│   │   └── SearchModal.astro   # Hộp tìm kiếm tức thì
│   ├── styles/
│   │   └── global.css          # Design tokens, màu giấy ấm, WCAG AA
│   └── pages/
│       ├── index.astro         # Tự động nhận diện ngôn ngữ trình duyệt
│       ├── 404.astro           # Trang lỗi 404 có cá tính
│       ├── rss.xml.ts          # RSS XML chuẩn
│       ├── api/tips.json.ts    # JSON Endpoint phục vụ tìm kiếm nhanh
│       ├── vi/                 # Toàn bộ trang tiếng Việt
│       └── en/                 # Toàn bộ trang tiếng Anh
├── public/
│   ├── favicon.svg             # Favicon thủ công nhận diện ở cỡ 16px
│   ├── robots.txt              # Chỉ thị bọ tìm kiếm
│   └── js/actions.js           # Xử lý bookmark & trạng thái đã xem
├── astro.config.mjs
├── tailwind.config.mjs
├── package.json
└── README.md
```

---

## 🚀 4. Hướng dẫn cài đặt và chạy thử cục bộ

### Yêu cầu môi trường
* **Node.js**: v18.0 trở lên (khuyến nghị v20+)
* **Python**: 3.10 trở lên

### Bước 1: Cài đặt dependencies
```bash
# 1. Cài đặt các gói giao diện Astro
npm install

# 2. Cài đặt các gói Python
python -m venv .venv
# Trên Windows:
.\.venv\Scripts\activate
# Trên Linux/macOS:
source .venv/bin/activate

pip install -r scripts/requirements.txt
```

### Bước 2: Chạy tiến trình thu thập dữ liệu (Tùy chọn nếu muốn lấy bài mới)
```bash
python scripts/run_pipeline.py
```
> *(Tùy chọn)* Nếu có Google Gemini API Key, bạn có thể thiết lập:
> ```bash
> export GEMINI_API_KEY="your-gemini-key"  # hoặc $env:GEMINI_API_KEY="your-key"
> ```
> Nếu không có key, hệ thống vẫn tự động chuyển sang bộ dịch quy tắc ngoại tuyến mà không tốn 1 xu chi phí!

### Bước 3: Khởi chạy môi trường xem trước (Dev Server)
```bash
npm run dev
```
Truy cập trình duyệt tại: `http://localhost:4321/vi` hoặc `http://localhost:4321/en`.

### Bước 4: Đóng gói bản Static Site (Production Build)
```bash
npm run build
```
Thư mục `dist/` tạo ra sẵn sàng triển khai thẳng lên Cloudflare Pages hoặc GitHub Pages!

---

## ⚙️ 5. Thêm nguồn tin mới

Chỉ cần thêm vào file `config/sources.yml`:

```yaml
- id: ten_nguon
  name: Tên Trang Tin
  url: https://example.com/feed/
  site_url: https://example.com
  type: rss
  lang: en # hoặc vi
  weight: 1.1 # Trọng số tin cậy 0.5 - 1.5
  categories: [windows, dev]
  description: Mô tả ngắn gọn về nguồn tin
```

Sau đó chạy lại `python scripts/run_pipeline.py`, bài viết sẽ tự động xuất hiện trên web.

---

## 🛡️ 6. Bản quyền và Pháp lý

* Mã nguồn được phát hành theo giấy phép **MIT License**.
* Toàn bộ nội dung bài viết và nhãn hiệu thuộc về các tác giả và nhà xuất bản gốc.
* Tech Tips Hub chỉ phục vụ mục đích học hỏi, dẫn link và tra cứu kiến thức công nghệ.

---

*Xây dựng với niềm đam mê dành cho cộng đồng công nghệ.*
