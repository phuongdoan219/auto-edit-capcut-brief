# Bài học áp dụng từ video Hai Giang

Nguồn: https://www.youtube.com/watch?v=ezhxedVFbrs — “AI không chỉ xuất clip sẵn nữa, nó dựng thẳng timeline CapCut | Toàn bộ quy trình”, Hai Giang, đăng 2026-10-23, dài 9:18. Đã đọc toàn bộ phụ đề tiếng Việt và đối chiếu các khung hình thao tác chính, đặc biệt phần 05:22–07:39. Phụ đề tự động có lỗi tên công cụ; mô tả video xác định công cụ ảnh là Higgsfield. Đây là đánh giá quy trình, không sao chép lời thoại, prompt hay skill tải kèm của tác giả vào repo.

## Video thực hiện việc gì

- 00:53–01:07: AI điều phối nhiều công cụ; tác giả đề nghị có bước xem lại giữa các giai đoạn.
- 01:08–01:58: chốt nội dung và nhịp cảnh; giữ thoại khi chia nhỏ shot.
- 01:58–03:14: tạo voice, rồi điều chỉnh thời gian cảnh theo file voice thực tế.
- 03:14–05:22: tạo ảnh tham chiếu và ảnh cho từng cảnh.
- 05:22–06:32: cài skill desktop, tạo project CapCut có media ban đầu, đóng CapCut rồi yêu cầu AI ghi file project. Ở khoảng 06:09 prompt trên màn hình nói ghi trực tiếp project, không dựng timeline bằng computer use.
- 06:27–06:59: xem bản preview trước khi ghi và mở lại project.
- 07:00–07:38: gặp media mất liên kết và thao tác relink.

Đây là thao tác file dự án để giữ timeline nhiều lớp chỉnh sửa được. Video không chứng minh có API/CLI lấy toàn bộ kho online hay renderer native chạy không cần app. Không suy ra chi tiết nội bộ file skill chỉ từ lời hướng dẫn.

## Đối chiếu với repo hiện tại

| Bài học | Hiện repo đã có | Áp dụng/ưu tiên còn lại |
|---|---|---|
| AI điều phối, kết quả là project editable | Có workflow, kế hoạch dựng, native builder Python ghi draft JSON | Giữ hướng này. Không chuyển sang kéo từng clip qua UI khi builder đã hỗ trợ. CLI backend mới vẫn là tích hợp riêng chưa thực hiện |
| Dùng project do đúng bản CapCut tạo | Builder dùng base project và các segment/material làm donor | Cần bước kiểm tra base có đủ loại video/audio/photo sẽ dùng, đúng timeline và phiên bản. Tutorial dùng ảnh + voice; task footage của user cần cả donor video, không áp y nguyên base chỉ có ảnh |
| Thời gian hình đi theo voice thực tế | Có transcript, source in/out, speed và kiểm tra range | Agent lập mapping frame → shot → source interval → timeline interval. Không lấy số chữ/độ dài dự kiến làm timestamp. Khoảng lặng chỉ là gợi ý, chưa chứng minh câu thoại bắt đầu/kết thúc. Với original voice đang lộ miệng, hình/tiếng cùng interval và speed; cảnh trám có thể đổi hình mà voice tiếp tục |
| Chia nhiều shot nhưng giữ thoại | Định nghĩa frame là cảnh biên tập, có thể nhiều shot/layer | Không ép một frame thành một clip hoặc mặc định mọi shot dưới 2 giây. Điều chỉnh shot trong phạm vi brief đã chốt, giữ text và element gắn đúng frame |
| Có điểm xem lại trước khi ghi | Popup xem lại/xác nhận element; build ra staging và có báo cáo | Thiếu preview tổng thể dựng từ nguồn thật trong workflow. Ưu tiên bảng mapping hoặc storyboard và preview cut/voice/layout nếu renderer thể hiện được. Proxy FFmpeg/ảnh minh họa không chứng minh native effect render. Dùng lại lần duyệt popup; không bắt user duyệt lại script/voice/source đã chốt hay thêm các vòng xác nhận hình thức |
| Ghi khi app đóng, có thể chỉnh tiếp | Có process check, backup, hash source/build, rollback, install vào đúng base | Duy trì. Khi user sửa tay trong CapCut thì lấy trạng thái project mới trước bản sửa tiếp, không ghi đè bằng bản staging cũ. Muốn tạo project độc lập cần luồng clone/registration có kiểm chứng; hiện install gắn với base đã chọn |
| Phải mở lại và kiểm tra media | Có probe/path checks, `validate_draft`, nguồn tài nguyên và cờ open/render pending | Ưu tiên xử lý native media registration/local-material IDs và đường dẫn ổn định, rồi mở/render kiểm tra thật. Không coi JSON hợp lệ hoặc preview MP4 riêng là project đã hoạt động |

## Tránh lỗi media mất liên kết

Video giải thích trường hợp của tác giả là tài nguyên mới chưa được CapCut cấp quyền đọc. Đó là tường thuật cho máy/macOS của tác giả; không kết luận mọi clip đỏ ở Windows đều là lỗi quyền.

Trước bàn giao cần phân biệt: file không tồn tại/đổi chỗ, đường dẫn sai, bản media tiền xử lý nằm trong thư mục tạm, quyền đọc thực tế, metadata đăng ký media/`local_material_id` không nhất quán, hoặc CapCut đọc timeline khác. Repo hiện chưa có quy trình sửa mọi trường hợp này. `capcut-cli register --materials` và `relink` là ứng viên tích hợp, không được báo đã nối chỉ vì đã đọc code hoặc có bridge info/lint.

Giữ source gốc theo brief. Nếu cần crop/blur/freeze hoặc tiền xử lý khác, tạo file dẫn xuất trong thư mục media ổn định thuộc work/project và lưu mapping gốc → dẫn xuất; không âm thầm đổi sang file khác. File có tồn tại chưa đủ để đảm bảo CapCut đã nhận đúng clip.

## Phạm vi áp dụng cho task của user

Giữ quy trình hai giai đoạn đã chốt: cài lần đầu tạo thư viện project/cache; edit thường ngày dùng thư viện đã lưu, không quét lại hoặc tự lấy thêm preview. Nhận kịch bản và nguồn/voice hoàn chỉnh; user chọn native text/sticker/effect theo frame trong popup.

Các phần tạo script từ đầu, ElevenLabs/TTS/clone mới, sinh ảnh/video Higgsfield, tự thêm phụ đề, fade âm thanh và dựng nhiều biến thể không thuộc yêu cầu hiện tại. Không đưa các bước này trở lại workflow chỉ vì video mẫu có chúng. Không mặc định thêm nhạc/SFX hoặc transition dày đặc; theo brief và lựa chọn user.

Không áp quy tắc tên project ASCII/không dấu cho mọi máy chỉ vì tác giả khuyên vậy. Dùng chính xác đường dẫn/ID đã xác minh, kiểm tra Unicode và hỗ trợ schema trên bản CapCut đích.

## Hướng hoàn thiện

1. Kiểm tra và chuẩn bị project/base tương thích, cộng mapping timing/source/voice rõ ràng cho từng frame.
2. Đưa phần xem lại mapping/preview tổng thể vào quy trình chọn element, phân biệt preview proxy và native render.
3. Hoàn thiện đăng ký media và kiểm chứng vòng mở → phát → lưu → mở lại trong CapCut trước khi mở rộng backend/transition mới.

Tài liệu này ghi lại bài học và phần cần làm; chưa bổ sung renderer, media registration, engine compile hay transition bằng code.
