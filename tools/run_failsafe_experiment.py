#!/usr/bin/env python3
# tools/run_failsafe_experiment.py
"""
Thực nghiệm đánh giá phản ứng Failsafe của xe Rover khi mất liên lạc (NET-04).
Kịch bản:
  1. Kết nối xe MAVLink, chuyển chế độ MANUAL và Mở khóa (ARM).
  2. Gửi lệnh lái xe tiến (z=700) đều đặn trong vài giây để xe đạt vận tốc ổn định.
  3. Tại thời điểm t0: Ngừng gửi lệnh điều khiển (mất tín hiệu RC/Manual control).
  4. Quan sát và ghi nhận:
     - Thời gian từ t0 đến khi xe dừng hẳn (v < 0.05 m/s).
     - Quãng đường xe trôi thêm sau t0.
     - Cảnh báo của PX4 (STATUSTEXT) và thay đổi chế độ bay/chế độ an toàn.
  5. Xuất kết quả ra file data/failsafe_summary.csv.
"""

import argparse
import datetime
import math
import os
import sys
import time

os.environ["MAVLINK20"] = "1"
from pymavlink import mavutil
from pymavlink.dialects.v20 import common as mavlink

MAIN_MODES = {1: "MANUAL", 2: "ALTCTL", 3: "POSCTL", 4: "AUTO", 5: "ACRO", 6: "OFFBOARD", 7: "STABILIZED"}


def parse_args():
    parser = argparse.ArgumentParser(description="Thực nghiệm Failsafe mất liên lạc NET-04")
    parser.add_argument("--url", default="udpin:0.0.0.0:14540", help="Địa chỉ nghe MAVLink UDP")
    parser.add_argument("--drive-time", type=float, default=2.5, help="Thời gian lái xe tiến trước khi ngắt (s)")
    parser.add_argument("--observe-time", type=float, default=6.0, help="Thời gian quan sát sau ngắt (s)")
    parser.add_argument("--throttle", type=int, default=700, help="Giá trị ga (z > 500 tiến, ví dụ 700)")
    parser.add_argument("--label", default="failsafe_r1", help="Nhãn lần thử")
    parser.add_argument("--out-file", default="data/failsafe_summary.csv", help="File CSV tổng hợp kết quả failsafe")
    return parser.parse_args()


def mode_name(custom_mode):
    main = (custom_mode >> 16) & 0xFF
    return MAIN_MODES.get(main, f"?{main}")


def main():
    args = parse_args()
    print("=" * 72)
    print(f" THỰC NGHIỆM FAILSAFE KHI MẤT LIÊN LẠC (NET-04): {args.label}")
    print(f" URL MAVLink      : {args.url}")
    print(f" Thời gian lái    : {args.drive_time} s (Ga: {args.throttle})")
    print(f" Thời gian quan sát: {args.observe_time} s")
    print("=" * 72)

    conn = mavutil.mavlink_connection(args.url, dialect="common")
    start_mono = time.monotonic()

    def log(text):
        print(f"[{time.monotonic() - start_mono:6.2f} s] {text}", flush=True)

    log("Đang đợi xe gửi HEARTBEAT...")
    sys_id = comp_id = None
    while True:
        msg = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=5)
        if msg and msg.autopilot != mavlink.MAV_AUTOPILOT_INVALID:
            sys_id = msg.get_srcSystem()
            comp_id = msg.get_srcComponent()
            log(f"Thấy xe PX4: system {sys_id}, component {comp_id}")
            break

    pose = {"x": 0.0, "y": 0.0, "vx": 0.0, "vy": 0.0, "speed": 0.0, "yaw": 0.0}
    status_texts = []
    mode_history = []

    def handle(m):
        nonlocal sys_id
        mtype = m.get_type()
        if mtype == "LOCAL_POSITION_NED":
            pose["x"], pose["y"] = m.x, m.y
            pose["vx"], pose["vy"] = m.vx, m.vy
            pose["speed"] = math.hypot(m.vx, m.vy)
        elif mtype == "ATTITUDE":
            pose["yaw"] = math.degrees(m.yaw)
        elif mtype == "STATUSTEXT":
            status_texts.append(m.text)
            log(f"STATUSTEXT: {m.text}")
        elif mtype == "HEARTBEAT":
            if m.autopilot != mavlink.MAV_AUTOPILOT_INVALID:
                armed = bool(m.base_mode & mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                cur_mode = mode_name(m.custom_mode)
                state_desc = f"{cur_mode} ({'ARMED' if armed else 'DISARMED'})"
                if not mode_history or mode_history[-1] != state_desc:
                    mode_history.append(state_desc)
                    log(f"Chế độ xe: {state_desc}")

    def pump():
        while True:
            m = conn.recv_match(blocking=False)
            if not m:
                break
            handle(m)

    # Chờ 1 giây để đọc vị trí ban đầu
    settle = time.monotonic() + 1.0
    while time.monotonic() < settle:
        pump()
        time.sleep(0.02)

    # Chuyển MANUAL và Mở khóa
    log("Chuyển chế độ MANUAL và Mở khóa xe...")
    conn.mav.command_long_send(sys_id, comp_id, mavlink.MAV_CMD_DO_SET_MODE, 0,
                               mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, 1, 0, 0, 0, 0, 0)
    time.sleep(0.2)
    conn.mav.command_long_send(sys_id, comp_id, mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 1, 0, 0, 0, 0, 0, 0)
    time.sleep(0.5)

    # Giai đoạn 1: Lái xe tiến
    log(f">>> GIAI ĐOẠN 1: Lái xe tiến trong {args.drive_time} s với z={args.throttle}...")
    drive_end = time.monotonic() + args.drive_time
    while time.monotonic() < drive_end:
        conn.mav.manual_control_send(sys_id, 0, 0, args.throttle, 0, 0)
        pump()
        time.sleep(0.05)

    # Thời điểm t0: Ngắt gửi lệnh điều khiển
    t0 = time.monotonic()
    pump()
    p0_x, p0_y = pose["x"], pose["y"]
    v0 = pose["speed"]
    log(f">>> [t0 = {t0 - start_mono:.2f} s] NGẮT GỬI LỆNH ĐIỀU KHIỂN! (Vận tốc lúc ngắt: {v0:.2f} m/s)")

    # Giai đoạn 2: Quan sát xe phản ứng và dừng lại
    t_stop = None
    drift_distance = 0.0
    observe_end = t0 + args.observe_time

    while time.monotonic() < observe_end:
        pump()
        cur_t = time.monotonic()
        cur_speed = pose["speed"]

        if t_stop is None and (cur_t - t0 > 0.2) and cur_speed < 0.05:
            t_stop = cur_t
            drift_distance = math.hypot(pose["x"] - p0_x, pose["y"] - p0_y)
            log(f">>> [XE DỪNG HẲN] tại t = {t_stop - t0:.2f} s sau khi mất lệnh!")
            log(f">>> Quãng đường xe trôi thêm: {drift_distance:.2f} m")

        time.sleep(0.02)

    if t_stop is None:
        t_stop = time.monotonic()
        drift_distance = math.hypot(pose["x"] - p0_x, pose["y"] - p0_y)
        stop_time_sec = t_stop - t0
        log(f">>> Xe chưa dừng hẳn trong thời gian quan sát! Vận tốc cuối: {pose['speed']:.2f} m/s")
    else:
        stop_time_sec = t_stop - t0

    # Khóa xe an toàn
    log("Khóa xe (DISARM) kết thúc thực nghiệm...")
    conn.mav.command_long_send(sys_id, comp_id, mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 0, 0, 0, 0, 0, 0, 0)
    time.sleep(0.5)
    conn.close()

    # Ghi kết quả vào CSV
    os.makedirs(os.path.dirname(args.out_file), exist_ok=True)
    write_header = not os.path.exists(args.out_file) or os.path.getsize(args.out_file) == 0
    with open(args.out_file, "a", encoding="utf-8") as f:
        if write_header:
            f.write("timestamp,label,v0_mps,stop_time_s,drift_distance_m,final_mode,statustext\n")
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_joined = " | ".join(status_texts).replace(",", ";")
        final_mode = mode_history[-1] if mode_history else "UNKNOWN"
        f.write(f"{now_str},{args.label},{v0:.2f},{stop_time_sec:.2f},{drift_distance:.2f},{final_mode},{status_joined}\n")

    print("=" * 72)
    print(" KẾT QUẢ FAILSAFE:")
    print(f"  Vận tốc ban đầu tại t0 : {v0:.2f} m/s")
    print(f"  Thời gian phản ứng/dừng: {stop_time_sec:.2f} s")
    print(f"  Quãng đường trôi thêm  : {drift_distance:.2f} m")
    print(f"  Chế độ kết thúc        : {final_mode}")
    print(f"  Cảnh báo PX4           : {status_joined if status_joined else '(Không có)'}")
    print(f"  Đã ghi vào             : {args.out_file}")
    print("=" * 72)


if __name__ == "__main__":
    main()
