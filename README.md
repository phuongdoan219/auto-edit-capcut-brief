# CapCut Brief Editor

Skill Codex dựng project CapCut từ brief từng cảnh, footage và voice có sẵn; mở popup tiếng Anh chỉ để user chọn **Text Effects** và **Stickers**.

## Cài đặt và tạo thư viện lần đầu

Cần Python; cài Pillow để thu preview ảnh trong cache và tạo ảnh minh họa kiểu chữ. FFmpeg/ffprobe phục vụ kiểm tra media/dựng, faster-whisper phục vụ dò thoại khi cần.

Sau khi clone/tải repo, chạy tại thư mục repo:

```powershell
python install.py
```

Installer copy skill vào `~/.codex/skills/auto-edit-capcut-brief` và tự quét project/cache CapCut, tạo thư viện cá nhân trên máy. Nếu chạy ngay trong thư mục skill đã cài, nó chỉ thiết lập thư viện còn thiếu. Có thể chỉ rõ đường dẫn project không ở vị trí mặc định:

```powershell
python install.py --root "D:/CapCutProjects"
```

Nếu cài bằng cách copy/clone thủ công hay trình cài skill khác, thao tác copy không tự chạy mã. AI chạy `python scripts/workflow.py setup` sau cài; nếu chưa chạy, lần sử dụng đầu tiên tự thiết lập khi chưa có thư viện. Không cần gửi kịch bản để chạy setup.

## Sử dụng thường ngày

Gọi skill với kịch bản và source/voice của video. Skill dùng thư viện đã lưu, lập kế hoạch dựng, mở popup lựa chọn theo từng cảnh rồi build theo lựa chọn được xác nhận. Không quét lại project/cache hoặc duyệt kho CapCut ở mỗi lần edit. Machine-state mặc định trên Windows: `%LOCALAPPDATA%/CodexCapCutBrief`; thư viện được kiểm tra theo máy, không dùng nhầm bản mang từ máy khác.

Trong popup, chỉ chọn **Text Effect** hoặc **Sticker** cho phần được kịch bản yêu cầu. Text Effect dùng font đi kèm donor, không bắt chọn font, animation hay template riêng. Thanh dưới cùng luôn có **Choose Missing Items**, **Review All** và **Confirm & Continue**. Lựa chọn được lưu nháp trong trình duyệt theo phiên; chỉ khi bạn bấm xác nhận mới gửi cho bước dựng. Ngôn ngữ giao diện là tiếng Anh; nội dung video giữ nguyên theo brief.

Mỗi scene có nút **Add Sticker (Optional)** ở phía trên khi brief chưa yêu cầu sticker. Bạn có thể thêm, đổi hoặc bỏ sticker; để trống không chặn xác nhận. Sticker được yêu cầu trong brief vẫn cần chọn theo yêu cầu đó.

Gallery chỉ hiển thị các mục có preview xem được. Mục thiếu hoặc lỗi preview được ẩn; nếu có preview dự phòng, popup tự thử trước khi ẩn mục đó.

## Cập nhật thư viện khi muốn

Khi đã thêm project/tải tài nguyên mới và muốn đưa vào thư viện, yêu cầu AI làm mới hoặc chạy trong thư mục skill:

```powershell
python scripts/workflow.py setup --refresh
```

Lệnh setup không có `--refresh` chỉ dùng lại thư viện hiện có. Root tùy chỉnh đã thiết lập được giữ khi refresh; muốn đổi root thì truyền `--root`. Các phiên chọn của video cũ giữ snapshot riêng, không bị cập nhật ngầm.

Setup báo project lỗi/mã hóa và preview còn thiếu; không có project đọc được thì báo rõ để chỉ đúng root, không đánh dấu cài thư viện thành công. Thiếu Pillow sẽ hạn chế thu preview ảnh; cài dependency rồi yêu cầu refresh. Thư viện không đại diện toàn bộ kho online. Preview qua giao diện CapCut là đợt bổ sung có AI điều phối, không phải tác vụ nền tự render hết.

Ảnh kiểu chữ tạo từ font/thông số là **minh họa gần đúng**, chưa phải render CapCut. Bản dựng JSON cần mở và kiểm tra trong CapCut. Tài nguyên cache, thư viện cá nhân, media và phiên lựa chọn không đưa vào Git. Xem `SKILL.md` và `references/` để biết chi tiết.
