#!/usr/bin/env bash
# Gỡ mạng ảo của NET-01: 2 netns, 2 bridge, 2 tap (veth trong netns tự mất theo).
# Ngược lại của setup-netns.sh: trả máy về trạng thái ban đầu.
#
# Cách dùng: sudo network/teardown-netns.sh
#   - Chạy khi làm xong thí nghiệm, hoặc khi mạng ảo bị lỗi và muốn dọn sạch.
#   - Không báo lỗi nếu chưa có gì để gỡ (setup-netns.sh cũng gọi script này trước khi dựng).
#   - Nên dừng ns-3, PX4, drive_check trước khi gỡ.
set -u

if [[ $EUID -ne 0 ]]; then
    echo "Cần chạy bằng sudo: sudo $0" >&2
    exit 1
fi

# Xóa netns -> veth-gcs / veth-rover bị xóa, đầu kia (veth-*-br) cũng mất theo.
for ns in ns-gcs ns-rover; do
    ip netns del "$ns" 2>/dev/null || true
done

# Phòng trường hợp đầu veth ở namespace chính còn sót (ví dụ setup dừng giữa chừng).
for dev in veth-gcs-br veth-rover-br; do
    ip link del "$dev" 2>/dev/null || true
done

for tap in tap-gcs tap-rover; do
    ip link del "$tap" 2>/dev/null || ip tuntap del dev "$tap" mode tap 2>/dev/null || true
done

for br in br-gcs br-rover; do
    ip link del "$br" 2>/dev/null || true
done

# Dọn dẹp tiến trình mô phỏng còn sót (nếu có)
pkill -f "gz sim" 2>/dev/null || true
pkill -f "px4" 2>/dev/null || true
pkill -f "rover-wifi" 2>/dev/null || true

echo "Đã gỡ mạng ảo (ns-gcs, ns-rover, br-*, tap-*, veth-*) và dọn dẹp tiến trình mô phỏng."
