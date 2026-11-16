#!/usr/bin/env python3
"""Tầng 1 – chương trình đo lường không giao diện (NET-02/T4).

Chạy đo lường tỷ lệ mất gói MAVLink, RTT và jitter giữa trạm mặt đất và xe PX4.
Số liệu chi tiết từng giây được ghi vào data/raw/<label>.csv.
Dòng tổng kết được ghi nối tiếp vào data/summary.csv.

Cách dùng:
    python tools/run_experiment.py --duration 60 --label d040_r1 --distance 40
"""

from __future__ import annotations

import argparse
import datetime
import os
import pathlib
import signal
import sys
import time

# Đảm bảo import được module rover từ thư mục gốc dự án
ROOT_DIR = pathlib .Path (__file__) .resolve () .parent .parent
if str (ROOT_DIR) not in sys .path:
    sys .path .insert (0, str (ROOT_DIR))

# PX4 gửi MAVLink 2
os .environ ["MAVLINK20"] = "1"

from rover .core .linkstats import (
    IntervalStats,
    RttTracker,
    SeqTracker,
    calc_mean,
    calc_percentile,
    calc_stdev,
    format_experiment_header,
    format_experiment_row,
    format_summary_header,
    format_summary_row,
)
from rover .core .model import Heartbeat, LinkState, PacketSeen, TimesyncReply
from rover .core .vehicle import LinkMonitor
from rover .drivers .clock import SystemClock
from rover .drivers .mavlink import MavlinkVehicleLink


def parse_args () -> argparse .Namespace:
    parser = argparse .ArgumentParser (
        description = "Chương trình đo chất lượng đường truyền MAVLink qua ns-3 / localhost (NET-02)"
    )
    parser .add_argument (
        "--url",
        default = "udpin:0.0.0.0:14540",
        help = "Địa chỉ lắng nghe MAVLink UDP (mặc định: udpin:0.0.0.0:14540)",
    )
    parser .add_argument (
        "--duration",
        type = float,
        default = 60.0,
        help = "Thời gian chạy đo lường tính bằng giây (mặc định: 60)",
    )
    parser .add_argument (
        "--label",
        default = "experiment",
        help = "Nhãn định danh lần chạy, ví dụ: baseline_r1, d050_r1 (mặc định: experiment)",
    )
    parser .add_argument (
        "--distance",
        type = float,
        default = 0.0,
        help = "Khoảng cách trong ns-3 tính bằng mét (mặc định: 0)",
    )
    parser .add_argument (
        "--out-dir",
        default = "data/raw",
        help = "Thư mục lưu file CSV chi tiết (mặc định: data/raw)",
    )
    parser .add_argument (
        "--summary-file",
        default = "data/summary.csv",
        help = "Đường dẫn file tổng kết toàn bộ thí nghiệm (mặc định: data/summary.csv)",
    )
    parser .add_argument (
        "--probe-hz",
        type = float,
        default = 5.0,
        help = "Tần số gửi gói probe TIMESYNC đo RTT (Hz, mặc định: 5.0)",
    )
    return parser .parse_args ()


def main () -> None:
    args = parse_args ()

    os .makedirs (args .out_dir, exist_ok = True)
    summary_dir = os .path .dirname (args .summary_file)
    if summary_dir:
        os .makedirs (summary_dir, exist_ok = True)

    raw_csv_path = os .path .join (args .out_dir, f"{args .label}.csv")
    command_str = " " .join (sys .argv)
    start_wall_time = datetime .datetime .now () .strftime ("%Y-%m-%d %H:%M:%S")

    clock = SystemClock ()
    link = MavlinkVehicleLink (url = args .url)

    link_monitor = LinkMonitor ()
    seq_tracker = SeqTracker ()
    rtt_tracker = RttTracker (timeout_s = 2.0)
    hb_stats = IntervalStats ()

    print ("=" * 72)
    print (f" BẮT ĐẦU ĐO LƯỜNG MAVLINK: {args .label}")
    print (f" Cổng kết nối   : {args .url}")
    print (f" Thời gian chạy : {args .duration} s")
    print (f" Khoảng cách    : {args .distance} m")
    print (f" Tần số probe   : {args .probe_hz} Hz")
    print (f" File chi tiết  : {raw_csv_path}")
    print (f" File tổng kết  : {args .summary_file}")
    print ("=" * 72)

    # Ghi header file chi tiết
    with open (raw_csv_path, "w", encoding = "utf-8") as f_raw:
        f_raw .write (
            format_experiment_header (
                command = command_str,
                start_time = start_wall_time,
                label = args .label,
                distance_m = args .distance,
                duration_s = args .duration,
                probe_hz = args .probe_hz,
            )
        )

    start_mono = clock .now ()
    next_probe_time = start_mono
    probe_interval = 1.0 / args .probe_hz if args .probe_hz > 0 else 1.0
    probe_counter = 1

    next_report_sec = 1
    lost_events = 0
    prev_state = LinkState .WAITING

    running = True

    def _sig_handler (sig, frame):
        nonlocal running
        print ("\n>>> Nhận tín hiệu dừng (Ctrl+C). Đang hoàn tất lưu số liệu...")
        running = False

    signal .signal (signal .SIGINT, _sig_handler)

    try:
        while running:
            now = clock .now ()
            elapsed = now - start_mono

            if elapsed >= args .duration:
                break

            # 1. Đọc mọi sự kiện đang chờ
            events = link .poll ()
            for ev in events:
                if isinstance (ev, Heartbeat):
                    link_monitor .on_heartbeat (now)
                    hb_stats .on_event (now)
                elif isinstance (ev, PacketSeen):
                    # Chỉ đếm gói của xe (khi đã biết system_id của xe)
                    if link .last_system_id is not None and ev .system_id == link .last_system_id:
                        seq_tracker .on_packet (ev .system_id, ev .component_id, ev .seq)
                elif isinstance (ev, TimesyncReply):
                    rtt_tracker .on_reply (probe_id = ev .ts1_ns, now = now)

            # 2. Theo dõi trạng thái link và đếm số lần mất kết nối
            cur_state = link_monitor .state (now)
            if prev_state != LinkState .LOST and cur_state == LinkState .LOST:
                lost_events += 1
            prev_state = cur_state

            # 3. Gửi probe TIMESYNC theo chu kỳ probe_hz khi đã thấy xe
            if now >= next_probe_time:
                if link .last_system_id is not None:
                    probe_id = probe_counter
                    probe_counter += 1
                    link .send_timesync (probe_id)
                    rtt_tracker .on_probe_sent (probe_id = probe_id, now = now)
                next_probe_time = now + probe_interval

            # 4. Quét timeout các probe quá hạn
            rtt_tracker .expire (now)

            # 5. Mỗi giây xuất số liệu 1 lần
            if elapsed >= next_report_sec:
                # Tính các chỉ số RTT bằng ms
                rtt_samples_ms = [s * 1000.0 for s in rtt_tracker .samples]
                rtt_mean = calc_mean (rtt_samples_ms)
                rtt_p95 = calc_percentile (rtt_samples_ms, 95.0)
                rtt_jit = calc_stdev (rtt_samples_ms)
                hb_jit_ms = (hb_stats .stdev * 1000.0) if hb_stats .stdev is not None else None

                row_str = format_experiment_row (
                    t = float (next_report_sec),
                    rx = seq_tracker .received,
                    lost = seq_tracker .lost,
                    loss_rate = seq_tracker .loss_rate,
                    resyncs = seq_tracker .resyncs,
                    probes_sent = rtt_tracker .sent,
                    probes_lost = rtt_tracker .lost,
                    rtt_mean_ms = rtt_mean,
                    rtt_p95_ms = rtt_p95,
                    rtt_jitter_ms = rtt_jit,
                    hb_jitter_ms = hb_jit_ms,
                    link_state = cur_state .name,
                    lost_events = lost_events,
                )
                with open (raw_csv_path, "a", encoding = "utf-8") as f_raw:
                    f_raw .write (row_str)

                # In tiến trình ra màn hình
                rtt_disp = f"{rtt_mean:.1f} ms" if rtt_mean is not None else "N/A"
                print (
                    f"[{next_report_sec:3d}s/{int(args .duration)}s] "
                    f"Trạng thái: {cur_state.name:<9} | "
                    f"Nhận: {seq_tracker.received:5d} | "
                    f"Mất: {seq_tracker.lost:4d} ({seq_tracker.loss_rate*100:5.2f}%) | "
                    f"RTT tb: {rtt_disp:<8} | "
                    f"Probe mất: {rtt_tracker.lost}"
                )
                next_report_sec += 1

            time .sleep (0.01)  # chu kỳ 10 ms
    finally:
        total_elapsed = clock .now () - start_mono
        link .close ()

        # Tính toán các chỉ số tổng kết cuối cùng
        all_rtt_ms = [s * 1000.0 for s in rtt_tracker .samples]
        final_rtt_mean = calc_mean (all_rtt_ms)
        final_rtt_p95 = calc_percentile (all_rtt_ms, 95.0)
        final_rtt_jitter = calc_stdev (all_rtt_ms)
        final_hb_jitter = (hb_stats .stdev * 1000.0) if hb_stats .stdev is not None else None

        # Nếu không nhận được bất kỳ gói nào trong suốt phiên đo, tỷ lệ mất gói là 100% (1.0)
        effective_loss_rate = 1.0 if seq_tracker.received == 0 else seq_tracker.loss_rate

        # Ghi vào file summary.csv
        write_summary_header = not os .path .exists (args .summary_file) or os .path .getsize (args .summary_file) == 0
        with open (args .summary_file, "a", encoding = "utf-8") as f_sum:
            if write_summary_header:
                f_sum .write (format_summary_header ())
            f_sum .write (
                format_summary_row (
                    label = args .label,
                    distance = args .distance,
                    duration = total_elapsed,
                    rx = seq_tracker .received,
                    lost = seq_tracker .lost,
                    loss_rate = effective_loss_rate,
                    rtt_mean_ms = final_rtt_mean,
                    rtt_p95_ms = final_rtt_p95,
                    rtt_jitter_ms = final_rtt_jitter,
                    hb_jitter_ms = final_hb_jitter,
                    probes_lost = rtt_tracker .lost,
                    lost_events = lost_events,
                )
            )

        print ("=" * 72)
        print (" KẾT QUẢ ĐO LƯỜNG TỔNG KẾT:")
        print (f"  Thời gian thực tế : {total_elapsed:.2f} s")
        print (f"  Tổng gói nhận (rx): {seq_tracker.received}")
        print (f"  Tổng gói mất      : {seq_tracker.lost}")
        print (f"  Tỷ lệ mất gói     : {seq_tracker.loss_rate * 100:.2f} %")
        print (f"  RTT trung bình    : {final_rtt_mean:.2f} ms" if final_rtt_mean else "  RTT trung bình    : N/A")
        print (f"  RTT p95           : {final_rtt_p95:.2f} ms" if final_rtt_p95 else "  RTT p95           : N/A")
        print (f"  Jitter RTT        : {final_rtt_jitter:.2f} ms" if final_rtt_jitter else "  Jitter RTT        : N/A")
        print (f"  Jitter HEARTBEAT  : {final_hb_jitter:.2f} ms" if final_hb_jitter else "  Jitter HEARTBEAT  : N/A")
        print (f"  Số probe RTT mất  : {rtt_tracker.lost}")
        print (f"  Số lần mất liên lạc: {lost_events}")
        print (f"  Đã ghi chi tiết vào: {raw_csv_path}")
        print (f"  Đã cập nhật vào    : {args .summary_file}")
        print ("=" * 72)


if __name__ == "__main__":
    main ()
