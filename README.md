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
Biên dịch và chạy mô phỏng mạng ns-3 (NET-01/T2):
```bash
# Liên kết file mã nguồn vào scratch của ns-3 (trên máy là ~/ns-3.49)
ln -sf $(pwd)/network/ns3/rover-wifi.cc ~/ns-3.49/scratch/rover-wifi.cc

# Biên dịch bằng user thường
cd ~/ns-3.49
ninja -C cmake-cache scratch_rover-wifi
# (hoặc ./ns3 build scratch/rover-wifi)

# Chạy thử kiểm tra tham số
./build/scratch/ns3.49-rover-wifi-default --help
./build/scratch/ns3.49-rover-wifi-default --distance=10 --simTime=1
```

Lái thử khi PX4 SITL đang chạy (chưa qua ns-3):
```
make px4_sitl gz_r1_rover          # trong thư mục PX4-Autopilot, terminal khác
python tools/drive_check.py tien
```
### Dựng / gỡ mạng ảo (NET-01/T1)
Hai script tạo "đường ống" Linux để gói giữa trạm mặt đất và xe buộc phải đi qua ns-3 (xem mục Kiến trúc mạng):

| Script | Làm gì | Khi nào chạy |
|---|---|---|
| `network/setup-netns.sh` | Tạo 2 netns `ns-gcs` (10.0.0.1) và `ns-rover` (10.0.0.2), mỗi bên nối với một tap (`tap-gcs`, `tap-rover`) qua veth + bridge. Tự gỡ bản cũ trước nên chạy lại bao nhiêu lần cũng được. | Đầu mỗi buổi làm việc / trước mỗi thí nghiệm, **trước** khi chạy ns-3 và PX4 |
| `network/teardown-netns.sh` | Xóa hết netns, veth, bridge, tap ở trên. Không báo lỗi nếu chưa có. | Khi làm xong, hoặc khi muốn dọn sạch máy |

```
sudo network/setup-netns.sh                     # 1. dựng mạng
# 2. chạy ns-3 (rover-wifi, NET-01/T2) ở terminal khác -> hai netns mới thông nhau
# 3. chạy chương trình trong netns (cần sudo để vào netns, sudo -u $USER để không chạy bằng root):
sudo ip netns exec ns-gcs   sudo -u $USER -E venv/bin/python tools/drive_check.py tien
sudo -E network/run-px4.sh                      # PX4 + Gazebo trong ns-rover (NET-01/T3), xem mục dưới
sudo network/teardown-netns.sh                  # 4. dọn
```
Kiểm nhanh sau khi dựng (mọi lệnh `ip -n` / `ip netns exec` cần sudo):
```
sudo ip -n ns-gcs addr show veth-gcs            # inet 10.0.0.1/24
sudo ip -n ns-rover addr show veth-rover        # inet 10.0.0.2/24
ip link show master br-gcs                      # tap-gcs, veth-gcs-br
sudo ip netns exec ns-gcs ping -c 5 10.0.0.2    # chưa chạy ns-3: 100% loss (không có đường tắt)
```
`tap-gcs`, `tap-rover` báo `NO-CARRIER` khi ns-3 chưa chạy: bình thường.

### Lái xe qua ns-3 (NET-01, AC3) – 3 terminal
Cần trước: PX4 đã build (`cd ~/PX4-Autopilot && make px4_sitl`), ns-3 đã build `rover-wifi` (mục trên), `venv` đã cài.
```bash
# Terminal 1: mạng ảo + PX4 + Gazebo trong ns-rover (terminal này thành pxh>; gõ "shutdown" để dừng)
sudo network/setup-netns.sh
sudo -E network/run-px4.sh                # -E giữ DISPLAY để mở cửa sổ Gazebo; thêm --headless nếu không cần cửa sổ

# Terminal 2: ns-3 (cần sudo để mở tap; ghi ĐƯỜNG DẪN ĐẦY ĐỦ vì với sudo "~" có thể là /root)
sudo /home/<user>/<thư mục ns-3>/build/scratch/<tên file>-rover-wifi-<profile> --distance=5

# Terminal 3: trạm mặt đất, chạy TỪ THƯ MỤC REPO
sudo ip netns exec ns-gcs ping -c 5 10.0.0.2                                   # thông, ~0% loss
sudo ip netns exec ns-gcs sudo -u $USER -E venv/bin/python tools/drive_check.py tien
```
Lưu ý:
- Tên file ns-3 tùy máy và profile build: `ls <thư mục ns-3>/build/scratch/ | grep rover`. Ví dụ `~/ns-3-dev` profile debug: `ns3-dev-rover-wifi-debug`; `~/ns-3.49` profile default: `ns3.49-rover-wifi-default`. Sau khi sửa `rover-wifi.cc` phải build lại, đừng chạy file cũ.
- `network/run-px4.sh` tự thêm instance MAVLink `14581 -> 10.0.0.1:14540` khi PX4 khởi động xong (thấy dòng `>>> Thêm instance MAVLink`). Kiểm bằng `mavlink status` trong `pxh>`. Đổi thư mục PX4 bằng biến `PX4_DIR`.
- MAC của `veth-gcs` (02:00:00:00:00:01) và `veth-rover` (02:00:00:00:00:02) cố định trong `setup-netns.sh` và PHẢI trùng hằng `GCS_MAC` / `ROVER_MAC` trong `rover-wifi.cc` (BUG-01 trong `docs/agile/bug-log.txt`). Đổi một bên thì đổi cả hai.
- Dựng lại mạng (`setup-netns.sh`) thì phải chạy lại PX4, vì netns cũ đã bị xóa.
- Cảnh báo `sudo: unable to resolve host ...` khi vào netns là vô hại.

### Chạy chương trình đo lường (NET-02/T4)
Đo mất gói MAVLink, RTT và jitter, xuất file CSV chi tiết và bảng tổng kết:
- **Baseline localhost** (không qua ns-3): PX4 chạy bình thường ở namespace chính:
  ```bash
  python tools/run_experiment.py --duration 60 --label baseline_r1
  ```
- **Chạy trong `ns-gcs` qua ns-3**:
  ```bash
  sudo ip netns exec ns-gcs sudo -u $USER -E venv/bin/python tools/run_experiment.py --duration 60 --label d040_r1 --distance 40
  ```
Số liệu chi tiết từng giây lưu tại `data/raw/<label>.csv`, dòng tổng kết được ghi nối tiếp vào `data/summary.csv`.
