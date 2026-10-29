# CapCut Brief Editor

Skill Codex dựng project CapCut từ brief theo từng cảnh, footage và voice có sẵn. Trên mỗi máy, skill lập thư viện từ các project local và mở popup để người dùng chọn kiểu chữ, effect, animation, template và sticker.

Thư mục skill cần được đặt trong thư mục skills của Codex, ví dụ `~/.codex/skills/auto-edit-capcut-brief`. Cần Python và FFmpeg/ffprobe; ảnh minh họa kiểu chữ cần thư viện Pillow. Tính năng dò thoại dùng faster-whisper và model phù hợp. Xem `SKILL.md` và `references/` để biết quy trình.

Ảnh kiểu chữ được tạo từ font và thông số là **minh họa gần đúng**, chưa phải bản render CapCut. Hiệu ứng thiếu trong cache, project cloud hoặc project mã hóa có thể không thu thập được. Bản dựng JSON cần mở và kiểm tra trong CapCut trước khi dùng thực tế.

Tài nguyên cache, thư viện cá nhân, media và phiên lựa chọn không được đưa vào repository.
