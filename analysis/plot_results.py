#!/usr/bin/env python3
# analysis/plot_results.py
import argparse
import os
import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

def parse_args():
    parser = argparse.ArgumentParser(
        description="Vẽ biểu đồ và xuất bảng tổng hợp số liệu khảo sát NET-03 từ summary.csv"
    )
    parser.add_argument(
        "--summary-file",
        default="data/summary.csv",
        help="Đường dẫn tới file summary.csv (mặc định: data/summary.csv)",
    )
    parser.add_argument(
        "--out-dir",
        default="analysis",
        help="Thư mục xuất biểu đồ và bảng kết quả (mặc định: analysis)",
    )
    return parser.parse_args()


def load_data(filepath: str) -> pd.DataFrame:
    if not os.path.exists(filepath):
        print(f"Lỗi: Không tìm thấy file {filepath}", file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(filepath)
    # Loại bỏ các dòng trống nếu có
    df = df.dropna(subset=["label", "distance", "loss_rate"])
    # Chỉ giữ các lần chạy của NET-03: baseline_rN và dXXX_rN (bỏ test_*, acc_* của NET-02...)
    keep = df["label"].astype(str).str.match(r"^(baseline_r\d+|d\d+_r\d+)$")
    if (~keep).any():
        print(f"[Bỏ qua] {(~keep).sum()} dòng không thuộc NET-03: {', '.join(df.loc[~keep, 'label'].astype(str))}")
    df = df[keep]
    # Nếu một nhãn bị ghi nhiều lần (chạy lại), chỉ giữ lần cuối
    dup = df.duplicated(subset=["label"], keep="last")
    if dup.any():
        print(f"[Bỏ qua] {dup.sum()} dòng trùng nhãn (giữ lần chạy cuối): {', '.join(df.loc[dup, 'label'].astype(str))}")
    df = df[~dup]
    # Đảm bảo các cột số là kiểu float
    numeric_cols = [
        "distance", "duration", "rx", "lost", "loss_rate",
        "rtt_mean_ms", "rtt_p95_ms", "rtt_jitter_ms", "hb_jitter_ms",
        "probes_lost", "lost_events"
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Đổi tỷ lệ mất gói sang phần trăm (%)
    df["loss_percent"] = df["loss_rate"] * 100.0
    return df


def generate_summary_table(df: pd.DataFrame, out_dir: str) -> pd.DataFrame:
    """Tính trung bình và độ lệch chuẩn của từng chỉ số theo khoảng cách."""
    grouped = df.groupby("distance").agg(
        runs=("label", "count"),
        loss_mean=("loss_percent", "mean"),
        loss_std=("loss_percent", "std"),
        rtt_mean=("rtt_mean_ms", "mean"),
        rtt_std=("rtt_mean_ms", "std"),
        rtt_p95_mean=("rtt_p95_ms", "mean"),
        rtt_jitter_mean=("rtt_jitter_ms", "mean"),
        rtt_jitter_std=("rtt_jitter_ms", "std"),
        hb_jitter_mean=("hb_jitter_ms", "mean"),
        hb_jitter_std=("hb_jitter_ms", "std"),
        probes_lost_sum=("probes_lost", "sum"),
        lost_events_sum=("lost_events", "sum"),
        lost_events_mean=("lost_events", "mean"),
        lost_events_std=("lost_events", "std"),
    ).reset_index()

    # Lưu ra CSV
    out_csv = os.path.join(out_dir, "summary_table.csv")
    grouped.to_csv(out_csv, index=False)
    print(f"[OK] Đã xuất bảng tổng hợp: {out_csv}")

    # Xuất bảng text
    out_txt = os.path.join(out_dir, "summary_table.txt")
    with open(out_txt, "w", encoding="utf-8") as f:
        f.write("BẢNG TỔNG HỢP KẾT QUẢ ĐO LƯỜNG ĐƯỜNG MAVLINK THEO KHOẢNG CÁCH (NET-03/AC3)\n")
        f.write("=" * 96 + "\n")
        f.write(f"{'Khoảng cách (m)':<16} | {'Số lần':<6} | {'Mất gói (%)':<16} | {'RTT tb (ms)':<16} | {'RTT p95 (ms)':<14} | {'Jitter RTT (ms)':<15}\n")
        f.write("-" * 96 + "\n")
        for _, row in grouped.iterrows():
            dist_label = f"Baseline (0m)" if row['distance'] == 0 else f"{row['distance']:.1f} m"
            loss_str = f"{row['loss_mean']:.2f} ± {row['loss_std']:.2f}%" if pd.notnull(row['loss_std']) else f"{row['loss_mean']:.2f}%"
            rtt_str = f"{row['rtt_mean']:.2f} ± {row['rtt_std']:.2f}" if pd.notnull(row['rtt_std']) else f"{row['rtt_mean']:.2f}"
            rtt_p95_str = f"{row['rtt_p95_mean']:.2f}" if pd.notnull(row['rtt_p95_mean']) else "N/A"
            rtt_jit_str = f"{row['rtt_jitter_mean']:.2f}" if pd.notnull(row['rtt_jitter_mean']) else "N/A"
            f.write(f"{dist_label:<16} | {int(row['runs']):<6} | {loss_str:<16} | {rtt_str:<16} | {rtt_p95_str:<14} | {rtt_jit_str:<15}\n")
        f.write("=" * 96 + "\n")
    print(f"[OK] Đã xuất bảng văn bản: {out_txt}")
    return grouped


def _baseline_value(baseline_summary: pd.DataFrame, col: str):
    """Giá trị trung bình của baseline (distance == 0) cho một cột; None nếu không có baseline."""
    if len(baseline_summary) == 0 or pd.isnull(baseline_summary[col].values[0]):
        return None
    return baseline_summary[col].values[0]


def draw_jitter(ax, wifi_summary: pd.DataFrame, baseline_summary: pd.DataFrame, title: str):
    """(c) Jitter: RTT ở trục trái, HEARTBEAT ở trục phải (hai thang khác nhau ~100 lần), có baseline và độ lệch chuẩn 3 lần."""
    rtt = wifi_summary.dropna(subset=["rtt_jitter_mean"])
    hb = wifi_summary.dropna(subset=["hb_jitter_mean"])
    ax2 = ax.twinx()
    ax.errorbar(rtt["distance"], rtt["rtt_jitter_mean"], yerr=rtt["rtt_jitter_std"].fillna(0),
                fmt="-o", color="darkorange", capsize=3, linewidth=2, label="Jitter RTT (trục trái)")
    ax2.errorbar(hb["distance"], hb["hb_jitter_mean"], yerr=hb["hb_jitter_std"].fillna(0),
                 fmt="-^", color="forestgreen", capsize=3, linewidth=2, label="Jitter HEARTBEAT (trục phải)")
    b_rtt = _baseline_value(baseline_summary, "rtt_jitter_mean")
    b_hb = _baseline_value(baseline_summary, "hb_jitter_mean")
    if b_rtt is not None:
        ax.axhline(y=b_rtt, color="darkorange", linestyle="--", alpha=0.6, label=f"Baseline RTT ({b_rtt:.2f} ms)")
    if b_hb is not None:
        ax2.axhline(y=b_hb, color="forestgreen", linestyle="--", alpha=0.6, label=f"Baseline HEARTBEAT ({b_hb:.1f} ms)")
    ax.set_title(title, fontweight="bold")
    ax.set_xlabel("Khoảng cách (m)")
    ax.set_ylabel("Jitter RTT (ms)", color="darkorange")
    ax2.set_ylabel("Jitter HEARTBEAT (ms)", color="forestgreen")
    ax.grid(True, linestyle=":", alpha=0.6)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=8)


def draw_lost_events(ax, wifi_summary: pd.DataFrame, baseline_summary: pd.DataFrame, title: str):
    """(d) Số lần mất liên lạc (quá 3 s không có HEARTBEAT) trung bình mỗi lần chạy 60 s, thanh sai số = độ lệch chuẩn 3 lần."""
    ax.bar(wifi_summary["distance"], wifi_summary["lost_events_mean"], width=4, color="purple", alpha=0.7,
           yerr=wifi_summary["lost_events_std"].fillna(0), capsize=4, label="Trung bình mỗi lần chạy (± độ lệch chuẩn)")
    b = _baseline_value(baseline_summary, "lost_events_mean")
    if b is not None:
        ax.axhline(y=b, color="gray", linestyle="--", label=f"Baseline ({b:.1f} lần)")
    ax.set_title(title, fontweight="bold")
    ax.set_xlabel("Khoảng cách (m)")
    ax.set_ylabel("Số lần mất liên lạc / lần chạy")
    ax.grid(True, linestyle=":", alpha=0.6)
    ax.legend(loc="upper left", fontsize=8)


def plot_metrics(df: pd.DataFrame, summary_df: pd.DataFrame, out_dir: str):
    """Vẽ các đồ thị định lượng theo yêu cầu của AC2."""
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial"]
    plt.rcParams["axes.unicode_minus"] = False

    # Lọc riêng baseline (distance == 0) và khoảng cách Wi-Fi (distance > 0)
    wifi_df = df[df["distance"] > 0]
    wifi_summary = summary_df[summary_df["distance"] > 0]
    baseline_summary = summary_df[summary_df["distance"] == 0]

    baseline_loss = baseline_summary["loss_mean"].values[0] if len(baseline_summary) > 0 else None
    baseline_rtt = baseline_summary["rtt_mean"].values[0] if len(baseline_summary) > 0 else None
    baseline_rtt_jit = baseline_summary["rtt_jitter_mean"].values[0] if len(baseline_summary) > 0 else None

    # 1. Đồ thị Tỷ lệ mất gói theo khoảng cách
    plt.figure(figsize=(8, 5))
    if baseline_loss is not None:
        plt.axhline(y=baseline_loss, color="gray", linestyle="--", label=f"Baseline ({baseline_loss:.1f}%)")
    
    # Scatter từng lần đo để thể hiện độ phân tán
    plt.scatter(wifi_df["distance"], wifi_df["loss_percent"], color="crimson", alpha=0.6, label="Các lần đo (r1..r3)")
    # Đường trung bình có thanh sai số std
    plt.errorbar(
        wifi_summary["distance"],
        wifi_summary["loss_mean"],
        yerr=wifi_summary["loss_std"].fillna(0),
        fmt="-o",
        color="firebrick",
        capsize=4,
        linewidth=2,
        label="Trung bình",
    )
    plt.title("Tỷ lệ mất gói MAVLink theo khoảng cách (802.11g ns-3)", fontsize=13, fontweight="bold")
    plt.xlabel("Khoảng cách giữa Trạm và Rover (m)", fontsize=11)
    plt.ylabel("Tỷ lệ mất gói (%)", fontsize=11)
    plt.ylim(-2, 105)
    plt.grid(True, linestyle=":", alpha=0.6)
    plt.legend(loc="upper left")
    plt.tight_layout()
    loss_png = os.path.join(out_dir, "loss_vs_distance.png")
    plt.savefig(loss_png, dpi=300)
    plt.close()
    print(f"[OK] Đã lưu biểu đồ: {loss_png}")

    # 2. Đồ thị RTT trung bình và RTT p95 theo khoảng cách
    plt.figure(figsize=(8, 5))
    if baseline_rtt is not None:
        plt.axhline(y=baseline_rtt, color="gray", linestyle="--", label=f"Baseline RTT ({baseline_rtt:.1f} ms)")
    
    valid_rtt_summary = wifi_summary.dropna(subset=["rtt_mean"])
    plt.errorbar(
        valid_rtt_summary["distance"],
        valid_rtt_summary["rtt_mean"],
        yerr=valid_rtt_summary["rtt_std"].fillna(0),
        fmt="-s",
        color="royalblue",
        capsize=4,
        linewidth=2,
        label="RTT trung bình (ms)",
    )
    if "rtt_p95_mean" in valid_rtt_summary.columns:
        plt.plot(
            valid_rtt_summary["distance"],
            valid_rtt_summary["rtt_p95_mean"],
            "--^",
            color="navy",
            linewidth=1.8,
            label="RTT percentile 95% (ms)",
        )
    plt.title("Độ trễ khứ hồi RTT theo khoảng cách", fontsize=13, fontweight="bold")
    plt.xlabel("Khoảng cách (m)", fontsize=11)
    plt.ylabel("Độ trễ RTT (ms)", fontsize=11)
    plt.grid(True, linestyle=":", alpha=0.6)
    plt.legend(loc="upper left")
    plt.tight_layout()
    rtt_png = os.path.join(out_dir, "rtt_vs_distance.png")
    plt.savefig(rtt_png, dpi=300)
    plt.close()
    print(f"[OK] Đã lưu biểu đồ: {rtt_png}")

    # 3. Đồ thị Jitter RTT và Jitter HEARTBEAT (hai trục y)
    fig, ax = plt.subplots(figsize=(8, 5))
    draw_jitter(ax, wifi_summary, baseline_summary, "Độ biến thiên trễ (Jitter) theo khoảng cách")
    fig.tight_layout()
    jit_png = os.path.join(out_dir, "jitter_vs_distance.png")
    fig.savefig(jit_png, dpi=300)
    plt.close(fig)
    print(f"[OK] Đã lưu biểu đồ: {jit_png}")

    # 3b. Đồ thị số lần mất liên lạc
    fig, ax = plt.subplots(figsize=(8, 5))
    draw_lost_events(ax, wifi_summary, baseline_summary, "Số lần mất liên lạc (quá 3 s không có HEARTBEAT)")
    fig.tight_layout()
    lost_png = os.path.join(out_dir, "lost_events_vs_distance.png")
    fig.savefig(lost_png, dpi=300)
    plt.close(fig)
    print(f"[OK] Đã lưu biểu đồ: {lost_png}")

    # 4. Hình ghép 2x2 tổng hợp cho Báo cáo (Combined 4-panel)
    fig, axs = plt.subplots(2, 2, figsize=(13, 9))
    
    # Panel (a) Loss Rate
    if baseline_loss is not None:
        axs[0, 0].axhline(y=baseline_loss, color="gray", linestyle="--", label=f"Baseline ({baseline_loss:.1f}%)")
    axs[0, 0].errorbar(
        wifi_summary["distance"],
        wifi_summary["loss_mean"],
        yerr=wifi_summary["loss_std"].fillna(0),
        fmt="-o", color="crimson", capsize=3, label="Mất gói (%)"
    )
    axs[0, 0].set_title("(a) Tỷ lệ mất gói MAVLink (%)", fontweight="bold")
    axs[0, 0].set_xlabel("Khoảng cách (m)")
    axs[0, 0].set_ylabel("Mất gói (%)")
    axs[0, 0].set_ylim(-2, 105)
    axs[0, 0].grid(True, linestyle=":", alpha=0.6)
    axs[0, 0].legend()

    # Panel (b) RTT
    if baseline_rtt is not None:
        axs[0, 1].axhline(y=baseline_rtt, color="gray", linestyle="--", label=f"Baseline ({baseline_rtt:.1f} ms)")
    axs[0, 1].errorbar(
        valid_rtt_summary["distance"],
        valid_rtt_summary["rtt_mean"],
        yerr=valid_rtt_summary["rtt_std"].fillna(0),
        fmt="-s", color="royalblue", capsize=3, label="RTT trung bình (ms)"
    )
    if "rtt_p95_mean" in valid_rtt_summary.columns:
        axs[0, 1].plot(valid_rtt_summary["distance"], valid_rtt_summary["rtt_p95_mean"], "--^", color="navy", label="RTT p95 (ms)")
    axs[0, 1].set_title("(b) Độ trễ khứ hồi RTT (ms)", fontweight="bold")
    axs[0, 1].set_xlabel("Khoảng cách (m)")
    axs[0, 1].set_ylabel("RTT (ms)")
    axs[0, 1].grid(True, linestyle=":", alpha=0.6)
    axs[0, 1].legend()

    # Panel (c) Jitter và (d) Số lần mất liên lạc
    draw_jitter(axs[1, 0], wifi_summary, baseline_summary, "(c) Độ biến động (Jitter)")
    draw_lost_events(axs[1, 1], wifi_summary, baseline_summary, "(d) Số lần mất liên lạc (Heartbeat timeout)")

    plt.tight_layout()
    combined_png = os.path.join(out_dir, "combined_metrics.png")
    plt.savefig(combined_png, dpi=300)
    plt.close()
    print(f"[OK] Đã lưu biểu đồ tổng hợp 4 đồ thị: {combined_png}")


def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    df = load_data(args.summary_file)
    summary_df = generate_summary_table(df, args.out_dir)
    plot_metrics(df, summary_df, args.out_dir)
    print("\n[HOÀN TẤT] Quá trình phân tích và vẽ biểu đồ kết thúc thành công.")


if __name__ == "__main__":
    main()
