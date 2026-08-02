# ClassHub Engineering Chief of Staff

Repo này là nơi chạy root agent điều phối công việc kỹ thuật cho ClassHub. Anh
giao một yêu cầu ở mức nghiệp vụ; root agent đọc policy của ClassHub, phân loại
rủi ro, điều phối writer/reviewer qua Herdr, kiểm tra candidate và trả lại một
báo cáo ngắn.

## Phạm vi MVP

MVP hỗ trợ:

- chuẩn bị task contract và prompt có scope/authority rõ ràng;
- dùng ClassHub `bin/harness` làm durable record cho intake, story, decision và
  trace;
- writer làm việc trong Git worktree riêng qua Herdr;
- evidence và handoff gắn với đúng project/task/commit;
- Root khóa target branch/base trước khi giao việc; worker không được tự chọn;
- gate kiểm tra Git ancestry, file thực tế, `owns`, `does_not_own` và whitespace;
- Root tự chạy các safe verification command trên đúng candidate, không dùng
  exit code do worker tự khai;
- sau khi candidate pass, Root fast-forward vào target branch và chạy lại toàn
  bộ verification trước khi `ACCEPT`;
- root agent gửi correction cho cùng writer hoặc ghi `ACCEPT/REVISE/WAIT`;
- báo cáo cho người dùng theo ngôn ngữ nghiệp vụ của ClassHub.

Root Codex vẫn là orchestration engine: nó đọc yêu cầu, lựa chọn context và gọi
Herdr. `chiefctl` cung cấp các thao tác deterministic để tránh ghép task và gate
bằng tay; nó không phải một daemon hay một bộ lập lịch độc lập.

## Khởi động

Root Codex phải được mở trong một Herdr-managed pane với working directory là
repo này để Codex tự nạp `AGENTS.md`.

Kiểm tra các thành phần cục bộ mà không điều khiển Herdr:

```bash
bin/chiefctl doctor
```

Trong Herdr-managed root pane, chạy mandatory live preflight:

```bash
bin/chiefctl doctor --live
```

Nếu preflight đạt, có thể giao trực tiếp một yêu cầu như:

```text
Sửa lỗi số buổi còn lại hiển thị sai khi học viên đổi gói giữa kỳ.
```

Root agent sẽ tự thực hiện intake, đọc đúng spec/rules, quyết định topology,
tạo task contract, điều phối qua Herdr và đóng quality gate trước khi báo cáo.

## Chuẩn bị contract bằng CLI

Root agent có thể tạo contract và rendered prompt bằng:

```bash
bin/chiefctl prepare-classhub \
  --task-id session-package-remaining \
  --lane high-risk \
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

Artifacts được ghi dưới `.runtime/classhub/<task-id>/` và không đi vào source
control. Trước khi giao writer, root phải ghi intake vào ClassHub harness và bổ
sung các instruction layer/spec liên quan.

## Acceptance gate

Worker tạo evidence và handoff bằng `taskctl.py`. Đây chỉ là claim. Root kiểm
tra claim bằng:

```bash
python3 herdr-orchestrator/taskctl.py verify-handoff \
  --task .runtime/classhub/<task-id>/<task-id>.task.json \
  --handoff .runtime/classhub/<task-id>/<task-id>.handoff.json
```

Sau đó Root tự chạy test trong writer worktree:

```bash
python3 herdr-orchestrator/taskctl.py root-verify \
  --task .runtime/classhub/<task-id>/<task-id>.task.json \
  --handoff .runtime/classhub/<task-id>/<task-id>.handoff.json \
  --worktree /absolute/path/to/writer-worktree \
  --phase candidate \
  --requirement-checked "<exact requirement>" \
  --done-checked "<exact done_when>" \
  --output .runtime/classhub/<task-id>/candidate.root-verification.json
```

Candidate pass vẫn chưa phải hoàn thành. Root phải xác nhận target branch còn ở
locked base, checkout sạch, fast-forward tới candidate và chạy lại cùng lệnh với
`--phase integrated` trên `/Users/danhloi/work/classhub`. `decision-create
--decision ACCEPT` bắt buộc tham chiếu integrated Root verification này.

Root vẫn phải trực tiếp đọc diff, đối chiếu spec và kiểm tra tác động
tenant/money/session/data. Việc truyền đầy đủ mọi `--requirement-checked` và
`--done-checked` là acknowledgement bắt buộc của Root, không phải bằng chứng do
worker cung cấp.

## Kiểm tra repo này

```bash
python3 -m unittest discover -s tests -v
```
