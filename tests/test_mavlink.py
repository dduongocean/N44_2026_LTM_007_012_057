"""Kiểm tra tầng 4 – driver MAVLink: parse_heartbeat đọc thông tin xe từ HEARTBEAT và MavlinkVehicleLink đọc HEARTBEAT, COMMAND_ACK, gửi lệnh mở / khóa, gửi lệnh lái và đổi chế độ Manual; dùng gói tự đóng và giả lập UDP, không cần mô phỏng PX4."""

import time

from pymavlink .dialects .v20 import common as mavlink

from rover .core .model import ArmAck, Heartbeat, PacketSeen, TimesyncReply, VehicleInfo
from rover .drivers .mavlink import MavlinkVehicleLink, parse_heartbeat
from tests .mavlink_sim import (
    GCS_HEARTBEAT,
    VEHICLE_HEARTBEAT,
    HeartbeatSimulator,
    TwoWayVehicleSimulator,
    command_ack_bytes,
    find_free_port,
    heartbeat_bytes,
    timesync_bytes,
)


def make_heartbeat (system_id, component_id, autopilot, vehicle_type):
    """Tạo một HEARTBEAT giống như nhận được từ mạng.

    Làm 2 bước để giống thật:
    1. Bên gửi: đóng gói HEARTBEAT thành dãy byte. system_id và component_id của bên gửi được ghi vào phần đầu (header) của gói.
    2. Bên nhận: giải mã dãy byte đó thành message, như chương trình sẽ làm khi nhận từ mạng.
    """
    # Bên gửi, tự xưng là system_id / component_id.
    sender = mavlink. MAVLink (file = None, srcSystem = system_id, srcComponent = component_id)
    msg = sender. heartbeat_encode (
        type = vehicle_type,                        # loại thiết bị
        autopilot = autopilot,                      # loại firmware
        base_mode = 0,                              # các cờ trạng thái (không dùng trong test)
        custom_mode= 0,                             # chế độ riêng của PX4 (không dùng trong test)
        system_status = mavlink. MAV_STATE_STANDBY,  # trạng thái: đang chờ
    )
    data = msg. pack (sender)                         # -> dãy byte, đúng như gửi qua UDP

    # Bên nhận giải mã dãy byte thành message.
    receiver = mavlink. MAVLink (file = None)
    return receiver. decode (bytearray (data))


def test_1_heartbeat_tu_xe_px4_binh_thuong ():
    # Đầu vào: HEARTBEAT của xe mô phỏng (system 1, component 1, PX4, xe mặt đất).
    msg = make_heartbeat (
        system_id = 1,
        component_id = 1,
        autopilot = mavlink.MAV_AUTOPILOT_PX4,
        vehicle_type = mavlink.MAV_TYPE_GROUND_ROVER,
    )

    info = parse_heartbeat (msg)

    # Mong đợi: đọc ra đúng 4 thông tin, tên đã bỏ tiền tố "MAV_..._".
    assert info == VehicleInfo (
        system_id = 1,
        component_id = 1,
        autopilot = "PX4",
        vehicle_type = "GROUND_ROVER",
    )


def test_2_heartbeat_tu_QroundControl ():
    # Đầu vào: HEARTBEAT kiểu QGroundControl gửi:
    # autopilot = INVALID (không phải autopilot), type = GCS (trạm mặt đất).
    msg = make_heartbeat (
        system_id = 255,
        component_id = 190,
        autopilot = mavlink. MAV_AUTOPILOT_INVALID,
        vehicle_type = mavlink. MAV_TYPE_GCS,
    )

    # Mong đợi: None, nghĩa là "đây không phải xe", chương trình sẽ bỏ qua gói này.
    assert parse_heartbeat (msg) is None


def test_3_loai_xe_la_khong_gay_loi ():
    # Đầu vào: firmware PX4 nhưng type = 250, số này không có trong bảng tra MAV_TYPE.
    msg = make_heartbeat (
        system_id = 1,
        component_id = 1,
        autopilot = mavlink. MAV_AUTOPILOT_PX4,
        vehicle_type = 250,
    )

    info = parse_heartbeat (msg)

    # Mong đợi: không lỗi; vẫn nhận là xe, loại xe ghi "UNKNOWN(250)" để người dùng biết số thật.
    assert info is not None
    assert info.autopilot == "PX4"
    assert info.vehicle_type == "UNKNOWN(250)"


def test_4_doc_system_id_tu_goi_khong_gan_cung ():
    # Đầu vào: HEARTBEAT của một xe khác, có system_id = 2.
    msg = make_heartbeat (
        system_id = 2,
        component_id = 1,
        autopilot = mavlink.MAV_AUTOPILOT_PX4,
        vehicle_type = mavlink.MAV_TYPE_GROUND_ROVER,
    )

    info = parse_heartbeat (msg)

    # Mong đợi: system_id = 2, lấy từ phần đầu của gói, không phải số 1 viết sẵn trong code.
    assert info.system_id == 2
    assert info.component_id == 1


def test_5_vehicle_heartbeat_returns_heartbeat_event ():
    # Đầu vào: giả lập xe PX4 rover gửi HEARTBEAT tới cổng trống; chờ 0,3 s; gọi poll ().
    port = find_free_port ()
    link = MavlinkVehicleLink (url = f"udpin:127.0.0.1:{port}")
    try:
        with HeartbeatSimulator (port, [(VEHICLE_HEARTBEAT, 5)]):
            time .sleep (0.3)
            events = link .poll ()

        # Mong đợi: sinh Heartbeat với đúng thông tin xe và armed = False.
        heartbeats = [ev for ev in events if isinstance (ev, Heartbeat)]
        assert len (heartbeats) > 0
        for ev in heartbeats:
            assert ev .info == VehicleInfo (
                system_id = 1,
                component_id = 1,
                autopilot = "PX4",
                vehicle_type = "GROUND_ROVER",
            )
            assert ev .armed is False
    finally:
        link .close ()


def test_6_armed_flag_in_base_mode_sets_armed_true ():
    # Đầu vào: giả lập xe gửi HEARTBEAT có base_mode bật cờ MAV_MODE_FLAG_SAFETY_ARMED; gọi poll ().
    port = find_free_port ()
    armed_heartbeat = heartbeat_bytes (
        system_id = 1,
        component_id = 1,
        autopilot = mavlink .MAV_AUTOPILOT_PX4,
        vehicle_type = mavlink .MAV_TYPE_GROUND_ROVER,
        base_mode = mavlink .MAV_MODE_FLAG_SAFETY_ARMED,
    )
    link = MavlinkVehicleLink (url = f"udpin:127.0.0.1:{port}")
    try:
        with HeartbeatSimulator (port, [(armed_heartbeat, 5)]):
            time .sleep (0.3)
            events = link .poll ()

        # Mong đợi: Heartbeat .armed = True (giải mã trạng thái khóa xe từ base_mode).
        assert len (events) > 0
        assert events [0] .armed is True
    finally:
        link .close ()


def test_7_gcs_heartbeat_is_ignored ():
    # Đầu vào: chỉ có giả lập QGroundControl (autopilot = INVALID) gửi gói; chờ 0,3 s; gọi poll ().
    port = find_free_port ()
    link = MavlinkVehicleLink (url = f"udpin:127.0.0.1:{port}")
    try:
        with HeartbeatSimulator (port, [(GCS_HEARTBEAT, 5)]):
            time .sleep (0.3)
            events = link .poll ()

        # Mong đợi: trả danh sách rỗng [], không nhận nhầm trạm mặt đất là xe.
        assert events == []
    finally:
        link .close ()


def test_8_poll_without_packets_does_not_block ():
    # Đầu vào: không có giả lập nào gửi gói; đo thời gian thực hiện một lần poll ().
    port = find_free_port ()
    link = MavlinkVehicleLink (url = f"udpin:127.0.0.1:{port}")
    try:
        start = time .monotonic ()
        events = link .poll ()
        elapsed = time .monotonic () - start

        # Mong đợi: trả [] trong dưới 0,1 s, vòng lặp chương trình không bị đơ khi mất tín hiệu.
        assert events == []
        assert elapsed < 0.1
    finally:
        link .close ()


def _wait_for_heartbeat (link, timeout = 1.0):
    """Chờ tới khi link .poll () nhận được ít nhất một Heartbeat từ giả lập và gom toàn bộ sự kiện đã nhận."""
    collected = []
    deadline = time .monotonic () + timeout
    while time .monotonic () < deadline:
        events = link .poll ()
        collected .extend (events)
        if any (isinstance (ev, Heartbeat) for ev in events):
            return collected
        time .sleep (0.02)
    raise AssertionError ("Không nhận được HEARTBEAT từ giả lập")


def test_9_send_arm_true_sends_arm_command_long ():
    # Đầu vào: giả lập PX4 hai chiều gửi HEARTBEAT; chương trình poll () thấy xe; gọi send_arm (True).
    port = find_free_port ()
    link = MavlinkVehicleLink (url = f"udpin:127.0.0.1:{port}")
    try:
        with TwoWayVehicleSimulator (port) as sim:
            _wait_for_heartbeat (link)
            link .send_arm (True)
            cmds = sim .wait_commands (count = 1, timeout = 1.0)

        # Mong đợi: giả lập nhận được COMMAND_LONG với command = 400, param1 = 1, target_system = 1, target_component = 1.
        assert len (cmds) == 1
        assert cmds [0] .command == mavlink .MAV_CMD_COMPONENT_ARM_DISARM
        assert cmds [0] .param1 == 1
        assert cmds [0] .target_system == 1
        assert cmds [0] .target_component == 1
    finally:
        link .close ()


def test_10_send_arm_false_sends_disarm_command_long ():
    # Đầu vào: giả lập PX4 hai chiều gửi HEARTBEAT; chương trình poll () thấy xe; gọi send_arm (False).
    port = find_free_port ()
    link = MavlinkVehicleLink (url = f"udpin:127.0.0.1:{port}")
    try:
        with TwoWayVehicleSimulator (port) as sim:
            _wait_for_heartbeat (link)
            link .send_arm (False)
            cmds = sim .wait_commands (count = 1, timeout = 1.0)

        # Mong đợi: giả lập nhận được COMMAND_LONG với command = 400, param1 = 0, target_system = 1, target_component = 1.
        assert len (cmds) == 1
        assert cmds [0] .command == mavlink .MAV_CMD_COMPONENT_ARM_DISARM
        assert cmds [0] .param1 == 0
        assert cmds [0] .target_system == 1
        assert cmds [0] .target_component == 1
    finally:
        link .close ()


def test_11_poll_decodes_arm_command_ack_and_ignores_other_commands ():
    # Đầu vào: giả lập gửi COMMAND_ACK (400, ACCEPTED), COMMAND_ACK (400, DENIED), COMMAND_ACK (176, ACCEPTED); chương trình gọi poll ().
    port = find_free_port ()
    ack_packets = [
        command_ack_bytes (mavlink .MAV_CMD_COMPONENT_ARM_DISARM, mavlink .MAV_RESULT_ACCEPTED),
        command_ack_bytes (mavlink .MAV_CMD_COMPONENT_ARM_DISARM, mavlink .MAV_RESULT_DENIED),
        command_ack_bytes (176, mavlink .MAV_RESULT_ACCEPTED),
    ]
    link = MavlinkVehicleLink (url = f"udpin:127.0.0.1:{port}")
    try:
        with TwoWayVehicleSimulator (port, ack_packets = ack_packets):
            events = _wait_for_heartbeat (link)
            time .sleep (0.05)
            events .extend (link .poll ())

        # Mong đợi: trong kết quả có đúng [ArmAck (True), ArmAck (False)] theo thứ tự, bỏ qua ACK của lệnh 176.
        acks = [ev for ev in events if isinstance (ev, ArmAck)]
        assert acks == [ArmAck (True), ArmAck (False)]
    finally:
        link .close ()


def test_12_send_drive_forward_sends_manual_control ():
    # Đầu vào: giả lập PX4 hai chiều gửi HEARTBEAT; chương trình poll () thấy xe; gọi send_drive (0.5, 0.0).
    port = find_free_port ()
    link = MavlinkVehicleLink (url = f"udpin:127.0.0.1:{port}")
    try:
        with TwoWayVehicleSimulator (port) as sim:
            _wait_for_heartbeat (link)
            link .send_drive (0.5, 0.0)
            manual = sim .wait_manual (count = 1, timeout = 1.0)

        # Mong đợi: một MANUAL_CONTROL tới xe 1, z = 500 + 500 * 0.5 = 750 (tiến), y = 0, x = r = 0 (kênh đã thử trên PX4 SITL).
        assert len (manual) == 1
        assert manual [0] .target == 1
        assert (manual [0] .x, manual [0] .y, manual [0] .z, manual [0] .r) == (0, 0, 750, 0)
    finally:
        link .close ()


def test_13_send_drive_turn_left_sends_negative_y ():
    # Đầu vào: giả lập PX4 hai chiều gửi HEARTBEAT; chương trình poll () thấy xe; gọi send_drive (0.0, -0.5).
    port = find_free_port ()
    link = MavlinkVehicleLink (url = f"udpin:127.0.0.1:{port}")
    try:
        with TwoWayVehicleSimulator (port) as sim:
            _wait_for_heartbeat (link)
            link .send_drive (0.0, -0.5)
            manual = sim .wait_manual (count = 1, timeout = 1.0)

        # Mong đợi: z = 500 (không tiến, không lùi), y = -500 (quay trái) (dấu đã thử trên PX4 SITL).
        assert len (manual) == 1
        assert (manual [0] .z, manual [0] .y) == (500, -500)
    finally:
        link .close ()


def test_14_no_vehicle_seen_sends_nothing ():
    # Đầu vào: giả lập đang chạy nhưng chương trình chưa poll () nên chưa thấy HEARTBEAT nào; gọi send_drive (0.5, 0.0) và send_manual_mode ().
    port = find_free_port ()
    link = MavlinkVehicleLink (url = f"udpin:127.0.0.1:{port}")
    try:
        with TwoWayVehicleSimulator (port) as sim:
            link .send_drive (0.5, 0.0)
            link .send_manual_mode ()
            time .sleep (0.3)
            manual = sim .wait_manual (count = 1, timeout = 0.1)
            cmds = sim .wait_commands (count = 1, timeout = 0.1)

        # Mong đợi: giả lập không nhận MANUAL_CONTROL hay COMMAND_LONG nào (không gửi lệnh khi chưa có xe).
        assert manual == []
        assert cmds == []
    finally:
        link .close ()


def test_15_send_manual_mode_sends_set_mode_command ():
    # Đầu vào: giả lập PX4 hai chiều gửi HEARTBEAT; chương trình poll () thấy xe; gọi send_manual_mode ().
    port = find_free_port ()
    link = MavlinkVehicleLink (url = f"udpin:127.0.0.1:{port}")
    try:
        with TwoWayVehicleSimulator (port) as sim:
            _wait_for_heartbeat (link)
            link .send_manual_mode ()
            cmds = sim .wait_commands (count = 1, timeout = 1.0)

        # Mong đợi: COMMAND_LONG MAV_CMD_DO_SET_MODE (176), param1 = 1 (custom mode), param2 = 1 (Manual), tới xe 1 / component 1 (chế độ đã thử trên PX4 SITL).
        assert len (cmds) == 1
        assert cmds [0] .command == mavlink .MAV_CMD_DO_SET_MODE
        assert cmds [0] .param1 == mavlink .MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
        assert cmds [0] .param2 == 1
        assert cmds [0] .target_system == 1
        assert cmds [0] .target_component == 1
    finally:
        link .close ()


def test_16_each_valid_message_emits_packet_seen ():
    # Đầu vào: một luồng gửi HEARTBEAT từ xe; poll () phải sinh PacketSeen kèm seq, system_id, component_id và cả Heartbeat.
    port = find_free_port ()
    link = MavlinkVehicleLink (url = f"udpin:127.0.0.1:{port}")
    try:
        with HeartbeatSimulator (port, [(VEHICLE_HEARTBEAT, 0.3)]):
            deadline = time .monotonic () + 1.0
            seen_packet = None
            seen_hb = None
            while time .monotonic () < deadline:
                for event in link .poll ():
                    if isinstance (event, PacketSeen):
                        seen_packet = event
                    elif isinstance (event, Heartbeat):
                        seen_hb = event
                if seen_packet is not None and seen_hb is not None:
                    break
                time .sleep (0.02)

        # Mong đợi: nhận được PacketSeen với đúng nguồn của xe và kiểu "HEARTBEAT"
        assert seen_packet is not None
        assert seen_packet .system_id == 1
        assert seen_packet .component_id == 1
        assert seen_packet .msg_type == "HEARTBEAT"
        assert isinstance (seen_packet .seq, int)
        # Heartbeat vẫn được giải mã đầy đủ
        assert seen_hb is not None
        assert seen_hb .info .autopilot == "PX4"
    finally:
        link .close ()


def test_17_timesync_reply_only_when_tc1_nonzero ():
    # Đầu vào: gói TIMESYNC có tc1 != 0 (do xe phản hồi trạm).
    port = find_free_port ()
    link = MavlinkVehicleLink (url = f"udpin:127.0.0.1:{port}")
    pkt = timesync_bytes (tc1 = 123456789, ts1 = 987654321, system_id = 1, component_id = 1, seq = 15)
    try:
        with HeartbeatSimulator (port, [(pkt, 0.3)]):
            deadline = time .monotonic () + 1.0
            seen_reply = None
            seen_pkt = None
            while time .monotonic () < deadline:
                for event in link .poll ():
                    if isinstance (event, TimesyncReply):
                        seen_reply = event
                    elif isinstance (event, PacketSeen):
                        seen_pkt = event
                if seen_reply is not None and seen_pkt is not None:
                    break
                time .sleep (0.02)

        # Mong đợi: sinh TimesyncReply với đúng ts1_ns và sinh PacketSeen
        assert seen_reply is not None
        assert seen_reply .ts1_ns == 987654321
        assert seen_pkt is not None
        assert seen_pkt .msg_type == "TIMESYNC"
        assert seen_pkt .seq == 15
    finally:
        link .close ()


def test_18_timesync_with_tc1_zero_does_not_emit_timesync_reply ():
    # Đầu vào: gói TIMESYNC có tc1 = 0 (PX4 tự gửi yêu cầu đồng bộ, không phải phản hồi của trạm).
    port = find_free_port ()
    link = MavlinkVehicleLink (url = f"udpin:127.0.0.1:{port}")
    pkt = timesync_bytes (tc1 = 0, ts1 = 987654321, system_id = 1, component_id = 1, seq = 20)
    try:
        with HeartbeatSimulator (port, [(pkt, 0.3)]):
            deadline = time .monotonic () + 1.0
            replies = []
            seen_pkts = []
            while time .monotonic () < deadline:
                for event in link .poll ():
                    if isinstance (event, TimesyncReply):
                        replies .append (event)
                    elif isinstance (event, PacketSeen):
                        seen_pkts .append (event)
                if seen_pkts:
                    break
                time .sleep (0.02)

        # Mong đợi: sinh PacketSeen nhưng KHÔNG sinh TimesyncReply
        assert len (seen_pkts) > 0
        assert replies == []
    finally:
        link .close ()


def test_19_send_timesync_sends_to_vehicle_seen ():
    # Đầu vào: giả lập gửi HEARTBEAT; link poll () thấy xe; gọi send_timesync (ts1_ns = 555555555).
    port = find_free_port ()
    link = MavlinkVehicleLink (url = f"udpin:127.0.0.1:{port}")
    try:
        with TwoWayVehicleSimulator (port) as sim:
            _wait_for_heartbeat (link)
            link .send_timesync (ts1_ns = 555555555)
            timesync_msgs = sim .wait_timesync (count = 1, timeout = 1.0)

        # Mong đợi: giả lập nhận được gói TIMESYNC với tc1 = 0 và đúng ts1
        assert len (timesync_msgs) == 1
        assert timesync_msgs [0] .tc1 == 0
        assert timesync_msgs [0] .ts1 == 555555555
    finally:
        link .close ()


def test_20_send_timesync_does_nothing_if_no_vehicle_seen ():
    # Đầu vào: chưa thấy xe nào; gọi send_timesync ().
    port = find_free_port ()
    link = MavlinkVehicleLink (url = f"udpin:127.0.0.1:{port}")
    try:
        with TwoWayVehicleSimulator (port) as sim:
            link .send_timesync (ts1_ns = 555555555)
            time .sleep (0.3)
            timesync_msgs = sim .wait_timesync (count = 1, timeout = 0.1)

        # Mong đợi: không gửi gói TIMESYNC nào khi chưa thấy xe
        assert timesync_msgs == []
    finally:
        link .close ()
