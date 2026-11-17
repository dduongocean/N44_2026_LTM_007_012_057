#!/usr/bin/env bash
# tools/run_failsafe.sh – Thực nghiệm phản ứng của xe khi mất liên lạc giữa lúc chạy (NET-04)
#
# Mỗi lần chạy: bật ns-3 (--distance), bật failsafe_logger.py trong ns-rover (đọc xe qua 127.0.0.1:14550, KHÔNG qua ns-3),
# chạy run_failsafe_experiment.py trong ns-gcs (lái tiến qua ns-3), rồi:
#   cut     : sau --drive-time giây, netem loss 100% trên veth-gcs VÀ veth-rover (t0), giữ --observe-time giây, gỡ netem
#   stopcmd : script lái tự ngừng gửi lệnh tại t0 (mạng vẫn tốt) – để so sánh
# Kết quả: data/failsafe/<nhãn>_pose.csv, <nhãn>_events.csv (script lái ghi), <nhãn>_netem.csv (script này ghi t0,
# restore – file RIÊNG, không ghi chung với script lái); cuối cùng chạy analysis/failsafe_analysis.py.
# Dòng "Killed" sau mỗi lần chạy là bash báo đã dừng ns-3 (bình thường).
#
# Cách dùng (netns + PX4 trong ns-rover đang chạy; ns-3 CHƯA chạy):
#   sudo NS3_BIN=/home/<user>/ns-3-dev/build/scratch/ns3-dev-rover-wifi-debug tools/run_failsafe.sh
# Tùy chọn: --scenarios "cut stopcmd" --runs 3 --distance 10 --drive-time 4 --observe-time 15
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

RUN_USER="${SUDO_USER:-$USER}"
PYTHON="${PYTHON:-$ROOT_DIR/venv/bin/python}"
NS3_BIN="${NS3_BIN:-}"
SCENARIOS="cut stopcmd"
RUNS=3
DISTANCE=10
DRIVE=4
OBSERVE=15
RECOVER=3
OUT_DIR="data/failsafe"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --scenarios)    SCENARIOS="$2"; shift 2 ;;
        --runs)         RUNS="$2"; shift 2 ;;
        --distance)     DISTANCE="$2"; shift 2 ;;
        --drive-time)   DRIVE="$2"; shift 2 ;;
        --observe-time) OBSERVE="$2"; shift 2 ;;
        --out-dir)      OUT_DIR="$2"; shift 2 ;;
        -h|--help)      sed -n '2,15p' "$0"; exit 0 ;;
        *) echo "Tham số không hợp lệ: $1" >&2; exit 1 ;;
    esac
done

[[ $EUID -eq 0 ]] || { echo "Cần sudo: sudo NS3_BIN=... $0" >&2; exit 1; }
[[ -x "$NS3_BIN" ]] || { echo "Đặt NS3_BIN = file chạy rover-wifi" >&2; exit 1; }
[[ -x "$PYTHON" ]] || { echo "Không thấy $PYTHON" >&2; exit 1; }
ip netns list | grep -qw ns-rover || { echo "Chưa có netns (sudo network/setup-netns.sh)" >&2; exit 1; }
pgrep -f "build/px4_sitl_default/bin/px4" >/dev/null || { echo "PX4 chưa chạy trong ns-rover (sudo -E network/run-px4.sh)" >&2; exit 1; }

mkdir -p "$OUT_DIR"; chown "$RUN_USER": "$OUT_DIR"
as_user() { local ns=$1; shift; ip netns exec "$ns" sudo -u "$RUN_USER" -E "$@"; }

NS3_PID=""; LOG_PID=""
netem_off() {
    ip netns exec ns-gcs   tc qdisc del dev veth-gcs   root 2>/dev/null || true
    ip netns exec ns-rover tc qdisc del dev veth-rover root 2>/dev/null || true
}
cleanup() {
    netem_off
    [[ -n "$LOG_PID" ]] && kill -INT "$LOG_PID" 2>/dev/null || true
    [[ -n "$NS3_PID" ]] && kill -9 "$NS3_PID" 2>/dev/null || true
    LOG_PID=""; NS3_PID=""
}
trap cleanup EXIT INT TERM
pkill -9 -f "^${NS3_BIN}( |$)" 2>/dev/null || true
netem_off

for scen in $SCENARIOS; do
    for r in $(seq 1 "$RUNS"); do
        label="fs_${scen}_r${r}"
        echo; echo "=== $label | ns-3 --distance=$DISTANCE | lái ${DRIVE} s, quan sát ${OBSERVE} s ==="
        "$NS3_BIN" --distance="$DISTANCE" --RngRun="$r" > "$OUT_DIR/${label}.ns3.log" 2>&1 & NS3_PID=$!
        sleep 2
        as_user ns-rover "$PYTHON" tools/failsafe_logger.py --out "$OUT_DIR/${label}_pose.csv" & LOG_PID=$!
        sleep 1
        as_user ns-gcs "$PYTHON" tools/run_failsafe_experiment.py --scenario "$scen" \
            --drive-time "$DRIVE" --observe-time "$OBSERVE" --recover-time "$RECOVER" \
            --events "$OUT_DIR/${label}_events.csv" & DRV_PID=$!

        if [[ "$scen" == cut ]]; then
            for _ in $(seq 1 400); do grep -q '^drive_start' "$OUT_DIR/${label}_events.csv" 2>/dev/null && break; sleep 0.1; done
            sleep "$DRIVE"
            ip netns exec ns-gcs   tc qdisc add dev veth-gcs   root netem loss 100%
            ip netns exec ns-rover tc qdisc add dev veth-rover root netem loss 100%
            NETEM_FILE="$OUT_DIR/${label}_netem.csv"
            printf 'event,t\nt0,%s\n' "$(date +%s.%N)" > "$NETEM_FILE"; echo "[t0] CẮT MẠNG (netem loss 100% hai chiều)"
            sleep "$OBSERVE"
            netem_off
            echo "restore,$(date +%s.%N)" >> "$NETEM_FILE"; echo "[restore] NỐI LẠI MẠNG"
        fi
        wait "$DRV_PID" || echo "Cảnh báo: script lái kết thúc với lỗi" >&2
        sleep 2
        cleanup 2>/dev/null
        chown "$RUN_USER": "$OUT_DIR"/"${label}"* 2>/dev/null || true
        sleep 5   # để xe dừng hẳn / PX4 ổn định trước lần sau
    done
done

as_user ns-gcs "$PYTHON" analysis/failsafe_analysis.py --dir "$OUT_DIR" || true
