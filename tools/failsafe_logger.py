#!/usr/bin/env python3
"""Ghi vị trí, vận tốc và chế độ của xe khi đang thực nghiệm failsafe (NET-04).

Chạy BÊN TRONG ns-rover, nghe instance MAVLink mặc định của PX4 (127.0.0.1:14550 trong ns-rover). Đường này không đi
qua ns-3, nên vẫn đọc được xe sau khi đường MAVLink chính (qua ns-3) bị cắt.

Cách dùng (thường do tools/run_failsafe.sh gọi):
    sudo ip netns exec ns-rover sudo -u $USER -E venv/bin/python tools/failsafe_logger.py --out data/failsafe/x_pose.csv
Dừng bằng Ctrl+C / SIGINT / SIGTERM. Thời gian ghi bằng time.time () – cùng đồng hồ với script lái và run_failsafe.sh.
"""

import argparse
import math
import os
import signal
import sys
import time

os .environ ["MAVLINK20"] = "1"
sys .path .insert (0, os .path .dirname (os .path .dirname (os .path .abspath (__file__))))

from pymavlink import mavutil                      # noqa: E402
from pymavlink .dialects .v20 import common as mavlink  # noqa: E402

MAIN_MODES = {1: "MANUAL", 2: "ALTCTL", 3: "POSCTL", 4: "AUTO", 5: "ACRO", 6: "OFFBOARD", 7: "STABILIZED"}
AUTO_SUB_MODES = {1: "READY", 2: "TAKEOFF", 3: "LOITER", 4: "MISSION", 5: "RTL", 6: "LAND"}


def mode_name (custom_mode: int) -> str:
    """Tên chế độ PX4 từ custom_mode của HEARTBEAT, ví dụ MANUAL hoặc AUTO/RTL."""
    main = (custom_mode >> 16) & 0xFF
    name = MAIN_MODES .get (main, f"?{main}")
    if main == 4:
        name += "/" + AUTO_SUB_MODES .get ((custom_mode >> 24) & 0xFF, "?")
    return name


def main () -> None:
    parser = argparse .ArgumentParser (description = "Ghi vị trí / chế độ xe cho NET-04")
    parser .add_argument ("--url", default = "udpin:127.0.0.1:14550", help = "Instance MAVLink localhost trong ns-rover")
    parser .add_argument ("--out", required = True, help = "File CSV ghi ra")
    parser .add_argument ("--duration", type = float, default = 600.0, help = "Tối đa bao nhiêu giây (s)")
    args = parser .parse_args ()

    stop = {"flag": False}
    for sig in (signal .SIGINT, signal .SIGTERM):
        signal .signal (sig, lambda *_: stop .update (flag = True))

    conn = mavutil .mavlink_connection (args .url, dialect = "common")
    os .makedirs (os .path .dirname (args .out) or ".", exist_ok = True)
    state = {"mode": "", "armed": ""}
    end = time .time () + args .duration
    with open (args .out, "w", encoding = "utf-8") as f:
        f .write ("t,x,y,vx,vy,speed,mode,armed,text\n")
        while not stop ["flag"] and time .time () < end:
            msg = conn .recv_match (blocking = True, timeout = 0.2)
            if msg is None:
                continue
            t = time .time ()
            kind = msg .get_type ()
            if kind == "LOCAL_POSITION_NED":
                f .write (f"{t:.3f},{msg.x:.3f},{msg.y:.3f},{msg.vx:.3f},{msg.vy:.3f},"
                          f"{math.hypot (msg.vx, msg.vy):.3f},{state ['mode']},{state ['armed']},\n")
            elif kind == "HEARTBEAT" and msg .autopilot != mavlink .MAV_AUTOPILOT_INVALID:
                mode = mode_name (msg .custom_mode)
                armed = "ARMED" if msg .base_mode & mavlink .MAV_MODE_FLAG_SAFETY_ARMED else "DISARMED"
                if (mode, armed) != (state ["mode"], state ["armed"]):
                    state .update (mode = mode, armed = armed)
                    f .write (f"{t:.3f},,,,,,{mode},{armed},MODE\n")
            elif kind == "STATUSTEXT":
                text = msg .text .replace (",", ";") .replace ("\n", " ")
                f .write (f"{t:.3f},,,,,,{state ['mode']},{state ['armed']},{text}\n")
            f .flush ()


if __name__ == "__main__":
    main ()
