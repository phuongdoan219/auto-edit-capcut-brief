# Quét thư viện và chọn element

`library_scan.py ensure --state-dir <dir>` tìm root thông thường Windows/macOS và `currentCustomDraftPath` trong cấu hình CapCut. `--root <path>` lặp lại cho root khác. Chỉ đọc project; bỏ backup/cache/symlink; xử lý từng timeline và gộp file trùng. Thư viện là `state-dir/library.json`, machine identity dựa trên host/user/root và được làm mới khi prepare. Kiểm tra summary và errors; không khẳng định quét hết nếu có project mã hóa hoặc không truy cập được.

Phân biệt text style, text effect, animation in/out/loop, text template, sticker/icon và video effect. `available` xác nhận cache tồn tại; `supported` cho biết cấu trúc native builder hiểu; cả hai chưa chứng minh render. Ưu tiên preview thật trong cache; hình minh họa chữ phải có nhãn gần đúng và mục không có preview phải ghi rõ. Asset online chưa tải hoặc chưa từng xuất hiện trong project không tự xuất hiện.

Kiểu chữ chưa có ảnh cache được dựng hình minh họa từ font và màu/nền/viền khi file font còn trên máy và có Pillow. Popup ghi rõ “ảnh minh họa gần đúng”, không phải ảnh render CapCut: bố cục, kích thước, đường viền hoặc glyph có thể khác. Text effect, animation và template vẫn dùng preview native khi có; không biến ảnh minh họa thành bằng chứng CapCut render. Nếu thiếu font, Pillow hoặc kiểu chữ phức tạp không dựng được, ghi chưa có preview thay vì bịa.

Request `capcut-selection-request/1`: `{id,title,brief_source,semantic_review_required:false,frames:[{id,dialogue,edit_notes,slots:[...]}]}`. Slot `{id,role,label,text?,requirement?,required,categories}`. Role `text` categories gồm `text_style,text_effect,text_animation,text_template`; `sticker` hoặc `icon` dùng `sticker`; `video_effect` dùng `video_effect`. Một slot cho mỗi element được brief yêu cầu. Text là nội dung chính xác; giữ chỉ dẫn effect/layout trong requirement, không đưa chỉ dẫn vào text.

Popup localhost hiển thị từng frame, gallery có tìm kiếm/phân trang, preview cache khi có và nguồn. Chưa chọn sẵn. Text chọn template hoặc style + effect + animation; template giữ các thành phần gốc, chưa phối thêm thành phần ngoài. User có thể bỏ qua slot optional, nhưng slot required cần chọn. Chỉ review -> xác nhận mới lưu lựa chọn; đóng/hủy không xác nhận. Server bind 127.0.0.1, có token, không ghi project hay tải asset online.

Session gắn hash request/library và machine identity. `selection_plan.py` từ chối session pending/stale hoặc lựa chọn thiếu/khác loại, giữ nguyên source/voice/music. Template nhiều text material cần map đủ `text_slots` theo original material ID; nếu chưa rõ ý nghĩa slot, làm rõ trước khi dựng.

Plan chưa có asset trang trí: mọi segment text/sticker/video_effect có `slot_id` khớp request. Segment video có `segment_id` khi dùng clip effect; effect segment có `target_segment` tương ứng và thời gian nằm trong clip. Track effect dùng native donor; asset không có dependency hoặc cấu trúc chưa hỗ trợ không được tự bịa/âm thầm bỏ qua.

`workflow.py prepare` snapshot request/library theo video; `workflow.py run` khởi động popup, chờ xác nhận và build khi plan/base sẵn sàng. Chọn trong popup không tự sửa CapCut. Ghi project cần CapCut đóng, sau đó `resume --install --confirmed-closed`. Nếu chưa có plan/base, trạng thái là `choices_confirmed`; AI hoàn thiện timing, cập nhật plan/base trong workflow state rồi resume. Không tự render khi thiếu source.
