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
#   --distances "<d1 d2..>" Danh sách khoảng cách (mặc định: "10 40 50 60 70 80 90 100", calibration.txt mục 6)
#   --skip-baseline         Bỏ qua các lần đo baseline
#   --baseline-only         Chỉ đo baseline (bỏ qua quét khoảng cách)
#
# Baseline = PX4 và chương trình đo nói chuyện qua localhost, KHÔNG qua ns-3: chạy khi CHƯA dựng netns
# (sudo network/teardown-netns.sh; PX4 chạy bình thường: make px4_sitl gz_r1_rover). Nếu netns đang có,
# script bỏ qua baseline và báo. Quét khoảng cách thì ngược lại: cần netns + PX4 trong ns-rover.
#
# Biến môi trường:
#   NS3_BIN   đường dẫn file chạy rover-wifi (bắt buộc khi quét khoảng cách)
#   NS3_ARGS  tham số thêm cho rover-wifi, ví dụ "--fading=false" để so sánh với kênh không fading
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
NS3_BIN="${NS3_BIN:-}"
NS3_ARGS="${NS3_ARGS:-}"

# Cấu hình mặc định
DURATION=60
RUNS=3
DISTANCES="10 40 50 60 70 80 90 100"
RUN_BASELINE=true
RUN_SWEEP=true
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
        --baseline-only)
            RUN_SWEEP=false
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


# Biến lưu PID của tiến trình ns-3 đang chạy nền
CURRENT_NS3_PID=""

cleanup() {
    if [[ -n "$CURRENT_NS3_PID" ]]; then
        echo -e "\n[Dọn dẹp] Dừng tiến trình ns-3 (PID: $CURRENT_NS3_PID)..."
        kill -9 "$CURRENT_NS3_PID" 2>/dev/null || true
        wait "$CURRENT_NS3_PID" 2>/dev/null || true
        CURRENT_NS3_PID=""
    fi
}
trap cleanup INT TERM EXIT

# Kiểm tra xem có đang dùng network namespace ns-gcs không
USE_NETNS=false
if ip netns list | grep -qw "ns-gcs"; then
    USE_NETNS=true
    # Đảm bảo bảng ARP tĩnh luôn sẵn sàng tránh bị drop ARP broadcast trong Wi-Fi
    ip -n ns-gcs neigh replace 10.0.0.2 lladdr 02:00:00:00:00:02 dev veth-gcs 2>/dev/null || true
    ip -n ns-rover neigh replace 10.0.0.1 lladdr 02:00:00:00:00:01 dev veth-rover 2>/dev/null || true
fi

if [[ "$RUN_BASELINE" == true && "$USE_NETNS" == true ]]; then
    echo "Cảnh báo: netns đang có -> bỏ qua baseline (baseline phải chạy localhost, không qua ns-3)." >&2
    echo "          Chạy baseline riêng: sudo network/teardown-netns.sh ; PX4 bình thường ; sudo $0 --baseline-only" >&2
    RUN_BASELINE=false
fi
if [[ "$RUN_SWEEP" == true && "$USE_NETNS" != true ]]; then
    echo "Lỗi: quét khoảng cách cần netns + PX4 trong ns-rover (sudo network/setup-netns.sh). Chỉ đo baseline: --baseline-only" >&2
    exit 1
fi
if [[ "$RUN_SWEEP" == true && ! -x "$NS3_BIN" ]]; then
    echo "Lỗi: không thấy file chạy ns-3 '$NS3_BIN'. Đặt biến NS3_BIN, ví dụ:" >&2
    echo "     sudo NS3_BIN=/home/<user>/ns-3-dev/build/scratch/ns3-dev-rover-wifi-debug $0" >&2
    exit 1
fi

echo "========================================================================"
echo " CHIẾN DỊCH QUÉT KHOẢNG CÁCH WI-FI MAVLINK (NET-03/T1)"
echo "========================================================================"
echo " Thời gian mỗi lần đo : ${DURATION} s"
echo " Số lần lặp mỗi mốc   : ${RUNS}"
echo " Mốc khoảng cách (m)  : ${DISTANCES}"
echo " Chạy baseline        : $([[ "$RUN_BASELINE" == true ]] && echo "Có (${RUNS} lần, localhost)" || echo "Bỏ qua")"
echo " Quét khoảng cách     : $([[ "$RUN_SWEEP" == true ]] && echo "Có" || echo "Bỏ qua")"
echo " ns-3                 : ${NS3_BIN:-–} ${NS3_ARGS}"
echo " Thư mục raw CSV      : ${OUT_DIR}"
echo " File tổng hợp        : ${SUMMARY_FILE}"
echo " Chế độ mạng          : $([[ "$USE_NETNS" == true ]] && echo "Linux netns (ns-gcs <-> ns-rover qua ns-3)" || echo "Localhost (trực tiếp)")"
echo "========================================================================"

# Script chạy bằng root nhưng run_experiment.py chạy bằng $RUN_USER: thư mục ghi kết quả phải thuộc $RUN_USER.
# OUT_DIR là thư mục riêng cho kết quả nên luôn trao lại; thư mục của file tổng hợp chỉ trao khi do script tạo ra.
SUMMARY_DIR="$(dirname "$SUMMARY_FILE")"
[[ -d "$SUMMARY_DIR" ]] && SUMMARY_DIR_EXISTED=true || SUMMARY_DIR_EXISTED=false
mkdir -p "$OUT_DIR" "$SUMMARY_DIR"
chown "$RUN_USER": "$OUT_DIR"
[[ "$SUMMARY_DIR_EXISTED" == false ]] && chown "$RUN_USER": "$SUMMARY_DIR"
if [[ -e "$SUMMARY_FILE" && ! -w "$SUMMARY_FILE" ]] || ! sudo -u "$RUN_USER" test -w "$SUMMARY_DIR"; then
    echo "Lỗi: $RUN_USER không ghi được vào $SUMMARY_FILE / $SUMMARY_DIR" >&2
    exit 1
fi

# Dừng tiến trình ns-3 cũ (nếu còn) để tránh tranh tap. Chỉ khớp tiến trình có dòng lệnh BẮT ĐẦU bằng file chạy
# ns-3; không dùng "pkill -f rover-wifi" vì nó khớp cả dòng lệnh "sudo NS3_BIN=...rover-wifi... run_sweep.sh"
# và giết luôn chính script này.
kill_old_ns3() {
    [[ -n "$NS3_BIN" ]] || return 0
    pkill -9 -f "^${NS3_BIN}( |$)" 2>/dev/null || true
}
kill_old_ns3
sleep 1

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
        kill_old_ns3
        sleep 0.5
        echo "[ns-3] Khởi chạy mô phỏng Wi-Fi: --distance=${dist}..."
        # RngRun khác nhau cho mỗi lần lặp để fading của các lần r1..r3 độc lập nhau
        # shellcheck disable=SC2086
        "$NS3_BIN" --distance="$dist" --RngRun="$run_idx" $NS3_ARGS > "$OUT_DIR/${label}.ns3.log" 2>&1 &
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
        kill -9 "$CURRENT_NS3_PID" 2>/dev/null || true
        wait "$CURRENT_NS3_PID" 2>/dev/null || true
        CURRENT_NS3_PID=""
        chown "$RUN_USER": "$OUT_DIR/${label}.ns3.log" 2>/dev/null || true
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
if [[ "$RUN_SWEEP" == true ]]; then
    echo -e "\n[GIAI ĐOẠN 2] Quét các mốc khoảng cách: ${DISTANCES}..."
    for dist in $DISTANCES; do
        pad_dist=$(printf "%03d" "$dist")
        for r in $(seq 1 "$RUNS"); do
            label="d${pad_dist}_r${r}"
            run_single_test "$label" "$dist" "$r"
        done
    done
fi

echo ""
echo "========================================================================"
echo " HOÀN TẤT TOÀN BỘ CHIẾN DỊCH QUÉT KHOẢNG CÁCH!"
echo " Kết quả tổng hợp đã ghi vào: ${SUMMARY_FILE}"
echo " Thư mục dữ liệu chi tiết    : ${OUT_DIR}"
echo "========================================================================"
