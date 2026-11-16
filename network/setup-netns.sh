#!/usr/bin/env bash
# Dựng mạng ảo của NET-01 (xem README, mục Kiến trúc mạng):
#
#   ns-gcs  [veth-gcs 10.0.0.1/24]   -- veth-gcs-br   -- br-gcs   -- tap-gcs   == ns-3 node 0
#   ns-rover[veth-rover 10.0.0.2/24] -- veth-rover-br -- br-rover -- tap-rover == ns-3 node 1
#
# Hai netns chỉ nối với nhau qua ns-3 (TapBridge UseLocal). Tap phải ở namespace chính
# vì ns-3 chạy ở đó và mở tap theo tên.
#
# Mục đích: tách trạm mặt đất (ns-gcs) và xe PX4 (ns-rover) thành 2 "máy" mạng riêng,
# để gói MAVLink không đi tắt qua 127.0.0.1 mà phải qua mô hình Wi-Fi của ns-3.
#
# Cách dùng:
#   sudo network/setup-netns.sh        dựng mạng (chạy lại nhiều lần được: tự gọi teardown trước)
#   sudo network/teardown-netns.sh     gỡ khi làm xong
# Sau khi dựng: chạy ns-3 (rover-wifi) rồi chạy chương trình bằng
#   sudo ip netns exec ns-gcs   sudo -u $USER -E <lệnh>    (trạm mặt đất, 10.0.0.1)
#   sudo ip netns exec ns-rover sudo -u $USER -E <lệnh>    (PX4 + Gazebo, 10.0.0.2)
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Cần chạy bằng sudo: sudo $0" >&2
    exit 1
fi

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$DIR/teardown-netns.sh" >/dev/null

# MAC cố định của veth trong netns. PHẢI trùng với GCS_MAC / ROVER_MAC trong network/ns3/rover-wifi.cc:
# TapBridge UseLocal đổi MAC thiết bị Wi-Fi của ns-3 theo MAC nguồn của khung đầu tiên (chính là veth),
# nên rover-wifi.cc gán sẵn đúng MAC này (xem BUG-01 trong docs/agile/bug-log.txt).
GCS_MAC=02:00:00:00:00:01
ROVER_MAC=02:00:00:00:00:02

# Tắt IPv6 trên interface ở namespace chính (bridge, tap, đầu veth ở bridge) để chúng không tự phát gói
# (Router/Neighbor Solicitation). Trên mỗi bridge chỉ được có MỘT thiết bị nói chuyện là veth trong netns,
# nếu không TapBridge UseLocal có thể học nhầm MAC.
no_ipv6() { sysctl -qw "net.ipv6.conf.$1.disable_ipv6=1" 2>/dev/null || true; }

# Hàm dựng một phía: <netns> <bridge> <tap> <veth trong netns> <veth ở bridge> <ip/cidr> <mac veth>
setup_side() {
    local ns=$1 br=$2 tap=$3 veth=$4 veth_br=$5 addr=$6 mac=$7

    # 1. netns + bật lo (PX4 và Gazebo nói chuyện qua lo trong ns-rover)
    ip netns add "$ns"
    ip -n "$ns" link set lo up

    # 2. bridge
    ip link add "$br" type bridge
    no_ipv6 "$br"

    # 3. tap ở namespace chính, gắn vào bridge
    ip tuntap add dev "$tap" mode tap
    no_ipv6 "$tap"
    ip link set "$tap" promisc on
    ip link set "$tap" master "$br"
    ip link set "$tap" up

    # 4. cặp veth: một đầu vào netns, một đầu gắn vào bridge
    ip link add "$veth_br" type veth peer name "$veth"
    no_ipv6 "$veth_br"
    ip link set "$veth" address "$mac"
    ip link set "$veth" netns "$ns"
    ip link set "$veth_br" master "$br"
    ip link set "$veth_br" up

    # 5. IP trong netns, bật veth và bridge
    ip -n "$ns" addr add "$addr" dev "$veth"
    ip -n "$ns" link set "$veth" up
    ip link set "$br" up
}

setup_side ns-gcs   br-gcs   tap-gcs   veth-gcs   veth-gcs-br   10.0.0.1/24 "$GCS_MAC"
setup_side ns-rover br-rover tap-rover veth-rover veth-rover-br 10.0.0.2/24 "$ROVER_MAC"

# 6. Tắt bridge-nf để iptables (ví dụ của Docker) không chặn gói đi qua bridge,
#    giống virtual-network-setup.sh trong ví dụ tap-bridge của ns-3.
modprobe br_netfilter 2>/dev/null || true
for f in /proc/sys/net/bridge/bridge-nf-*; do
    [[ -e "$f" ]] && echo 0 > "$f"
done

echo "Đã dựng mạng ảo:"
echo "  ns-gcs   : veth-gcs   10.0.0.1/24 ($GCS_MAC) -> br-gcs   + tap-gcs"
echo "  ns-rover : veth-rover 10.0.0.2/24 ($ROVER_MAC) -> br-rover + tap-rover"
echo "Chưa chạy ns-3 thì hai netns KHÔNG thông nhau (AC1)."
