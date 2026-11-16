# Khảo sát ảnh hưởng của chất lượng Wi-Fi đến điều khiển xe rover PX4 (PX4 SITL + Gazebo + ns-3)

Mã thư mục: `N44_2026_LTM_007_012_057` – Môn Lập trình mạng.

## Đề tài
Xây dựng hệ thống mô phỏng xe tự hành Rover dùng PX4 SITL kết hợp Gazebo và ns-3 để khảo sát ảnh hưởng của chất lượng mạng Wi-Fi đến khả năng điều khiển xe. ns-3 mô phỏng các điều kiện mạng như suy hao tín hiệu, mất gói và độ trễ. Dữ liệu điều khiển MAVLink giữa trạm mặt đất và PX4 đi qua mạng mô phỏng thông qua TapBridge. Nhóm đo các chỉ số mạng và đánh giá tác động của chúng đến khả năng phản hồi, di chuyển của Rover trong các điều kiện mạng khác nhau.

## Thành viên
- Vũ Duy Dương
- Trương Nhật Hoàng
- Đinh Trần Thảo Phương

Giảng viên hướng dẫn: (điền)

## Đầu vào – đầu ra của thí nghiệm
- **Biến thay đổi:** khoảng cách giữa node mặt đất và node trên xe trong ns-3.
- **Giữ cố định:** chuẩn 802.11g, tốc độ truyền, mô hình suy hao log-distance (exponent 3.0), công suất phát, xe `gz_r1_rover`, kịch bản lệnh, thời gian mỗi lần chạy.
- **Số đo:**
  - Tầng mạng: tỷ lệ mất gói MAVLink (đếm từ trường `seq`), độ trễ khứ hồi (RTT), jitter.
  - Tầng điều khiển: số lần mất kết nối (quá 3 s không có HEARTBEAT).
  - Tầng xe: thời gian xe dừng và quãng đường xe đi thêm khi mất liên lạc.
- **So sánh (baseline):** PX4 và chương trình đo nói chuyện trực tiếp qua localhost, không qua ns-3.

## Kiến trúc mạng
```
 netns ns-gcs                                                                  netns ns-rover
+------------------+                                                          +------------------+
| chương trình đo  |                                                          | PX4 SITL         |
| hoặc drive_check |                                                          | + Gazebo         |
| 10.0.0.1/24      |                                                          | 10.0.0.2/24      |
+---[veth-gcs]-----+                                                          +---[veth-rover]---+
        |                        namespace chính của máy                              |
  [veth-gcs-br]                                                                 [veth-rover-br]
        |                                                                             |
     br-gcs --- tap-gcs ==TapBridge== ns-3: node 0 ~~Wi-Fi~~ node 1 ==TapBridge== tap-rover --- br-rover
                                      (khoảng cách, suy hao, gửi lại MAC)
```
- ns-3 chạy ở namespace chính và mở `tap-gcs`, `tap-rover` theo tên. Vì vậy hai tap phải ở namespace chính.
- Mỗi netns nối với tap bằng một cặp veth và một Linux bridge (tầng 2). Đây đúng là cách ví dụ `src/tap-bridge/examples/tap-wifi-virtual-machine.cc` của ns-3 làm với LXC; nhóm thay LXC bằng netns.
- Hai netns không có đường nào khác tới nhau. Mọi gói giữa 10.0.0.1 và 10.0.0.2 buộc phải đi qua mô hình Wi-Fi của ns-3.

## Kiến trúc code
Code Python chia 4 tầng, không có giao diện; số liệu ghi ra file CSV.
```
tools/              TẦNG 1  chương trình chạy: drive_check.py (lái thử), run_experiment.py (đo, NET-02)
rover/core/         TẦNG 2  xử lý thuần, không import pymavlink hay time; thời điểm truyền vào qua tham số now
                            model.py (kiểu dữ liệu), vehicle.py (LinkMonitor, ArmControl, DriveController)
rover/hal.py        TẦNG 3  interface VehicleLink, Clock (chỉ chữ ký hàm)
rover/drivers/      TẦNG 4  mavlink.py (MavlinkVehicleLink, pymavlink qua UDP), clock.py (SystemClock)
tests/                      test tự động; fakes.py và mavlink_sim.py giả lập tầng 3 và PX4 qua UDP
```

## Cấu trúc thư mục
```
rover/                 code Python (tầng 2–4)
tests/                 test tự động (pytest)
tools/                 chương trình chạy (tầng 1): lái thử, chương trình đo
network/               script netns/tap, chương trình ns-3, script chạy PX4 (NET-01)
data/                  số liệu thô (CSV) của từng lần chạy (NET-03, NET-04)
analysis/              script vẽ biểu đồ (NET-03)
docs/agile/            product backlog, user story, sprint, bug log, definition of done
docs/acceptance/       thủ tục và kết quả kiểm thử chấp nhận
docs/diagrams/<tên>/   sơ đồ: .mmd + .svg + .txt chú thích
docs/experiments/      ghi chép hiệu chỉnh và cấu hình thí nghiệm
docs/evidence/         ảnh Wireshark, pcap chọn lọc làm minh chứng
docs/report/           khung báo cáo cuối kỳ
```

## Phương pháp
Agile (Scrum kết hợp thực hành XP):
- 2 sprint, mỗi sprint 1 ngày. Mỗi sprint có planning, Daily Scrum, review, retrospective.
- Phần nào test tự động được thì viết test trước rồi mới viết code (TDD).
- Phần chưa rõ kỹ thuật làm bằng spike có giới hạn thời gian.
- Kiểm thử chấp nhận do người không làm chính phần đó chạy.
- Quy ước: tên trong code bằng tiếng Anh; chữ hiển thị, comment, docstring bằng tiếng Việt.
- Sơ đồ bằng Mermaid; mỗi sơ đồ một thư mục docs/diagrams/<tên>/ gồm .mmd (nguồn), .svg (ảnh xuất), .txt (chú thích ký hiệu và luồng).
- Commit: `NET-xx/Tx: <nội dung>` hoặc `S0x/<mã>: <nội dung>`. Mỗi task một nhánh viết thường (`net-01/t1`).
- Chi tiết: `docs/agile/definition-of-done.txt`, `docs/agile/product-backlog.txt`, `docs/agile/sprints/`.

## Trạng thái hiện tại
Sprint 01 – NET-01 (MAVLink qua ns-3) và NET-02 (công cụ đo).

## Cách chạy
Cài môi trường và chạy test:
```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pytest
```
Lái thử khi PX4 SITL đang chạy (chưa qua ns-3):
```
make px4_sitl gz_r1_rover          # trong thư mục PX4-Autopilot, terminal khác
python tools/drive_check.py tien
```
Các bước dựng mạng, chạy ns-3, PX4 trong netns và chương trình đo sẽ được bổ sung ở đây khi các task NET-01, NET-02 xong.
