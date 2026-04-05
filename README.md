# Livestream Restreamer Extension for TubeCLI

Tự động tạo sự kiện livestream trên YouTube, lấy stream key và phát lại luồng (Restream) từ nền tảng khác như Douyin, TikTok thông qua các AI agents.

## 🌟 Tính năng chính
- Tự động tạo broadcast và stream key RTMP qua YouTube API.
- Link trực tiếp stream key cho AI Agents tự động phát video.
- Giám sát sự kiện livestream (testing/live/complete).

## 🚀 Hướng dẫn cài đặt

Hệ thống yêu cầu phải cài đặt core [TubeCLI](https://github.com/tubecreate/tubecli) trước.

### Cách 1: Cài đặt trực tiếp (Khuyên dùng)
Bạn có thể tự động cài thông qua CLI có sẵn:
`ash
tubecli ext install https://github.com/tubecreate/tubecli-ext-livestream.git
`

### Cách 2: Clone thủ công dành cho Developer
`ash
# 1. Di chuyển vào thư mục lưu trữ
cd path/to/tubecli/data/extensions_external

# 2. Clone repository bằng git
git clone https://github.com/tubecreate/tubecli-ext-livestream.git livestream

# 3. Kích hoạt extension để nạp core
tubecli ext enable livestream
`

## 📖 Cách hoạt động
Gọi lệnh từ AI Agent (hoặc Telegram chatbot) như 	ạo phiên live. extension sẽ tự gọi API setup channel và trả Stream Key về cho Tools / FFmpeg để Restream.

---
*Phát triển bởi đội ngũ TubeCreate.*
