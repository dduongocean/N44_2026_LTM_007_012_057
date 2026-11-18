#!/usr/bin/env python3
"""Tính lại mọi bảng số dùng trong mục 4 và mục 6 của báo cáo, từ file dữ liệu gốc.

Mục đích: báo cáo không chép số tính tay; mỗi bảng trong docs/report/noi-dung/04-*.txt và 06-*.txt
phải khớp với output của script này. Chạy từ thư mục repo:
    venv/bin/python analysis/report_tables.py            # in ra màn hình và ghi analysis/report_tables.txt

Nguồn: data/summary.csv, data/raw/<nhãn>.csv, data/nofading/summary.csv, data/failsafe_summary.csv,
data/failsafe/<nhãn>_pose.csv / _events.csv / _netem.csv, docs/evidence/net-03-wifi-80m.pcap.
"""

import collections
import io
import math
import os
import struct
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = io.StringIO()


def say(text=""):
    print(text)
    OUT.write(text + "\n")


def path(*p):
    return os.path.join(ROOT, *p)


# ---------------------------------------------------------------- mô hình (mục 4)
PTX, L0, N_EXP, M, THETA, K = 16.0, 40.046, 3.0, 1.5, -82.0, 7


def gamma_p(a, x):
    """Hàm Gamma không đầy đủ chuẩn hóa P(a, x) (chuỗi lũy thừa)."""
    if x <= 0:
        return 0.0
    s = t = 1.0 / a
    n = 0
    while True:
        n += 1
        t *= x / (a + n)
        s += t
        if t < 1e-15 * s:
            break
    return s * math.exp(-x + a * math.log(x) - math.lgamma(a))


def model_tables():
    say("== MỤC 4: bảng 4.2–4.4 (mô hình)")
    say("d (m) | P̄rx (dBm) | x(d) | p(d) | P_mac=p^7 (%) | E[N_tx] chỉ mất khung | E[N_tx] tính cả mất ACK")
    for d in (10, 40, 50, 60, 70, 80, 85, 90, 100):
        prx = PTX - (L0 + 10 * N_EXP * math.log10(d))
        x = 10 ** ((THETA - prx) / 10)
        p = gamma_p(M, M * x)
        q = 1 - (1 - p) ** 2                    # lần phát thất bại nếu mất khung HOẶC mất ACK
        en = (1 - p ** K) / (1 - p) if p < 1 else K
        en_ack = (1 - q ** K) / (1 - q) if q < 1 else K
        say(f"{d:5d} | {prx:8.2f} | {x:5.3f} | {p:5.3f} | {p ** K * 100:9.3f} | {en:5.2f} | {en_ack:5.2f}")
    for l0 in (40.046, 46.6777):
        say(f"d* (L0 = {l0} dB) = {10 ** ((PTX - l0 - THETA) / (10 * N_EXP)):.2f} m")
    say()


# ---------------------------------------------------------------- thí nghiệm A (mục 6)
def sweep_tables():
    d = pd.read_csv(path("data", "summary.csv"))
    ref = (d[d.distance == 10].rx / d[d.distance == 10].duration).mean()
    rows = []
    for _, r in d.iterrows():
        x = pd.read_csv(path("data", "raw", f"{r.label}.csv"), comment="#")
        t_first = x[x.link_state != "WAITING"].t.min()          # giây đầu tiên đã có HEARTBEAT
        t_count = r.duration - (t_first - 1)                    # khoảng thời gian chương trình có đếm seq
        rows.append(dict(
            label=r.label, d=r.distance, L=(r.lost / (r.rx + r.lost) * 100 if r.rx + r.lost else 100.0), R=r.rx / r.duration,   # không dùng loss_rate vì đã làm tròn 4 chữ số
            LRw=(1 - r.rx / (ref * t_count)) * 100, recv=r.rx / (ref * t_count) * 100,
            rtt=r.rtt_mean_ms, p95=r.rtt_p95_ms, jr=r.rtt_jitter_ms, jh=r.hb_jitter_ms, E=int(r.lost_events),
            tmat=int(((x.link_state == "LOST") | (x.link_state == "WAITING")).sum()),
            wait0=int(t_first - 1), pl=r.probes_lost / x.probes_sent.iloc[-1] * 100,
            res=int(x.resyncs.iloc[-1])))
    t = pd.DataFrame(rows)
    ms = lambda c, k=2: t.groupby("d")[c].agg(lambda s: f"{s.mean():.{k}f} ± {s.std():.{k}f}")
    say(f"== MỤC 6: bảng 6.2 (R_ref = {ref:.1f} bản tin/s ở 10 m; L_R và tỷ lệ nhận tính trên khoảng có đếm, tức từ HEARTBEAT đầu tiên)")
    tab = pd.DataFrame({"L%": ms("L"), "L_R%": ms("LRw", 1), "R/s": ms("R", 1), "RTT ms": ms("rtt"),
                        "p95": t.groupby("d").p95.mean().round(2), "J_RTT": t.groupby("d").jr.mean().round(2),
                        "J_HB": t.groupby("d").jh.mean().round(1), "probe mất%": ms("pl", 1),
                        "E": t.groupby("d").E.apply(lambda s: "/".join(map(str, s))),
                        "T_mất s": ms("tmat", 1), "chờ HB đầu (s)": t.groupby("d").wait0.apply(lambda s: "/".join(map(str, s))),
                        "resync": t.groupby("d").res.sum(), "nhận%": t.groupby("d").recv.mean().round(1)})
    say(tab.to_string())
    say(f"|L − L_R| lớn nhất (70–100 m, cùng khoảng đếm) = {(t[t.d >= 70].L - t[t.d >= 70].LRw).abs().max():.2f} điểm %")
    say(f"tổng resync loạt A = {t.res.sum()} (ở 70–100 m: {t[t.d >= 70].res.sum()})")
    say()
    say("== MỤC 6: bảng 6.5 (xếp loại) và khoảng ngưỡng")
    for dd, g in t[t.d > 0].groupby("d"):
        cls = "KHÔNG TIN CẬY" if g.E.max() >= 1 else ("TIN CẬY" if (g.L < 1).all() and (g.p95 < 100).all() else "SUY GIẢM")
        say(f"{dd:5.0f} m | E max {g.E.max()} | L max {g.L.max():.3f}% | p95 max {g.p95.max():.2f} ms | {cls}")
    near, at70 = t[(t.d > 0) & (t.d <= 60)], t[t.d == 70]
    say(f"60 m giữ TIN CẬY cần: ngưỡng mất gói > {near.L.max():.3f}% VÀ ngưỡng p95 > {near.p95.max():.2f} ms")
    say(f"70 m giữ SUY GIẢM cần: ngưỡng mất gói < {at70.L.max():.2f}% HOẶC ngưỡng p95 < {at70.p95.max():.2f} ms")
    say()
    return ref


# ---------------------------------------------------------------- thí nghiệm B
def nofading_table(ref):
    nf = pd.read_csv(path("data", "nofading", "summary.csv"))
    nf = nf[nf.duration >= 59]                                    # bỏ lần thử bị dừng (14,7 s)
    say("== MỤC 6: bảng 6.4, kênh không fading (1 lần mỗi mức)")
    for _, r in nf.iterrows():
        say(f"{r.distance:5.0f} m | rx {r.rx:6d} | L {r.loss_rate * 100:6.2f}% | RTT {r.rtt_mean_ms} ms")
    say()


# ---------------------------------------------------------------- thí nghiệm C
def failsafe_tables():
    s = pd.read_csv(path("data", "failsafe_summary.csv"))
    say("== MỤC 6: bảng 6.6 (thí nghiệm C)")
    say(s.groupby("scenario")[["v0_mps", "t_brake_s", "d_max_m", "t_stop_s", "d_stop_m", "t_move_again_s"]]
        .agg(["mean", "std"]).round(3).to_string())
    for lab in s.label:
        ev = dict(pd.read_csv(path("data", "failsafe", f"{lab}_events.csv")).values.tolist())
        nf = path("data", "failsafe", f"{lab}_netem.csv")
        if os.path.exists(nf):
            ev.update(dict(pd.read_csv(nf).values.tolist()))
        t0 = ev["t0"]
        p = pd.read_csv(path("data", "failsafe", f"{lab}_pose.csv"))
        modes = p[(p.text == "MODE") & (p.t > t0)]
        seq = ", ".join(f"{r.mode}/{r.armed} {r.t - t0:+.2f}" for r in modes.itertuples())
        pos = p.dropna(subset=["speed"]).sort_values("t")
        b = pos[(pos.t >= t0 - 1) & (pos.t < t0)]
        v_pos = math.hypot(b.x.iloc[-1] - b.x.iloc[0], b.y.iloc[-1] - b.y.iloc[0]) / (b.t.iloc[-1] - b.t.iloc[0])
        v0 = pos[(pos.t >= t0 - 0.5) & (pos.t < t0)].speed.mean()
        dec = pos[(pos.t >= t0) & (pos.speed < 0.95 * v0)].t.min() - t0
        vret = pos[(pos.t > t0 + 6) & (pos.t < t0 + 12.5)].speed.max()     # lúc tự chạy về (Return)
        say(f"{lab}: v0 báo {v0:.2f} | v0 theo vị trí (1 s) {v_pos:.2f} | vận tốc dưới 95% v0 tại {dec:.2f} s | "
            f"vận tốc lớn nhất khi Return {vret:.2f} | {seq}")
    say()


# ---------------------------------------------------------------- pcap 80 m
def pcap_80m():
    f = path("docs", "evidence", "net-03-wifi-80m.pcap")
    d = open(f, "rb").read()
    o, frames, t0, t1 = 24, [], None, None
    while o + 16 <= len(d):
        ts, us, cl, _ = struct.unpack("<IIII", d[o:o + 16])
        pkt = d[o + 16:o + 16 + cl]
        o += 16 + cl
        t = ts + us / 1e6
        t0, t1 = t0 or t, t
        rl = struct.unpack("<H", pkt[2:4])[0]
        fr = pkt[rl:]
        if len(fr) < 24 or (fr[0] >> 2) & 3 != 2 or fr[10:16] != bytes.fromhex("020000000002"):
            continue
        frames.append((struct.unpack("<H", fr[22:24])[0] >> 4, bool(fr[1] & 0x08), len(fr)))
    groups, prev = [], None
    for seq, retry, _ in frames:
        if prev is not None and seq == prev and retry:
            groups[-1] += 1
        else:
            groups.append(1)
        prev = seq
    dur, n = t1 - t0, len(groups)
    c = collections.Counter(groups)
    air = sum(20 + ((16 + 8 * ln + 6 + 23) // 24) * 4 for _, _, ln in frames)   # µs, ERP-OFDM 6 Mbit/s
    say("== MỤC 6: pcap 80 m phía xe (docs/evidence/net-03-wifi-80m.pcap)")
    say(f"thời lượng {dur:.1f} s | lần phát {len(frames)} | khung khác nhau {n} ({n / dur:.1f}/s) | "
        f"trung bình {len(frames) / n:.2f} lần phát/khung | chạm 7 lần {c[7] / n * 100:.1f}% | phân bố {dict(sorted(c.items()))}")
    say(f"thời gian phát khung dữ liệu ≈ {air / 1e6 / dur * 100:.1f}% thời gian (chưa tính ACK, SIFS, chờ ngẫu nhiên)")
    say()


if __name__ == "__main__":
    model_tables()
    ref = sweep_tables()
    nofading_table(ref)
    failsafe_tables()
    pcap_80m()
    with open(path("analysis", "report_tables.txt"), "w", encoding="utf-8") as fh:
        fh.write("# Sinh bởi analysis/report_tables.py – không sửa tay\n" + OUT.getvalue())
    print("[OK] analysis/report_tables.txt", file=sys.stderr)
