#!/usr/bin/env bash
# Chạy PX4 SITL + Gazebo (xe gz_r1_rover) BÊN TRONG netns ns-rover (NET-01/T3),
# và thêm một instance MAVLink gửi tới trạm mặt đất 10.0.0.1:14540 (đi qua ns-3).
#
# Cách dùng (sau sudo network/setup-netns.sh và ns-3 rover-wifi đang chạy):
#   sudo -E network/run-px4.sh           có cửa sổ Gazebo (-E để giữ DISPLAY, XAUTHORITY)
#   sudo -E network/run-px4.sh --headless   không mở cửa sổ Gazebo (HEADLESS=1)
# Terminal này sẽ thành pxh> của PX4; gõ "shutdown" hoặc Ctrl+C để dừng.
# Ở terminal khác, phía trạm mặt đất:
#   sudo ip netns exec ns-gcs sudo -u $USER -E venv/bin/python tools/drive_check.py tien
#
# Biến môi trường tùy chọn:
#   PX4_DIR   thư mục PX4-Autopilot (mặc định /home/<user>/PX4-Autopilot), đã build "make px4_sitl"
#   GCS_IP    IP trạm mặt đất (mặc định 10.0.0.1), GCS_PORT cổng trên trạm (mặc định 14540)
set -euo pipefail

NS=ns-rover
GCS_IP=${GCS_IP:-10.0.0.1}
GCS_PORT=${GCS_PORT:-14540}
LOCAL_PORT=14581          # cổng PX4 nghe cho instance mới (14580 là instance Onboard mặc định tới 127.0.0.1)
AIRFRAME=4009             # 4009_gz_r1_rover

HEADLESS_ARG=""
for arg in "$@"; do
    case "$arg" in
        --headless) HEADLESS_ARG=1 ;;
        -h|--help)  sed -n '2,15p' "$0"; exit 0 ;;
        *) echo "Tham số không hợp lệ: $arg (xem --help)" >&2; exit 1 ;;
    esac
done

if [[ $EUID -ne 0 ]]; then
    echo "Cần chạy bằng sudo: sudo $0 $*" >&2
    exit 1
fi
RUN_USER=${SUDO_USER:?Chạy bằng sudo từ user thường, không đăng nhập root}
RUN_HOME=$(getent passwd "$RUN_USER" | cut -d: -f6)
PX4_DIR=${PX4_DIR:-$RUN_HOME/PX4-Autopilot}
BUILD=$PX4_DIR/build/px4_sitl_default

if ! ip netns list | grep -qw "$NS"; then
    echo "Chưa có netns $NS. Chạy trước: sudo network/setup-netns.sh" >&2
    exit 1
fi
if [[ ! -x $BUILD/bin/px4 ]]; then
    echo "Không thấy $BUILD/bin/px4. Build trước (user thường): cd $PX4_DIR && make px4_sitl" >&2
    exit 1
fi

# gz-transport (PX4 <-> Gazebo) tìm nhau bằng multicast. Trong ns-rover chỉ có lo là chắc chắn
# chỉ nội bộ, nên bật multicast cho lo và ép gz dùng 127.0.0.1 (GZ_IP bên dưới).
ip -n "$NS" link set lo up
ip -n "$NS" link set lo multicast on
ip -n "$NS" route replace 224.0.0.0/4 dev lo

# Chạy một lệnh trong ns-rover bằng user thường (PX4 không nên chạy bằng root).
# Truyền rõ các biến môi trường cần cho cửa sổ Gazebo (DISPLAY, XAUTHORITY, ...).
in_ns() {
    ip netns exec "$NS" sudo -u "$RUN_USER" \
        env HOME="$RUN_HOME" PATH="$PATH" \
            DISPLAY="${DISPLAY:-}" XAUTHORITY="${XAUTHORITY:-$RUN_HOME/.Xauthority}" \
            WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-}" XDG_RUNTIME_DIR="/run/user/$(id -u "$RUN_USER")" \
            GZ_IP=127.0.0.1 \
            "$@"
}

if [[ -z $HEADLESS_ARG && -z ${DISPLAY:-} ]]; then
    echo "Cảnh báo: DISPLAY trống, cửa sổ Gazebo có thể không mở. Dùng 'sudo -E' hoặc --headless." >&2
fi

# Sau khi PX4 khởi động xong: thêm instance MAVLink tới trạm mặt đất qua ns-3 (Q2, Q4).
# Dùng client px4-mavlink (nói chuyện với PX4 đang chạy qua /tmp/px4-sock-0), không sửa cây PX4.
add_gcs_link() {
    for _ in $(seq 1 120); do
        if in_ns "$BUILD/bin/px4-mavlink" status >/dev/null 2>&1; then
            sleep 3   # chờ rcS chạy hết (mavlink boot_complete)
            echo ">>> Thêm instance MAVLink: $NS:$LOCAL_PORT -> $GCS_IP:$GCS_PORT (onboard)"
            in_ns "$BUILD/bin/px4-mavlink" start -x -u "$LOCAL_PORT" -o "$GCS_PORT" -t "$GCS_IP" \
                -m onboard -r 4000000 \
                || echo ">>> LỖI: không thêm được instance MAVLink, gõ tay trong pxh> (xem Q2)" >&2
            return
        fi
        sleep 1
    done
    echo ">>> LỖI: PX4 không phản hồi sau 120 s, chưa thêm instance tới $GCS_IP" >&2
}
add_gcs_link &
ADDER_PID=$!
trap 'kill $ADDER_PID 2>/dev/null || true' EXIT

echo ">>> Chạy PX4 (airframe $AIRFRAME gz_r1_rover) trong $NS, user $RUN_USER${HEADLESS_ARG:+, HEADLESS}"
cd "$BUILD"
in_ns PX4_SYS_AUTOSTART="$AIRFRAME" ${HEADLESS_ARG:+HEADLESS=1} "$BUILD/bin/px4"
