#!/usr/bin/env bash
# Kiểm thử chấp nhận NET-02 (phần đo AC2, AC3 và lần tham chiếu): 3 trường hợp × N lần × D giây, qua ns-3.
#   ref     : không netem
#   loss10  : netem loss 10%   trên veth-rover (chiều xe -> trạm)
#   delay50 : netem delay 50ms trên veth-rover (chiều xe -> trạm)
# Thứ tự xen kẽ theo lần lặp (r1: ref, loss10, delay50; r2: ...) để trôi điều kiện máy không dồn vào một trường hợp.
# AC1 (baseline localhost) lấy từ baseline_r1..r3 của NET-03, không chạy ở đây.
#
# Cần chạy trước (xem README):
#   sudo network/setup-netns.sh ; sudo -E network/run-px4.sh --headless ; ns-3 rover-wifi --distance=5 ở terminal khác
# Cách dùng (từ thư mục repo):
#   sudo tools/run_net02_acceptance.sh [--runs 3] [--duration 60] [--summary-file data/net02_acceptance_summary.csv]
# Kết quả: data/raw/acc_<trường hợp>_r<lần>.csv và các dòng trong file summary.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

RUNS=3
DURATION=60
SUMMARY="data/net02_acceptance_summary.csv"
OUT_DIR="data/raw"
CASES="ref loss10 delay50"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --runs)         RUNS="$2"; shift 2 ;;
        --duration)     DURATION="$2"; shift 2 ;;
        --summary-file) SUMMARY="$2"; shift 2 ;;
        -h|--help)      sed -n '2,13p' "$0"; exit 0 ;;
        *) echo "Tham số không hợp lệ: $1 (xem --help)" >&2; exit 1 ;;
    esac
done

[[ $EUID -eq 0 ]] || { echo "Cần sudo: sudo $0" >&2; exit 1; }
RUN_USER=${SUDO_USER:?Chạy bằng sudo từ user thường}
PYTHON="$PWD/venv/bin/python"

netem_off() { ip netns exec ns-rover tc qdisc del dev veth-rover root 2>/dev/null || true; }
trap netem_off EXIT INT TERM

# 1. Không ghi đè số liệu cũ (BUG-03): kiểm mọi nhãn sắp chạy trước khi bắt đầu
if [[ -s "$SUMMARY" ]]; then
    echo "LỖI: $SUMMARY đã có số liệu. Chuyển nó đi chỗ khác hoặc dùng --summary-file khác." >&2; exit 2
fi
for r in $(seq 1 "$RUNS"); do
    for c in $CASES; do
        [[ -e "$OUT_DIR/acc_${c}_r${r}.csv" ]] && { echo "LỖI: đã có $OUT_DIR/acc_${c}_r${r}.csv" >&2; exit 2; }
    done
done

# 2. Mạng phải thông trước khi đo (tránh lần đo rx = 0)
netem_off
if ! ip netns exec ns-gcs ping -c 3 -W 1 10.0.0.2 >/dev/null; then
    echo "LỖI: ns-gcs không ping được 10.0.0.2 – kiểm netns, ns-3 (--distance=5) và PX4." >&2; exit 1
fi
echo "Mạng thông. Chạy ${RUNS} lần × 3 trường hợp × ${DURATION} s (≈ $(( RUNS * 3 * (DURATION + 3) / 60 )) phút)."

# 3. Đo
for r in $(seq 1 "$RUNS"); do
    for c in $CASES; do
        label="acc_${c}_r${r}"
        case "$c" in
            ref)     ;;
            loss10)  ip netns exec ns-rover tc qdisc add dev veth-rover root netem loss 10% ;;
            delay50) ip netns exec ns-rover tc qdisc add dev veth-rover root netem delay 50ms ;;
        esac
        echo; echo "=== $label | netem: $(ip netns exec ns-rover tc qdisc show dev veth-rover | head -1) ==="
        ip netns exec ns-gcs sudo -u "$RUN_USER" -E "$PYTHON" tools/run_experiment.py \
            --duration "$DURATION" --distance 5 --label "$label" --out-dir "$OUT_DIR" --summary-file "$SUMMARY"
        netem_off
        rx=$(tail -1 "$SUMMARY" | cut -d, -f4)
        if [[ "$rx" == "0" ]]; then
            echo "LỖI: $label không nhận được gói nào – dừng để kiểm tra (số liệu đã có vẫn giữ nguyên)." >&2; exit 1
        fi
        sleep 2
    done
done

echo; echo "XONG. Tổng kết:"; cat "$SUMMARY"
