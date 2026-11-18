"""Vẽ thêm 2 hình cho mục 6 của báo cáo (bổ sung cho plot_results.py của NET-03/T3, không thay thế):

1. analysis/throughput_vs_distance.png: số bản tin MAVLink nhận được mỗi giây (chiều xe -> trạm) theo khoảng cách,
   trung bình ± độ lệch chuẩn 3 lần, có điểm từng lần và đường baseline. Đọc data/summary.csv.
2. analysis/fading_vs_nofading_loss.png: tỷ lệ mất gói theo khoảng cách, CÙNG L0 = 40.046 dB: kênh có fading
   (loạt chính, data/summary.csv) và kênh không fading (data/nofading/summary.csv, chạy bằng
   NS3_ARGS="--fading=false" tools/run_sweep.sh ...), kèm ngưỡng tính tay 85.47 m.

Cách chạy (từ thư mục repo): venv/bin/python analysis/plot_report_extras.py
Bảng số của hình 1 ghi ra analysis/throughput_table.csv.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
MAIN_SUMMARY = ROOT / "data" / "summary.csv"
NOFADING_SUMMARY = ROOT / "data" / "nofading" / "summary.csv"
OUT_DIR = ROOT / "analysis"

# Màu theo thứ tự cố định (slot 1 xanh, slot 2 cam); chữ dùng màu chữ, không dùng màu series.
SERIES_1 = "#2a78d6"
SERIES_2 = "#eb6834"
TEXT_MUTED = "#5f5e57"
GRID = "#d9d8d2"
# Khoảng cách mà công suất thu = -82 dBm khi không fading: 16 - (40.046 + 30 log10 d) = -82 (calibration.txt mục 6).
NOFADING_CLIFF_M = 85.47


def load_summary(path: Path) -> pd.DataFrame:
    """Đọc summary, chỉ giữ nhãn baseline_rN / dXXX_rN; nhãn trùng thì giữ lần ghi sau cùng (như plot_results.py)."""
    df = pd.read_csv(path)
    df = df[df["label"].astype(str).str.match(r"^(baseline_r\d+|d\d+_r\d+)$")]
    return df.drop_duplicates(subset="label", keep="last").copy()


def style_axes(ax) -> None:
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(TEXT_MUTED)
    ax.tick_params(colors=TEXT_MUTED)


def plot_throughput(df: pd.DataFrame) -> pd.DataFrame:
    df["rx_per_s"] = df["rx"] / df["duration"]
    base = df[df["label"].str.startswith("baseline")]
    wifi = df[df["label"].str.startswith("d")]
    table = wifi.groupby("distance")["rx_per_s"].agg(["mean", "std", "count"]).reset_index()

    fig, ax = plt.subplots(figsize=(8, 5))
    style_axes(ax)
    if len(base) > 0:
        b = base["rx_per_s"].mean()
        ax.axhline(b, color=TEXT_MUTED, linestyle="--", linewidth=1.5)
        ax.text(101, b + 6, f"baseline\n{b:.0f} bản tin/s", va="bottom", fontsize=9, color=TEXT_MUTED)
    ax.scatter(wifi["distance"], wifi["rx_per_s"], s=22, color=SERIES_1, alpha=0.35, linewidths=0,
               label="từng lần đo (r1–r3)")
    ax.errorbar(table["distance"], table["mean"], yerr=table["std"].fillna(0), fmt="-o", color=SERIES_1,
                linewidth=2, markersize=6, capsize=3, label="trung bình ± độ lệch chuẩn")
    for _, row in table.iterrows():
        if row["distance"] >= 70:
            ax.annotate(f"{row['mean']:.0f}", (row["distance"], row["mean"]), textcoords="offset points",
                        xytext=(6, 6), fontsize=9, color="#1f1f1c")
    ax.set_xlabel("Khoảng cách trạm – xe trong ns-3 (m)")
    ax.set_ylabel("Bản tin MAVLink nhận được mỗi giây (xe → trạm)")
    ax.set_title("Thông lượng nhận theo khoảng cách (kênh có fading, 3 lần × 60 s mỗi mức)")
    ax.set_xlim(0, 112)
    ax.set_ylim(0, None)
    ax.legend(loc="lower left", frameon=False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "throughput_vs_distance.png", dpi=300)
    plt.close(fig)

    out = table.rename(columns={"mean": "rx_per_s_mean", "std": "rx_per_s_std", "count": "runs"})
    if len(base) > 0:
        out = pd.concat([pd.DataFrame([{"distance": 0.0, "rx_per_s_mean": base["rx_per_s"].mean(),
                                        "rx_per_s_std": base["rx_per_s"].std(), "runs": len(base)}]), out])
    out.round(1).to_csv(OUT_DIR / "throughput_table.csv", index=False)
    return out


def loss_by_distance(df: pd.DataFrame) -> pd.DataFrame:
    wifi = df[df["label"].str.startswith("d")].copy()
    wifi["loss_pct"] = wifi["loss_rate"] * 100
    return wifi.groupby("distance")["loss_pct"].agg(["mean", "std"]).reset_index()


def plot_fading_compare(main: pd.DataFrame, nofading: pd.DataFrame) -> None:
    fad = loss_by_distance(main)
    nof = loss_by_distance(nofading)

    fig, ax = plt.subplots(figsize=(8, 5))
    style_axes(ax)
    ax.axvline(NOFADING_CLIFF_M, ymax=0.8, color=TEXT_MUTED, linestyle=":", linewidth=1.5)
    ax.text(NOFADING_CLIFF_M + 1.2, 40, f"ngưỡng tính tay\nkhi không fading\n{NOFADING_CLIFF_M} m", fontsize=9,
            color=TEXT_MUTED, ha="left")
    ax.plot(nof["distance"], nof["mean"], "-s", color=SERIES_2, linewidth=2, markersize=6,
            label="không fading (1 lần × 60 s mỗi mức)")
    ax.errorbar(fad["distance"], fad["mean"], yerr=fad["std"].fillna(0), fmt="-o", color=SERIES_1, linewidth=2,
                markersize=6, capsize=3, label="fading Nakagami m = 1.5 (3 lần × 60 s, ± độ lệch chuẩn)")
    # Nhãn trực tiếp (chữ màu chữ, không dùng màu series)
    last_nof = nof.iloc[-1]
    ax.annotate("không fading", (last_nof["distance"], last_nof["mean"]), textcoords="offset points",
                xytext=(-14, 7), ha="right", fontsize=9, color="#1f1f1c")
    ax.annotate("có fading", (fad["distance"].iloc[-1], fad["mean"].iloc[-1]), textcoords="offset points",
                xytext=(8, -4), ha="left", fontsize=9, color="#1f1f1c")
    ax.set_xlabel("Khoảng cách trạm – xe trong ns-3 (m)")
    ax.set_ylabel("Tỷ lệ mất gói chiều xe → trạm (%)")
    ax.set_title("Cùng suy hao (L0 = 40.05 dB): không fading đứt gọn, có fading suy giảm dần")
    ax.set_xlim(0, 115)
    ax.set_ylim(-3, 105)
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    fig.text(0.01, 0.01, "Không fading: kênh tất định, chỉ đo 70–90 m (dưới 70 m công suất thu còn cao hơn nên theo tính toán là 0%). "
             "85 m: 0% mất; 86 m: 100% mất.", fontsize=8, color=TEXT_MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(OUT_DIR / "fading_vs_nofading_loss.png", dpi=300)
    plt.close(fig)


def main() -> None:
    main_df = load_summary(MAIN_SUMMARY)
    table = plot_throughput(main_df)
    print("Thông lượng nhận (bản tin/s), distance 0 = baseline:")
    print(table.round(1).to_string(index=False))
    plot_fading_compare(main_df, load_summary(NOFADING_SUMMARY))
    print("Đã ghi analysis/throughput_vs_distance.png, analysis/fading_vs_nofading_loss.png, analysis/throughput_table.csv")


if __name__ == "__main__":
    main()
