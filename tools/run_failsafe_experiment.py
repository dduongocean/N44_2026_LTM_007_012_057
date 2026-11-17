#!/usr/bin/env python3
"""Script lái xe cho thực nghiệm failsafe NET-04 – chạy trong ns-gcs, gửi lệnh qua đường MAVLink chính (qua ns-3).

Hai kịch bản (--scenario):
  stopcmd : mạng vẫn tốt; lái tiến --drive-time giây rồi NGỪNG gửi MANUAL_CONTROL tại t0 (script tự ghi t0).
  cut     : lái tiến LIÊN TỤC suốt --drive-time + --observe-time + --recover-time giây; đường truyền bị cắt TỪ BÊN NGOÀI
            (tools/run_failsafe.sh đặt netem loss 100% và ghi t0). Khi mạng có lại, lệnh lái lại tới xe.
Cuối cùng gửi ga 0 rồi khóa xe. Vị trí xe do tools/failsafe_logger.py ghi trong ns-rover (không qua ns-3).

Mốc thời gian ghi vào --events (CSV "event,t", t = time.time ()): drive_start, t0 (chỉ stopcmd), end.
"""

import argparse
import os
import sys
import time

os .environ ["MAVLINK20"] = "1"
from pymavlink import mavutil                      # noqa: E402
from pymavlink .dialects .v20 import common as mavlink  # noqa: E402

MANUAL = 1          # main mode MANUAL của PX4 (custom_mode byte 3)
SEND_PERIOD = 0.05  # gửi MANUAL_CONTROL 20 lần/giây


def parse_args ():
    p = argparse .ArgumentParser (description = "Lái xe cho thực nghiệm failsafe NET-04")
    p .add_argument ("--url", default = "udpin:0.0.0.0:14540", help = "Địa chỉ nghe MAVLink UDP")
    p .add_argument ("--scenario", choices = ["stopcmd", "cut"], required = True)
    p .add_argument ("--drive-time", type = float, default = 4.0, help = "Lái tiến bao lâu trước t0 (s)")
    p .add_argument ("--observe-time", type = float, default = 15.0, help = "Quan sát sau t0 (s)")
    p .add_argument ("--recover-time", type = float, default = 3.0, help = "cut: tiếp tục gửi lệnh sau khi có lại mạng (s)")
    p .add_argument ("--throttle", type = int, default = 750, help = "Ga MANUAL_CONTROL z (500 = đứng, > 500 tiến)")
    p .add_argument ("--events", required = True, help = "File CSV ghi mốc thời gian")
    return p .parse_args ()


def main ():
    args = parse_args ()
    os .makedirs (os .path .dirname (args .events) or ".", exist_ok = True)
    ev = open (args .events, "w", encoding = "utf-8")
    ev .write ("event,t\n")

    def mark (name):
        ev .write (f"{name},{time .time ():.3f}\n")
        ev .flush ()
        print (f"[{name}] {time .strftime ('%H:%M:%S')}", flush = True)

    conn = mavutil .mavlink_connection (args .url, dialect = "common")
    print ("Chờ HEARTBEAT của xe ...", flush = True)
    hb = None
    deadline = time .time () + 30
    while time .time () < deadline:
        m = conn .recv_match (type = "HEARTBEAT", blocking = True, timeout = 1)
        if m and m .autopilot != mavlink .MAV_AUTOPILOT_INVALID:
            hb = m
            break
    if hb is None:
        print ("LỖI: 30 s không thấy xe (ns-3, PX4 đã chạy chưa?)", file = sys .stderr)
        sys .exit (1)
    sys_id, comp_id = hb .get_srcSystem (), hb .get_srcComponent ()
    print (f"Thấy xe: system {sys_id}, component {comp_id}", flush = True)

    def drive (z, seconds):
        end = time .time () + seconds
        while time .time () < end:
            conn .mav .manual_control_send (sys_id, 0, 0, z, 0, 0)
            conn .recv_match (blocking = False)          # đọc bỏ bớt để bộ đệm không đầy
            time .sleep (SEND_PERIOD)

    # MANUAL + mở khóa; vừa gửi ga đứng (500) để PX4 thấy có tín hiệu điều khiển
    conn .mav .command_long_send (sys_id, comp_id, mavlink .MAV_CMD_DO_SET_MODE, 0,
                                  mavlink .MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, MANUAL, 0, 0, 0, 0, 0)
    drive (500, 1.0)
    conn .mav .command_long_send (sys_id, comp_id, mavlink .MAV_CMD_COMPONENT_ARM_DISARM, 0, 1, 0, 0, 0, 0, 0, 0)
    drive (500, 1.0)

    mark ("drive_start")
    if args .scenario == "stopcmd":
        drive (args .throttle, args .drive_time)
        mark ("t0")
        time .sleep (args .observe_time)              # KHÔNG gửi gì: mất tín hiệu điều khiển, mạng vẫn tốt
    else:
        drive (args .throttle, args .drive_time + args .observe_time + args .recover_time)

    drive (500, 1.0)
    conn .mav .command_long_send (sys_id, comp_id, mavlink .MAV_CMD_COMPONENT_ARM_DISARM, 0, 0, 0, 0, 0, 0, 0, 0)
    drive (500, 0.5)
    mark ("end")
    ev .close ()
    conn .close ()


if __name__ == "__main__":
    main ()
