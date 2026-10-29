# Đối chiếu khả năng dựng video với capcut-cli

Yêu cầu: bổ sung khả năng AI dựng video từ brief từng cảnh, nguồn và voice có sẵn; không giới hạn ở thư viện preview. Đối chiếu source capcut-cli 0.31.1 tại `f3d6c753edc33a183a60f955b402302c6e5ae7d4` với skill này tại `442365a`. Đây là đánh giá tích hợp, không phải thông báo mọi tính năng dưới đây đã được kết nối.

## Phạm vi đã được người dùng làm rõ

Task edit hiện tại chưa cần ba phần: phụ đề tự động theo voice, fade âm thanh và dựng nhiều phiên bản. Phần xem xét tích hợp tiếp tập trung vào `compile` dựng timeline và transition. Bảng dưới vẫn giữ để tham khảo khả năng của hai repo; những phần chưa cần không phải backlog đã được yêu cầu triển khai. Text từng frame theo brief, transcript để dò đoạn source/voice và điều chỉnh mute/volume/speed vẫn thuộc luồng dựng hiện có.

## Kết luận kiến trúc

Skill này giữ vai trò giải brief MarkFlow/Sheets, xác định cảnh/layer/thoại/source, chọn đúng đoạn voice, yêu cầu người dùng chọn element và giữ các lựa chọn đã xác nhận. capcut-cli có thể bổ sung backend dựng/chỉnh timeline và công cụ phân tích nguồn. Không chạy hai bộ ghi song song vào cùng draft.

Luồng đích: brief → scene plan đã giải timing → user chọn native element → backend có hỗ trợ đúng các tính năng trong plan → kiểm tra source/media/schema → mở/render trong CapCut → bàn giao draft editable.

## Những phần phù hợp

| Mảng | Skill hiện tại | Bổ sung từ capcut-cli | Ưu tiên và điều kiện |
|---|---|---|---|
| Dựng draft từ scene plan | Compiler Python dựng video/photo/audio/text/sticker/effect dựa trên donor; có trim/speed/layer/crop và kiểm tra range | `init`, `compile`, `compile --into`, `--check/--plan`, template seeding, tham chiếu ref cho operations | Cao. Thêm backend tùy chọn cho những plan chuyển đổi đầy đủ được. Không bỏ silently `box`, slot native, multi-slot template hoặc layer. Không cần nối hàng chục lệnh `add-*` riêng lẻ |
| Phụ đề từ voice và kịch bản | Có transcript theo từ, agent dò đoạn và dựng text; chưa có pipeline tạo subtitle track hoàn chỉnh | `caption --words --script`, chia cue/karaoke, import/export SRT/ASS, styleRef/preset | Chưa cần trong task hiện tại. Khi được yêu cầu mới xem xét dùng timestamps đã có và đúng wording kịch bản. Alignment có thể nội suy từ thiếu: báo inserted/substituted/match ratio, rà trước khi dùng; không biến thời gian nội suy thành mốc cắt đã xác minh |
| Âm thanh | Có original/provided clone, tách voice, mute clip, speed và volume; chưa có fade hoặc đo loudness tích hợp | `audio-fade`, `loudness` đo/gợi ý gain theo phần media phát trên timeline | Fade âm thanh chưa cần trong task hiện tại. Đo loudness là khả năng tham khảo chưa được yêu cầu. Giữ nguyên file voice có sẵn. Loudness không phải tự động ducking nhạc theo voice |
| Chuyển động và xử lý hình | Có common keyframes native nếu agent cung cấp, crop/box/flip, effect native đã có donor; chưa có giao diện plan cho transition/mask/bg blur mới | `keyframe` có easing, `transition`, `mask`, `bg-blur`, `mix-mode`, `chroma`, `matting`, filter và fade | Cao theo nhu cầu cảnh. Bổ sung schema plan và tính năng backend tương ứng, kiểm tra resource/schema trên CapCut 9.7. Không coi việc lệnh tồn tại là app đã render đúng |
| Tái dùng bố cục/nhận diện | Có thư viện text/effect/sticker theo tài nguyên, chưa có scene/layout pack hoàn chỉnh có tên | `save-template/apply-template`, `make-preset/restyle`, copyTextStyle | Trung bình–cao. Dùng cho title/subtitle/CTA đã kiểm chứng; nâng thành pack nhiều layer bằng logic của skill. `saveTemplate` trong factory.ts gom primary + extras trực tiếp, chưa duyệt closure đệ quy như skill; không thay pipeline template phức tạp hiện tại |
| Dựng nhiều biến thể | Mỗi video có một workflow/request/session; chưa có bộ sinh hàng loạt từ bảng | `compile --data`, ref/operations, batch/serve, replace-media | Chưa cần trong task hiện tại. Chỉ xem xét khi người dùng yêu cầu nhiều hook/CTA/source biến thể. Mỗi bản có scene mapping và lựa chọn hợp lệ riêng; cache shared nhưng session xác nhận không dùng nhầm giữa các bản |
| Chọn đoạn từ footage dài | Agent dùng transcript và ffprobe, chưa có gợi ý scene/silence/retake | `detect-scenes`, `detect-silence`, `detect-retakes` | Trung bình. Chỉ là gợi ý cut/take. Source/timing đã gắn trong brief vẫn là yêu cầu cần giữ; retake heuristic ưu tiên take sau không thay quyết định biên tập theo ngữ nghĩa |
| Đăng ký/di chuyển media và kiểm tra bàn giao | Có probe/range/reference/hash/backup/install; chưa có quy trình media-bin registration/packaging hoàn chỉnh | `register --materials`, `relink --stage`, `replace-media`, `version`, `diagnose`, `diff`, lint | Rất cao. Tránh project mở được nhưng clip không resolve/import-bin thiếu. Phân biệt sao chép resource với chỉ sửa path; giữ exact source thay vì tự chọn file trùng tên |
| Xem thử và export | Mở/render CapCut qua UI; preview ảnh không chứng minh native render | `render` proxy FFmpeg; `export --batch` tự động UI thử nghiệm | Proxy có ích kiểm tra cut/voice/timing. `export-batch.ts` có nhánh Windows SendKeys Ctrl+E, không theo dõi export hoàn tất; không coi thành phẩm đã xong khi mới trigger. Giữ điều khiển UI có quan sát và kiểm tra file render thực |

## Hướng tích hợp phù hợp với task hiện tại

1. **Từ plan ra draft:** adapter scene plan → CLI spec có kiểm tra mất tính năng. Plan chứa native element chưa chuyển được vẫn dùng builder hiện tại. Mỗi artifact chỉ có một backend chịu trách nhiệm ghi/finalize.
2. **Transition:** hỗ trợ chuyển cảnh được yêu cầu trong brief hoặc do user chọn; kiểm tra điểm nối, thời lượng, resource và kết quả trên CapCut. Không tự thêm transition cho mọi cảnh.

Phụ đề theo voice, fade âm thanh và sản xuất nhiều phiên bản để ngoài phạm vi hiện tại. Các công cụ khác trong bảng là tham khảo, không tự mở rộng task chỉ vì CLI có chức năng tương ứng.

Không nối lệnh CLI sửa draft sau `build_report` rồi dùng nguyên hash/report cũ để install. Nếu bổ sung post-operations, phải chạy trên bản staging và validate/finalize lại report/hashes trước khi cài. `--force-write` không phải cách chữa khác schema mặc định.

## Những gì đã có và chưa có

Trước đánh giá này đã tích hợp lookup 637 ID, bridge `info/lint` và quét preview cache. Đây là phần tra cứu/kiểm tra, chưa phải backend dựng mới.

Đã kiểm tra source các module compile, factory/templates, decorators, caption/align, loudness, scenes/silence/retakes, media registration, export-batch và version/store. Đã chạy `compile --plan` với nguồn demo local: canvas 1080×1920, 30 fps, 3 tracks, 4 items, 3 operations (hai keyframe scale và audio fade), kết quả `ok=true`, `checked=true`, `write=false`. Phép thử chỉ xác nhận CLI nhận và kiểm tra được spec; chưa tạo/mở/render project và chưa kiểm chứng tiếng Việt, layout hoặc native effect trong app.

Source quan trọng:

- https://github.com/phuongdoan219/capcut-cli/blob/master/src/compile.ts
- https://github.com/phuongdoan219/capcut-cli/blob/master/src/caption.ts
- https://github.com/phuongdoan219/capcut-cli/blob/master/src/align.ts
- https://github.com/phuongdoan219/capcut-cli/blob/master/src/decorators.ts
- https://github.com/phuongdoan219/capcut-cli/blob/master/src/factory.ts
- https://github.com/phuongdoan219/capcut-cli/blob/master/src/materials-register.ts
- https://github.com/phuongdoan219/capcut-cli/blob/master/src/export-batch.ts
- https://github.com/phuongdoan219/capcut-cli/blob/master/docs/version-support.md
