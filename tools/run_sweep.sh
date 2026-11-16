#!/usr/bin/env bash
# tools/run_sweep.sh – Tự động hóa chiến dịch đo lường quét khoảng cách (NET-03/T1)
#
# Chức năng:
#   Chạy loạt thí nghiệm đo chất lượng đường truyền MAVLink qua ns-3 với nhiều mức
#   khoảng cách khác nhau (mỗi mức lặp lại N lần) và lưu kết quả vào data/raw/ và data/summary.csv.
#
# Cách dùng:
#   sudo tools/run_sweep.sh [tùy chọn]
#
# Tùy chọn:
#   --duration <giây>       Thời gian mỗi lần đo (mặc định: 60)
#   --runs <số lần>         Số lần lặp lại cho mỗi mốc khoảng cách (mặc định: 3)
#   --distances "<d1 d2..>" Danh sách khoảng cách (mặc định: "10 50 60 70 80 90 100 120")
#   --skip-baseline         Bỏ qua các lần đo baseline
#   --quick                 Chế độ kiểm tra nhanh: duration 10s, 1 lần lặp, khoảng cách "10 70"
#   --out-dir <thư mục>     Thư mục chứa file CSV chi tiết (mặc định: data/raw)
#   --summary-file <file>   Đường dẫn file tổng hợp (mặc định: data/summary.csv)
#   -h, --help              Hiển thị trợ giúp
#
# Yêu cầu:
#   - Đã dựng mạng ảo: sudo network/setup-netns.sh
#   - Đã bật PX4 SITL trong ns-rover: sudo -E network/run-px4.sh

set -euo pipefail

# Xác định thư mục dự án và người dùng
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

RUN_USER="${SUDO_USER:-$USER}"
PYTHON="${PYTHON:-$ROOT_DIR/venv/bin/python}"
NS3_BIN="${NS3_BIN:-/home/luffy/ns-3.49/build/scratch/ns3.49-rover-wifi-default}"

# Cấu hình mặc định
DURATION=60
RUNS=3
DISTANCES="10 50 60 70 80 90 100 120"
RUN_BASELINE=true
OUT_DIR="data/raw"
SUMMARY_FILE="data/summary.csv"
PROBE_HZ=5.0

# Xử lý tham số dòng lệnh
while [[ $# -gt 0 ]]; do
    case "$1" in
        --duration)
            DURATION="$2"
            shift 2
            ;;
        --runs)
            RUNS="$2"
            shift 2
            ;;
        --distances)
            DISTANCES="$2"
            shift 2
            ;;
        --skip-baseline)
            RUN_BASELINE=false
            shift
            ;;
        --quick)
            DURATION=10
            RUNS=1
            DISTANCES="10 70"
            RUN_BASELINE=false
            shift
            ;;
        --out-dir)
            OUT_DIR="$2"
            shift 2
            ;;
        --summary-file)
            SUMMARY_FILE="$2"
            shift 2
            ;;
        -h|--help)
            sed -ne '/^#/!q;s/^# //;2,$p' "$0"
            exit 0
            ;;
        *)
            echo "Lỗi: Tham số không hợp lệ '$1'. Dùng --help để xem hướng dẫn." >&2
            exit 1
            ;;
    esac
done

if [[ $EUID -ne 0 ]]; then
    echo "Lỗi: Script cần chạy bằng quyền sudo để điều khiển ns-3 và netns: sudo $0" >&2
    exit 1
fi

if [[ ! -x "$PYTHON" ]]; then
    echo "Lỗi: Không tìm thấy python virtualenv tại $PYTHON" >&2
    exit 1
fi

if [[ ! -x "$NS3_BIN" ]]; then
    echo "Lỗi: Không tìm thấy binary ns-3 tại $NS3_BIN" >&2
    exit 1
fi

# Biến lưu PID của tiến trình ns-3 đang chạy nền
CURRENT_NS3_PID=""

cleanup() {
    if [[ -n "$CURRENT_NS3_PID" ]]; then
        echo -e "\n[Dọn dẹp] Dừng tiến trình ns-3 (PID: $CURRENT_NS3_PID)..."
        kill -INT "$CURRENT_NS3_PID" 2>/dev/null || kill -TERM "$CURRENT_NS3_PID" 2>/dev/null || true
        wait "$CURRENT_NS3_PID" 2>/dev/null || true
        CURRENT_NS3_PID=""
    fi
}
trap cleanup INT TERM EXIT

# Kiểm tra xem có đang dùng network namespace ns-gcs không
USE_NETNS=false
if ip netns list | grep -qw "ns-gcs"; then
    USE_NETNS=true
fi

echo "========================================================================"
echo " CHIẾN DỊCH QUÉT KHOẢNG CÁCH WI-FI MAVLINK (NET-03/T1)"
echo "========================================================================"
echo " Thời gian mỗi lần đo : ${DURATION} s"
echo " Số lần lặp mỗi mốc   : ${RUNS}"
echo " Mốc khoảng cách (m)  : ${DISTANCES}"
echo " Chạy baseline        : $([[ "$RUN_BASELINE" == true ]] && echo "Có (3 lần)" || echo "Bỏ qua")"
echo " Thư mục raw CSV      : ${OUT_DIR}"
echo " File tổng hợp        : ${SUMMARY_FILE}"
echo " Chế độ mạng          : $([[ "$USE_NETNS" == true ]] && echo "Linux netns (ns-gcs <-> ns-rover qua ns-3)" || echo "Localhost (trực tiếp)")"
echo "========================================================================"

mkdir -p "$OUT_DIR"
mkdir -p "$(dirname "$SUMMARY_FILE")"

run_single_test() {
    local label="$1"
    local dist="$2"
    local run_idx="$3"

    echo ""
    echo "------------------------------------------------------------------------"
    echo ">>> BẮT ĐẦU: Nhãn = ${label} | Khoảng cách = ${dist} m | Lần lặp = ${run_idx}"
    echo "------------------------------------------------------------------------"

    # Nếu dùng netns, khởi động ns-3 với khoảng cách tương ứng
    if [[ "$USE_NETNS" == true ]]; then
        echo "[ns-3] Khởi chạy mô phỏng Wi-Fi: --distance=${dist}..."
        "$NS3_BIN" --distance="$dist" > /dev/null 2>&1 &
        CURRENT_NS3_PID=$!
        sleep 2

        if ! kill -0 "$CURRENT_NS3_PID" 2>/dev/null; then
            echo "Lỗi: ns-3 không thể khởi động hoặc đã crash!" >&2
            exit 1
        fi
        echo "[ns-3] Đang chạy với PID $CURRENT_NS3_PID (kênh mạng sẵn sàng)."
    fi

    # Thực thi chương trình đo lường
    if [[ "$USE_NETNS" == true ]]; then
        ip netns exec ns-gcs sudo -u "$RUN_USER" -E "$PYTHON" tools/run_experiment.py \
            --duration "$DURATION" \
            --label "$label" \
            --distance "$dist" \
            --out-dir "$OUT_DIR" \
            --summary-file "$SUMMARY_FILE" \
            --probe-hz "$PROBE_HZ"
    else
        sudo -u "$RUN_USER" -E "$PYTHON" tools/run_experiment.py \
            --duration "$DURATION" \
            --label "$label" \
            --distance "$dist" \
            --out-dir "$OUT_DIR" \
            --summary-file "$SUMMARY_FILE" \
            --probe-hz "$PROBE_HZ"
    fi

    # Dừng ns-3 nếu đang chạy
    if [[ -n "$CURRENT_NS3_PID" ]]; then
        echo "[ns-3] Dừng mô phỏng (PID $CURRENT_NS3_PID)..."
        kill -INT "$CURRENT_NS3_PID" 2>/dev/null || kill -TERM "$CURRENT_NS3_PID" 2>/dev/null || true
        wait "$CURRENT_NS3_PID" 2>/dev/null || true
        CURRENT_NS3_PID=""
    fi

    # Nghỉ 2 giây giữa các lần chạy để dọn sạch socket và ổn định
    sleep 2
}

# 1. Chạy Baseline nếu được yêu cầu
if [[ "$RUN_BASELINE" == true ]]; then
    echo -e "\n[GIAI ĐOẠN 1] Đo lường Baseline..."
    for r in $(seq 1 "$RUNS"); do
        label="baseline_r${r}"
        run_single_test "$label" 0.0 "$r"
    done
fi

# 2. Chạy loạt quét khoảng cách
echo -e "\n[GIAI ĐOẠN 2] Quét các mốc khoảng cách: ${DISTANCES}..."
for dist in $DISTANCES; do
    pad_dist=$(printf "%03d" "$dist")
    for r in $(seq 1 "$RUNS"); do
        label="d${pad_dist}_r${r}"
        run_single_test "$label" "$dist" "$r"
    done
done

echo ""
echo "========================================================================"
echo " HOÀN TẤT TOÀN BỘ CHIẾN DỊCH QUÉT KHOẢNG CÁCH!"
echo " Kết quả tổng hợp đã ghi vào: ${SUMMARY_FILE}"
echo " Thư mục dữ liệu chi tiết    : ${OUT_DIR}"
echo "========================================================================"
