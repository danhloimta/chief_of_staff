# ClassHub Engineering Chief of Staff

Repo này là nơi chạy root agent điều phối công việc kỹ thuật cho ClassHub. Anh
giao một yêu cầu ở mức nghiệp vụ; root agent đọc policy của ClassHub, phân loại
rủi ro, điều phối các role cần thiết qua Paseo, kiểm tra chuỗi bằng chứng và trả lại một
báo cáo ngắn.

## Phạm vi MVP

MVP hỗ trợ:

- chuẩn bị task contract và prompt có scope/authority rõ ràng;
- dùng ClassHub `bin/harness` làm durable record cho intake, story, decision và
  trace;
- writer làm việc trong Git worktree riêng do Chief tạo và Paseo quản lý agent;
- evidence và handoff gắn với đúng project/task/commit;
- Root khóa target branch/base trước khi giao việc; worker không được tự chọn;
- gate kiểm tra Git ancestry, file thực tế, `owns`, `does_not_own` và whitespace;
- tester độc lập chạy safe verification command trên đúng candidate, không
  dùng exit code do writer tự khai;
- reviewer độc lập đọc diff, đối chiếu spec và xác nhận từng yêu cầu;
- sau khi candidate pass, integrator fast-forward vào target branch rồi tester
  và reviewer chạy lại gate trước khi `ACCEPT`;
- root agent gửi correction cho cùng writer hoặc ghi `ACCEPT/REVISE/WAIT`;
- investigation chỉ đọc để tìm bug và trả findings, không sửa code hoặc tạo commit;
- báo cáo cho người dùng theo ngôn ngữ nghiệp vụ của ClassHub.

Root Codex vẫn là orchestration engine: nó đọc yêu cầu, lựa chọn context và gọi
Paseo. `chiefctl` cung cấp các thao tác deterministic để tránh ghép task và gate
bằng tay; nó không phải một daemon hay một bộ lập lịch độc lập.

## Khởi động

Mở Root Codex CLI trực tiếp trong repo này để Codex tự nạp `AGENTS.md`:

```bash
cd ~/work/chief_of_staff
codex
```

Trên máy mới, clone repo này và đặt checkout ClassHub cạnh nó:

```text
~/work/chief_of_staff
~/work/classhub
```

Nếu ClassHub nằm ở nơi khác, cấu hình trước khi mở Codex:

```bash
export CLASSHUB_REPOSITORY=/absolute/path/to/classhub
cd /absolute/path/to/chief_of_staff
codex
```

Máy cần Git, Python 3, Codex CLI và Paseo CLI `0.2.5`; Paseo daemon phải đang
chạy và có các route Luna/Terra. Chạy `bin/chiefctl doctor --live` để xác nhận
toàn bộ dependency và đường dẫn trước khi giao task.

Kiểm tra các thành phần cục bộ mà không tạo agent:

```bash
bin/chiefctl doctor
```

Khi Paseo daemon đang chạy, Root chạy mandatory live preflight:

```bash
bin/chiefctl doctor --live
```

Nếu preflight đạt, có thể giao trực tiếp một yêu cầu như:

```text
Sửa lỗi số buổi còn lại hiển thị sai khi học viên đổi gói giữa kỳ.
```

Root agent sẽ thực hiện intake, đọc policy điều phối, quyết định topology, tạo
task contract, giao các role qua Paseo và chỉ đóng gate khi đủ artifact độc lập.

Paseo hiển thị các agent thật của task; hệ thống không tạo thêm agent chỉ để
lấp dashboard và giới hạn tối đa bốn role thực sự cần thiết.

Browser gate của ClassHub do tester chạy bằng Laravel Dusk qua `bin/dusk-safe`.
Root không chạy browser test và hệ thống không dùng Realbrowser.

## Chuẩn bị contract bằng CLI

Root agent có thể tạo contract và rendered prompt bằng:

```bash
bin/chiefctl prepare-classhub \
  --task-id session-package-remaining \
  --lane normal \
  --task-kind implementation \
  --objective "Correct remaining-session behavior after a package change" \
  --context "The class student list can show a stale remaining-session count" \
  --requirement "Show the current package remaining-session count" \
  --owns 'app/**' \
  --owns 'resources/**' \
  --owns 'tests/**' \
  --does-not-own 'database/migrations/**' \
  --verification 'bin/test-safe tests/Feature/SessionPackage' \
  --done-when "The relevant business regression is covered and passes"
```

`prepare-classhub` ghi model và effort vào contract. Mặc định: `tiny` dùng
Luna `medium`; `normal` và `high-risk` dùng Luna `max`.
Có thể chỉnh bằng `--model gpt-5.6-luna|gpt-5.6-terra` và
`--effort low|medium|high|xhigh|max`; mọi managed task ClassHub chủ động chặn
Sol. Terra chỉ dùng khi task cần judgment/kiến trúc rõ ràng hoặc Luna không đủ
năng lực sau một correction có evidence. `high-risk` giữ nguyên nhãn và yêu cầu
evidence và independent verification chặt hơn, nhưng không tự động chặn một yêu cầu đã rõ.
Chỉ escalation khi còn product decision có thể làm đổi tiền, buổi học, dữ liệu
lịch sử, tenant/quyền, chi phí dịch vụ ngoài, dữ liệu không thể hoàn tác, hoặc
production.
Task mới dùng artifact schema v4; các artifact v2/v3 đang chạy vẫn được đọc để
hoàn tất an toàn nhưng không được dùng làm mẫu cho task mới.

Để chỉ tìm bug mà không sửa code, Root dùng `--task-kind investigation`.
Investigator phải giữ nguyên locked revision, trả findings có evidence và
reviewer độc lập xác nhận trước khi chấp nhận báo cáo.

Artifacts được ghi dưới `.runtime/classhub/<task-id>/` và không đi vào source
control. Trước khi giao writer, root phải ghi intake vào ClassHub harness và bổ
sung các instruction layer/spec liên quan.

## Acceptance gate

Writer tạo evidence và handoff bằng `taskctl.py`. Đây chỉ là claim. Reviewer và
tester tạo các artifact độc lập; Root chỉ kiểm tra identity, provenance và thứ
tự gate.

```bash
python3 herdr-orchestrator/taskctl.py verify-handoff \
  --task .runtime/classhub/<task-id>/<task-id>.task.json \
  --handoff .runtime/classhub/<task-id>/<task-id>.handoff.json
```

Candidate pass vẫn chưa phải hoàn thành. Integrator phải xác nhận target branch
còn ở locked base, checkout sạch và fast-forward tới candidate. Tester và
reviewer sau đó lặp lại gate trên checkout ClassHub đã resolve. `ACCEPT` bắt
buộc tham chiếu đúng integrated evidence của cả hai role.

CLI hiện còn các tên legacy như `root-verify`. Tên lệnh không cấp quyền cho
Root chạy test hoặc review. Workflow phải fail closed cho đến khi artifact ghi
được role identity độc lập; tuyệt đối không fallback sang Root tự làm.

## Kiểm tra repo này

```bash
python3 -m unittest discover -s tests -v
```
