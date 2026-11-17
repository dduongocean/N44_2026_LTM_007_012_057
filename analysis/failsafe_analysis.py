#!/usr/bin/env python3
"""Phân tích thực nghiệm failsafe NET-04: đọc data/failsafe/<nhãn>_pose.csv + <nhãn>_events.csv.

Với mỗi lần chạy (t0 = lúc cắt mạng / ngừng gửi lệnh):
  v0          vận tốc trung bình trong 0.5 s trước t0 (m/s)
  t_react     từ t0 tới lúc PX4 đổi chế độ (HEARTBEAT, ví dụ MANUAL -> AUTO/RTL) (s)
  t_brake     từ t0 tới lúc vận tốc tụt dưới 50% v0 – xe bắt đầu phanh (s)
  d_max       quãng xa nhất xe đi được tính từ vị trí ở t0, trong 5 s sau t0 (m) – chỉ số an toàn chính
  t_stop      từ t0 tới lúc vận tốc < 0.05 m/s và giữ ít nhất 0.5 s (s); sau khi phanh xe còn trôi / lùi chậm
  d_stop      khoảng cách thẳng từ vị trí ở t0 tới vị trí lúc dừng (m); nhỏ hơn d_max vì xe lùi lại sau khi phanh
  t_move      từ t0 tới lúc xe tự chạy lại sau khi dừng (vận tốc > 0.2 m/s), nếu có (s)
Ghi data/failsafe_summary.csv và analysis/failsafe_speed.png.

Cách dùng: venv/bin/python analysis/failsafe_analysis.py [--dir data/failsafe]
"""

import argparse
import glob
import math
import os

import matplotlib
matplotlib .use ("Agg")
import matplotlib .pyplot as plt  # noqa: E402
import pandas as pd               # noqa: E402

STOP_SPEED = 0.05   # m/s
STOP_HOLD = 0.5     # s
MOVE_SPEED = 0.2    # m/s


def analyse (pose: pd.DataFrame, events: dict) -> dict:
    """Tính các chỉ số của một lần chạy."""
    t0 = events ["t0"]
    pos = pose .dropna (subset = ["speed"]) .sort_values ("t")
    modes = pose [pose ["text"] == "MODE"] .sort_values ("t")
    texts = pose [pose ["text"] .notna () & (pose ["text"] != "MODE")]

    before = pos [(pos .t >= t0 - 0.5) & (pos .t < t0)]
    v0 = before .speed .mean () if len (before) else float ("nan")
    at0 = pos [pos .t <= t0] .tail (1)
    x0, y0 = (at0 .x .iloc [0], at0 .y .iloc [0]) if len (at0) else (float ("nan"), float ("nan"))

    mode_t0 = modes [modes .t <= t0] .mode_ .iloc [-1] if len (modes [modes .t <= t0]) else ""
    after_modes = modes [(modes .t > t0) & (modes .mode_ != mode_t0)]
    t_react = after_modes .t .iloc [0] - t0 if len (after_modes) else float ("nan")
    new_mode = after_modes .mode_ .iloc [0] if len (after_modes) else ""

    first5 = pos [(pos .t >= t0) & (pos .t <= t0 + 5)]
    dist = ((first5 .x - x0) ** 2 + (first5 .y - y0) ** 2) ** 0.5
    d_max = dist .max () if len (dist) else float ("nan")
    slow = first5 [first5 .speed < 0.5 * v0]
    t_brake = slow .t .iloc [0] - t0 if len (slow) else float ("nan")

    t_stop = d_stop = t_move = float ("nan")
    end = events .get ("restore", events .get ("end", pos .t .max ()))
    window = pos [(pos .t >= t0) & (pos .t <= end)]
    for i, row in enumerate (window .itertuples ()):
        if row .speed < STOP_SPEED:
            hold = window [(window .t >= row .t) & (window .t <= row .t + STOP_HOLD)]
            if (hold .speed < STOP_SPEED) .all () and hold .t .max () - row .t >= STOP_HOLD * 0.8:
                t_stop = row .t - t0
                d_stop = math .hypot (row .x - x0, row .y - y0)
                again = window [(window .t > row .t) & (window .speed > MOVE_SPEED)]
                if len (again):
                    t_move = again .t .iloc [0] - t0
                break
    after_texts = texts [texts .t > t0] .text .tolist ()
    return {"v0_mps": v0, "mode_t0": mode_t0, "new_mode": new_mode, "t_react_s": t_react,
            "t_brake_s": t_brake, "d_max_m": d_max, "t_stop_s": t_stop, "d_stop_m": d_stop, "t_move_again_s": t_move,
            "px4_text": " | ".join (dict .fromkeys (after_texts)) [:200]}


def main ():
    p = argparse .ArgumentParser (description = __doc__ .splitlines () [0])
    p .add_argument ("--dir", default = "data/failsafe")
    p .add_argument ("--summary", default = "data/failsafe_summary.csv")
    p .add_argument ("--plot", default = "analysis/failsafe_speed.png")
    args = p .parse_args ()

    rows, curves = [], []
    for ev_file in sorted (glob .glob (os .path .join (args .dir, "*_events.csv"))):
        label = os .path .basename (ev_file) [:-len ("_events.csv")]
        pose_file = os .path .join (args .dir, f"{label}_pose.csv")
        events = dict (pd .read_csv (ev_file) .values .tolist ())
        netem_file = os .path .join (args .dir, f"{label}_netem.csv")   # t0, restore của kịch bản cut
        if os .path .exists (netem_file):
            events .update (dict (pd .read_csv (netem_file) .values .tolist ()))
        if "t0" not in events or not os .path .exists (pose_file):
            print (f"[Bỏ qua] {label}: thiếu t0 hoặc file pose")
            continue
        pose = pd .read_csv (pose_file, keep_default_na = True) .rename (columns = {"mode": "mode_"})
        r = {"label": label, "scenario": label .split ("_") [1]}
        r .update (analyse (pose, events))
        rows .append (r)
        pos = pose .dropna (subset = ["speed"])
        curves .append ((label, r ["scenario"], pos .t - events ["t0"], pos .speed, events .get ("restore", None) and events ["restore"] - events ["t0"]))

    if not rows:
        print ("Không có lần chạy nào để phân tích")
        return
    df = pd .DataFrame (rows)
    df .to_csv (args .summary, index = False, float_format = "%.3f")
    show = ["label", "v0_mps", "new_mode", "t_react_s", "t_brake_s", "d_max_m", "t_stop_s", "d_stop_m", "t_move_again_s"]
    print (df [show] .to_string (index = False, float_format = lambda v: f"{v:.2f}"))
    print ("\nTrung bình theo kịch bản:")
    print (df .groupby ("scenario") [["v0_mps", "t_react_s", "t_brake_s", "d_max_m", "t_stop_s", "t_move_again_s"]]
           .agg (["mean", "std"]) .round (2) .to_string ())
    print (f"\n[OK] {args .summary}")

    scen = sorted (df .scenario .unique ())
    titles = {"cut": "Cắt mạng (netem loss 100% hai chiều)", "stopcmd": "Ngừng gửi lệnh, mạng vẫn tốt"}
    fig, axs = plt .subplots (len (scen), 1, figsize = (9, 3.6 * len (scen)), sharex = True, squeeze = False)
    for ax, s in zip (axs [:, 0], scen):
        for label, sc, t, v, t_restore in curves:
            if sc == s:
                ax .plot (t, v, label = label .split ("_") [-1])
                if t_restore:
                    ax .axvline (t_restore, color = "green", linestyle = ":", alpha = 0.6)
        ax .axvline (0, color = "red", linestyle = "--", label = "t0")
        ax .set_title (titles .get (s, s), fontweight = "bold")
        ax .set_ylabel ("Vận tốc (m/s)")
        ax .grid (True, linestyle = ":", alpha = 0.6)
        ax .legend (loc = "upper right", fontsize = 8)
    axs [-1, 0] .set_xlabel ("Thời gian so với t0 (s)  (đường chấm xanh: nối lại mạng)")
    axs [-1, 0] .set_xlim (-5, None)
    fig .tight_layout ()
    os .makedirs (os .path .dirname (args .plot) or ".", exist_ok = True)
    fig .savefig (args .plot, dpi = 200)
    print (f"[OK] {args .plot}")


if __name__ == "__main__":
    main ()
