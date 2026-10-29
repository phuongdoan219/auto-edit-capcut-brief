# Brief, voice và edit plan

## Nhận MarkFlow

Đọc `dailyScriptId` trong URL; lấy đúng daily script qua connector, không nhầm shooting script. Dữ liệu thực tế dùng `items[].voice` là thoại, `items[].source` là ghi chú dựng đa dòng chứa source/layout/text/voice, không có các cột text/layout riêng. Preserve nguồn rồi chuẩn hóa; không ghi lại MarkFlow chỉ vì đang dựng.

`brief_io.py` chỉ chuẩn hóa và kiểm tra đường dẫn. Nó không hiểu toàn bộ ngữ nghĩa bố cục. Agent đọc ghi chú để tách shot/layer/text; giữ mọi yêu cầu, ghi trường nào chưa giải được. Các lỗi font như `Monstserrat` có thể hiểu là Montserrat theo ngữ cảnh nhưng kiểm tra font thực tế. Sửa lỗi chữ trong text quảng cáo chỉ khi người dùng cho phép; nội dung không được tự đổi thông điệp.

Các tên như `IMG\_[2394.MOV](http://2394.MOV)` là một tên file bị Markdown làm hỏng: khôi phục `IMG_2394.MOV`, không truy cập domain `2394.MOV`. Kiểm tra đường dẫn chuẩn hóa tồn tại. `.crdownload` trong brief được báo là tải chưa hoàn tất; không mặc định đó là MP4 hợp lệ dù có file.

## Voice và timing

Mỗi đoạn thoại cần `mode`, `file`, `source_in/out`, `speed` và mapping sang timeline. Không có mốc thì transcribe file có sẵn:

```powershell
python scripts/transcribe_source.py --input "D:/media/voice.mp3" --out "work/video/voice.words.json" --lang vi --model small
```

Requires `faster-whisper`; first model use can download weights. Respect an existing local model and offline preference. Probe scripts and compiler only need Python standard library + ffprobe; they do not auto-install packages.

Tìm đúng câu từ transcript rồi kiểm tra audio biên: bỏ chỗ thừa, không cắt phụ âm/cuối từ. Các câu lặp lại trong source phải được đối chiếu hình/take. Không chắc đoạn nào thì hỏi một lần hoặc đánh dấu unresolved; không đoán timestamps.

Khi giữ voice chuyên gia xuyên cảnh trám: tách audio từ đoạn source vào track riêng, tắt tiếng các visual clips để tránh tiếng đôi. Nếu chuyên gia lộ miệng, visual và original voice phải dùng cùng source interval/speed. Clone có sẵn thì ghép file clone; chỉ lip sync khi user yêu cầu và có workflow riêng.

Mốc source s → mốc output: `timeline_start + (s - source_start)/speed`. Với 10 giây source ở 1.3×, output dài 10/1.3 giây. Nếu đã render atempo 1.3 ra file mới, plan dùng speed=1.0.

## Schema plan/1

Đơn vị time: giây; compiler snap theo fps. Volume là hệ số tuyến tính (`1` nguyên mức, `0` mute), không phải dB. Layer lớn vẽ lên trên; khai báo rõ mọi layer. Các segment video ở layer thấp nhất phải phủ đủ duration, tránh frame đen ngoài ý muốn.

Ví dụ cấu trúc (agent thay source/asset bằng dữ liệu đã xác minh; người dùng không phải nhập JSON):

```json
{
  "title":"Demo",
  "brief_source":"MarkFlow daily script id",
  "canvas":{"width":1080,"height":1920},
  "fps":30,
  "duration":12,
  "segments":[
    {"frame":1,"kind":"video","file":"D:/media/expert.mp4","source_start":30,"start":0,"duration":12,"speed":1,"volume":0,"layer":0},
    {"frame":1,"kind":"audio","file":"D:/media/expert.mp4","source_start":30,"start":0,"duration":12,"speed":1,"volume":1,"role":"original_voice","layer":0},
    {"frame":2,"kind":"video","file":"D:/media/broll.mp4","source_start":8,"start":6,"duration":6,"volume":0,"box":[0.55,0.15,0.4,0.3],"layer":1},
    {"frame":1,"kind":"text","asset":"a-real-library-key","text":"Mẹ đồng hành cùng con","start":0.5,"duration":2,"layer":3},
    {"frame":2,"kind":"sticker","asset":"another-real-library-key","start":6.5,"duration":2.5,"layer":4}
  ]
}
```

`box` = `[left,top,width,height]` theo tỷ lệ canvas, crop center để fill vùng. Native geometry phải kiểm tra trên app đích vì CapCut có thể diễn giải crop/scale khác theo version. Chia ba người: ba visual segments cùng khoảng thời gian, layer khác nhau, box `[0,0,1,0.3333]`, `[0,0.3333,1,0.3334]`, `[0,0.6667,1,0.3333]`. Không hứa bố cục đúng trước khi xem trên CapCut.

`transform` cho text/sticker ghi đè các trường native `scale`, `transform`, `rotation`, `flip`, `alpha`. Đây là đơn vị CapCut, không phải pixel: vị trí x/y nằm quanh -1..1, y dương hướng lên. Giữ donor nếu không chắc, kiểm tra vị trí/tràn chữ trong app. `keyframes` là cấu trúc common_keyframes native đã biết, với `time_offset` tính microsecond trong clip; compiler kiểm tra mốc nằm trong clip. `flip_horizontal` có cho visuals.

Text uniform một material dùng `text`. Nhiều material trong template: dùng `text_slots:[{"slot":"original-text-material-id","text":"Nội dung"}]` với slot ID lấy từ catalog, điền đủ, không dựa vào thứ tự materials. Rich text nhiều styles cần `style_ranges` cho từng style dưới dạng `[start,end]` theo UTF-16 của chuỗi mới. Nếu không có mapping thì chọn donor uniform hoặc thao tác trong CapCut, không kéo toàn bộ styles lên một range làm mất định dạng.

Trường không hỗ trợ bị compiler từ chối. Không truyền `blur`, `freeze`, `brightness` rồi coi đã áp dụng. Cần tiền xử lý bằng FFmpeg vào media mới để giữ trim/crop/blur đơn giản, hoặc tạo effect trong CapCut và phát triển donor hỗ trợ tương ứng. File tiền xử lý là asset đã bake: nói rõ phần đó không còn là effect editable. Freeze: xuất đúng frame thành ảnh rồi dùng photo donor. Background blur: tiền xử lý thành full-canvas background riêng, visual rõ ở track trên. Không đổi toàn bộ pipeline sang HyperFrames khi mục tiêu là native CapCut.

## Mức kiểm chứng

1. `brief_normalized`: đọc đủ cảnh, giữ nguồn và yêu cầu, báo thiếu file.
2. `json_compiled`: cấu trúc, source intervals, ID references và dependency tồn tại; chưa chứng minh hình/render.
3. `capcut_open_verified`: mở lại đúng project, chữ và effect không lỗi.
4. `capcut_render_verified`: xem bản render, soát motion, voice, timing và layout.

Ghi đúng mức đạt được. Bộ test Python chứng minh logic dữ liệu, không chứng minh CapCut đã nhận draft.
