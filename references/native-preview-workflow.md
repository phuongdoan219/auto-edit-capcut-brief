# Thu thập preview và mở rộng thư viện từ CapCut

Chỉ thực hiện khi thiết lập thư viện lần đầu hoặc user yêu cầu cập nhật. Khi edit thường ngày, dùng thư viện đã lưu; không chạy lại quy trình này. Công việc này gồm hai luồng: bổ sung preview cho donor đã có, và duyệt kho đang có trong CapCut để thu thập mẫu chưa từng dùng. AI thực hiện thao tác, không bắt user điền manifest/evidence hay tự chụp hàng trăm mẫu.

## Chọn cách kết nối

Dùng connector/API/CLI CapCut nếu môi trường có công cụ đã xác minh được chức năng render. Không giả định `CapCut.exe --render`, không dùng CLI dựng JSON của skill như bằng chứng CapCut đã render. Nếu chưa có CLI phù hợp, dùng công cụ điều khiển Windows/macOS hiện có; đọc hướng dẫn của công cụ, chọn đúng cửa sổ CapCut và quan sát trước mỗi thao tác. Không hardcode tọa độ từ máy này sang máy khác.

`native_previews.py` là CLI quản lý queue và nhập kết quả; nó không tự điều khiển hay render CapCut. Bước `workflow.py setup` sinh `preview-jobs.json` trong machine-state; `prepare` chỉ tham chiếu hàng đợi này khi dùng thư viện đã cài. Khi user yêu cầu bổ sung preview, agent chạy các bước UI bên dưới, sau đó `setup --refresh` và prepare workspace mới để snapshot bao gồm cập nhật. Không sửa thư viện/session đang được user chọn.

## Bổ sung preview cho tài nguyên đã sử dụng

1. Đọc `preview-jobs.json`: có key, fingerprint donor, project, segment, target timerange và resource IDs. Giữ key làm liên kết; không ghép preview theo tên gần giống. Kiểu chữ hiện chỉ có ảnh minh họa gần đúng cũng vào queue.
2. Ưu tiên preview native của chính resource trong cache. Không mượn icon effect con làm ảnh của template.
3. Nếu thiếu: mở bản sao project trong project preview riêng do AI tạo bằng UI; hoặc chỉ xem player dự án gốc tại thời gian segment, không thay nội dung. Đối chiếu resource ID/cài đặt, thời gian và layer cần xem. Preview có các layer khác phải ghi `project_context`, không gọi là mẫu cô lập.
4. Với mẫu cô lập: dùng project preview riêng, nền và chữ mẫu dễ nhìn, tái hiện đúng recipe. Với effect video cần clip nền; với template nhiều ô giữ đủ ô. Thao tác qua UI, hoặc ghi draft vào bản sao đã đóng theo cơ chế cài đặt có sẵn. Không ghi trực tiếp project đang mở. Xác minh asset đã tải, không hiển thị cảnh báo thiếu nguồn/font/Pro trước khi lấy preview.
5. Lấy ảnh player cho kiểu chữ/sticker tĩnh. Với animation/template/effect, export clip ngắn từ CapCut chứa trọn vào/giữ/ra hoặc ít nhất một vòng lặp; ảnh tĩnh không hoàn tất job chuyển động. Cắt vùng player từ screenshot để lưu artifact được phép, không đưa ảnh cả desktop chứa ứng dụng khác vào preview.
6. Agent tạo evidence JSON: `{asset_key,fingerprint,method:"capcut_export"|"capcut_ui_capture",scope:"isolated"|"project_context",app_version,project?,segment_id?}`. Fingerprint lấy từ job; scope context phải khớp đúng project/segment donor. Đây là ghi chép đối chiếu của agent, không phải kiểm chứng tự động danh tính bằng pixel.
7. Nhập kết quả:

```
python scripts/native_previews.py attach --library <library.json> --state-dir <machine-state> --key <asset-key> --media <capture.png-or-export.mp4> --evidence <evidence.json>
```

Script kiểm tra identity evidence, decode media, lưu preview, hash và provenance. Lần scan tiếp theo tự ghép lại nếu donor, máy và hash còn khớp. Chụp được preview không đồng nghĩa builder đã được kiểm chứng hay toàn bộ asset đều được hỗ trợ.

## Duyệt kho CapCut ngoài những project đã có

1. Lần lượt vào Text styles/effects, Text template (bao gồm mẫu phụ đề), Text Animation In/Out/Loop, Stickers và Video effects/Body effects mà phiên bản đang có. Duyệt các danh mục hiển thị trên tài khoản. Không giả lập danh mục không xuất hiện. Không mua/gia hạn Pro.
2. Chờ mỗi trang/đợt tải xong, chụp bảng mẫu; agent đọc tên, loại, tọa độ từng tile hoàn chỉnh. Không lấy ô loading/cắt dở. Chụp và crop ảnh thuộc CapCut; bỏ panel khác và thông báo ngoài ứng dụng. Nếu không có tên hiển thị, dùng nhãn mô tả và không khẳng định đó là tên gốc. Resource ID không biết thì bỏ trống, không đoán từ tên/ảnh.
3. Tạo manifest nội bộ: `{app_version,panel,items:[{category,label,box:[x,y,width,height],resource_id?}]}`. Nhập:

```
python scripts/native_previews.py catalog --library <library.json> --state-dir <machine-state> --sheet <native-gallery.png> --manifest <tiles.json>
```

Mẫu xuất hiện trong thư viện với `origin=capcut_catalog`, `preview_kind=capcut_catalog_thumbnail`. Chỉ có tile thì **chỉ xem**; `supported=false`. Không suy ra recipe/font/animation từ screenshot.
4. Với mẫu cần dùng: chọn/ap dụng nó trong project preview riêng qua UI, chờ CapCut tải resource rồi lưu. Quét lại project đó để thu được closure native, đúng resource IDs và dependencies. Gắn thumbnail vào donor chỉ sau khi đối chiếu identity. Lấy clip preview theo bước trên. Khi builder hỗ trợ và đủ tài nguyên, donor mới chọn được để dựng.
5. Cuộn lấy các đợt kế tiếp, duyệt danh mục khác và lưu checkpoint tại work folder: panel/category/filter/scroll position, số tile mới, lỗi và lý do dừng. Hai lần tải/cuộn không có mục mới chỉ xác nhận hết phần hiện đang tải được của danh mục đó. Lỗi mạng, login, mục không truy cập được hoặc giới hạn công cụ phải ghi `partial`, không báo quét hết.

## Mở lại picker và báo cáo

Sau đợt bổ sung thư viện theo yêu cầu, chạy `workflow.py setup --refresh` để ghép registry `native-previews.json`/`native-catalog.json`, rồi prepare workspace mới. Prepare thường ngày chỉ đọc library.json đã lưu, không scan/merge registry lại. Tài nguyên cũ còn dùng được giữ preview; donor thay đổi cần lấy lại. Queue giữ các job thiếu clip ngay cả khi đã có ảnh tĩnh.

Nêu rõ: bao nhiêu mẫu từ project, bao nhiêu mẫu từ bảng CapCut, bao nhiêu ảnh/clip native đã nhập, bao nhiêu mục chỉ xem, bao nhiêu job còn thiếu và phần catalog chưa duyệt. Không hứa toàn bộ kho online; nội dung phụ thuộc phiên bản, region, tài khoản và tải theo cuộn. Không upload ảnh/video/cache dự án người dùng lên GitHub; chỉ commit code và tài liệu skill.
