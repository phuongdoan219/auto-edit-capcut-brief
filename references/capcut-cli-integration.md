# Tích hợp capcut-cli

Đã đối chiếu source https://github.com/phuongdoan219/capcut-cli tại commit `f3d6c753edc33a183a60f955b402302c6e5ae7d4`, package 0.31.1, MIT. Dữ liệu trích trong `assets/capcut-cli-catalogue.json` có 637 bản ghi thuộc text animation vào/ra/lặp và video/body effects. Giữ `capcut-cli-LICENSE.txt` khi phân phối dữ liệu. Không ghép danh mục JianYing tiếng Trung vào CapCut.

## Những phần dùng được

- `capcut_cli_bridge.py lookup <tên-hoặc-ID> [--category text_animation|video_effect]`: tra ID/tên/slug từ danh mục đã ghim. Đây là tham khảo có phiên bản, không chứng minh tài nguyên hiện có trên tài khoản, cache hay render được. Không bật supported chỉ vì tra được ID.
- `capcut_cli_bridge.py audit --entry <capcut-cli/dist/index.js> --project <draft-folder> --out <report.json>`: gọi Node bằng argv, chỉ dùng hai lệnh `info` và `lint`. Giữ nguyên native builder hiện tại. Report lưu output JSON/exit code để agent giải thích lỗi trước bàn giao; đọc issue cụ thể, không suy chỉ từ mã thoát. Không chạy auto-repair hoặc ghi project qua bridge này.
- `cache_catalog.py`: dùng metadata native trong toàn bộ thư mục cache được chỉ định và bảng ID trên để định danh. Đọc cả thư mục đã giải nén và ZIP tải về. Chỉ đọc các member tên cho phép, có giới hạn dung lượng, không extract ZIP hoặc thực thi script của effect. `InfoSticker` còn dùng cho font: phải có media/script sticker mới phân loại sticker; TextStyle là text effect. Không ép tài nguyên chưa phân loại thành video effect.

Ví dụ quét Windows (thay theo máy hiện tại):

```
python scripts/cache_catalog.py --library <snapshot/library.json> --state-dir <machine-state> --root <CapCut/User Data/Cache/effect> --root <CapCut/User Data/Cache/artistEffect> --report <work/cache-coverage.json>
```

Thiết lập lần đầu tự gọi cache scanner. Sau khi nhập thêm preview theo yêu cầu, chạy `workflow.py setup --refresh` để cập nhật thư viện; prepare thường ngày chỉ dùng bản đã lưu. Có hash, owner resource, ID và đường dẫn gốc. Khử trùng theo loại + resource ID + hash media; tổng packages có preview có thể lớn hơn unique previews do cùng tài nguyên có cả thư mục và ZIP. Chỉ dùng số unique để báo cáo. Các entry cache chỉ có preview, chưa có donor/recipe, vẫn chỉ xem. Gắn vào donor có thể dựng chỉ khi kiểm chứng đúng ID/đường dẫn/appearance; không ghép theo tên gần giống.

## Thiết lập CLI tùy chọn

Bridge không tự tải/chạy mã repo hoặc yêu cầu có CLI để picker hoạt động. Khi người dùng yêu cầu tích hợp, clone source vào work, xem package/scripts và mã các chức năng dùng, rồi build source đã ghim. Dùng `npm ci --ignore-scripts` và script build đã kiểm tra; giữ dependency runtime ngoài skill. Khi mang sang máy khác cần Node và bản CLI tương thích đã build, hoặc dùng riêng lookup/cache scanner không cần Node. Không lưu đường dẫn máy này vào cấu hình portable của skill.

## Phạm vi chưa giải quyết

`src/render.ts` dùng FFmpeg để dựng proxy; hiệu ứng, sticker, animation và nhiều tính năng CapCut bị bỏ qua hoặc chỉ mô phỏng. Không dùng output này làm preview native, không đổi `capcut_open_verified`/`capcut_verified` thành true. `--strict` từ chối draft không thể mô phỏng trung thực; nó không bổ sung renderer CapCut.

`catalogue` là tìm trong bảng IDs, `harvest-enums` là thu từ draft trên máy; cả hai không duyệt/lấy hết kho online CapCut. Preview chưa cache và mẫu mới vẫn cần quy trình UI trong [native-preview-workflow.md](native-preview-workflow.md). Báo riêng cache đã quét hoàn tất, kho online chưa duyệt hết và số ảnh/clip thực, không gộp ID metadata vào số mẫu có preview.

Các chức năng compile, template, silence/retake, loudness, subtitles có thể dùng cho công việc tương ứng sau khi kiểm tra draft schema/timing. Không thay builder hiện tại chỉ vì có lệnh tương tự. Cloud caption gửi audio ra ngoài nên không thuộc bridge này; voice và source vẫn theo brief người dùng.
