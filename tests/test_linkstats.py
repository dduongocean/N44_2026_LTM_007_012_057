"""Kiểm tra tầng 2 – đếm mất gói theo số hiệu tuần tự (SeqTracker)."""

import pytest

from rover .core .linkstats import (
    IntervalStats,
    RttTracker,
    SeqTracker,
    calc_mean,
    calc_percentile,
    calc_stdev,
)


def test_1_initial_state ():
    # Đầu vào: SeqTracker mới tạo, chưa ghi nhận gói nào.
    tracker = SeqTracker ()

    # Mong đợi: received = 0, lost = 0, resyncs = 0, loss_rate = 0.0.
    assert tracker .received == 0
    assert tracker .lost == 0
    assert tracker .resyncs == 0
    assert tracker .loss_rate == 0.0


def test_2_continuous_sequence ():
    # Đầu vào: dãy 10 gói liên tục từ seq 0 đến 9 từ cùng một nguồn (1, 1).
    tracker = SeqTracker ()
    for seq in range (10):
        tracker .on_packet (1, 1, seq)

    # Mong đợi: received = 10, lost = 0, resyncs = 0, loss_rate = 0.0.
    assert tracker .received == 10
    assert tracker .lost == 0
    assert tracker .resyncs == 0
    assert tracker .loss_rate == 0.0


def test_3_sequence_wrap_around ():
    # Đầu vào: dãy seq qua mốc quay vòng 255 -> 0 (254, 255, 0, 1).
    tracker = SeqTracker ()
    for seq in [254, 255, 0, 1]:
        tracker .on_packet (1, 1, seq)

    # Mong đợi: không có gói mất khi seq quay vòng từ 255 về 0; lost = 0, resyncs = 0.
    assert tracker .received == 4
    assert tracker .lost == 0
    assert tracker .resyncs == 0
    assert tracker .loss_rate == 0.0


def test_4_single_gap ():
    # Đầu vào: gói seq 5 rồi đến seq 8 (bị mất gói 6 và 7).
    tracker = SeqTracker ()
    tracker .on_packet (1, 1, 5)
    tracker .on_packet (1, 1, 8)

    # Mong đợi: received = 2, lost = 2 (mất gói 6 và 7), resyncs = 0.
    assert tracker .received == 2
    assert tracker .lost == 2
    assert tracker .resyncs == 0
    assert tracker .loss_rate == 2 / 4


def test_5_gap_across_wrap ():
    # Đầu vào: khoảng trống qua mốc quay vòng: nhận seq 254 rồi nhận seq 1 (mất gói 255 và 0).
    tracker = SeqTracker ()
    tracker .on_packet (1, 1, 254)
    tracker .on_packet (1, 1, 1)

    # Mong đợi: lost = 2, received = 2, resyncs = 0.
    assert tracker .received == 2
    assert tracker .lost == 2
    assert tracker .resyncs == 0
    assert tracker .loss_rate == 2 / 4


def test_6_multiple_sources_interleaved ():
    # Đầu vào: hai nguồn xen kẽ (1, 1) và (1, 190), mỗi nguồn có chuỗi seq riêng biệt tự liên tục.
    tracker = SeqTracker ()
    for seq in range (5):
        tracker .on_packet (1, 1, seq)
        tracker .on_packet (1, 190, seq)

    # Mong đợi: đếm tách biệt theo từng nguồn, không coi việc xen kẽ là mất gói; lost = 0, resyncs = 0, received = 10.
    assert tracker .received == 10
    assert tracker .lost == 0
    assert tracker .resyncs == 0
    assert tracker .loss_rate == 0.0


def test_7_duplicate_or_out_of_order ():
    # Đầu vào: nhận gói 10 rồi nhận gói 9 (gói đến lùi seq / muộn) hoặc gói trùng 10.
    # Trường hợp A: lùi seq (10 rồi 9)
    tracker_a = SeqTracker ()
    tracker_a .on_packet (1, 1, 10)
    tracker_a .on_packet (1, 1, 9)

    # Mong đợi: resyncs = 1, lost = 0, received = 2.
    assert tracker_a .received == 2
    assert tracker_a .lost == 0
    assert tracker_a .resyncs == 1

    # Trường hợp B: gói trùng (10 rồi 10)
    tracker_b = SeqTracker ()
    tracker_b .on_packet (1, 1, 10)
    tracker_b .on_packet (1, 1, 10)

    # Mong đợi: resyncs = 1, lost = 0, received = 2.
    assert tracker_b .received == 2
    assert tracker_b .lost == 0
    assert tracker_b .resyncs == 1


def test_8_loss_rate_calculation ():
    # Đầu vào: kịch bản có đúng 90 gói nhận và 10 gói mất.
    # Gửi seq 0 (nhận 1, mất 0)
    # Gửi seq 11 (gap = 10 -> mất 10 gói: 1..10, nhận thêm 1 gói 11 -> tổng nhận 2, mất 10)
    # Gửi seq 12 đến 99 (88 gói liên tục -> tổng nhận 2 + 88 = 90, mất 10)
    tracker = SeqTracker ()
    tracker .on_packet (1, 1, 0)
    tracker .on_packet (1, 1, 11)
    for seq in range (12, 100):
        tracker .on_packet (1, 1, seq)

    # Mong đợi: received = 90, lost = 10, loss_rate = 10 / (90 + 10) = 0.1.
    assert tracker .received == 90
    assert tracker .lost == 10
    assert tracker .loss_rate == pytest .approx (0.1)


def test_9_rtt_basic_send_and_reply ():
    # Đầu vào: gửi probe 1 tại 1.0 s, nhận phản hồi tại 1.05 s.
    tracker = RttTracker (timeout_s = 2.0)
    tracker .on_probe_sent (probe_id = 1, now = 1.0)

    # Mong đợi: sent = 1, replied = 0, lost = 0
    assert tracker .sent == 1
    assert tracker .replied == 0
    assert tracker .lost == 0

    rtt = tracker .on_reply (probe_id = 1, now = 1.05)
    # Mong đợi: rtt = 0.05 s, replied = 1, lost = 0, samples = [0.05]
    assert rtt == pytest .approx (0.05)
    assert tracker .replied == 1
    assert tracker .lost == 0
    assert tracker .samples == [pytest .approx (0.05)]


def test_10_rtt_unknown_probe_returns_none ():
    # Đầu vào: nhận phản hồi probe_id lạ (chưa từng gửi hoặc trùng).
    tracker = RttTracker ()
    tracker .on_probe_sent (probe_id = 100, now = 1.0)

    # Nhận probe_id 999 chưa gửi
    rtt = tracker .on_reply (probe_id = 999, now = 1.1)
    assert rtt is None

    # Nhận probe_id 100 lần 1 -> trả rtt
    rtt1 = tracker .on_reply (probe_id = 100, now = 1.04)
    assert rtt1 == pytest .approx (0.04)

    # Nhận lại probe_id 100 lần 2 (trùng) -> trả None
    rtt2 = tracker .on_reply (probe_id = 100, now = 1.05)
    assert rtt2 is None


def test_11_rtt_timeout_expire_marks_lost ():
    # Đầu vào: gửi probe tại 0.0 s, timeout là 2.0 s.
    tracker = RttTracker (timeout_s = 2.0)
    tracker .on_probe_sent (probe_id = 1, now = 0.0)

    # Tại 1.5 s: chưa hết hạn
    assert tracker .expire (now = 1.5) == 0
    assert tracker .lost == 0

    # Tại 2.5 s: đã quá timeout 2.0 s -> tính là mất 1 probe
    assert tracker .expire (now = 2.5) == 1
    assert tracker .lost == 1

    # Nếu sau đó nhận được phản hồi muộn của probe này -> trả None
    rtt = tracker .on_reply (probe_id = 1, now = 2.6)
    assert rtt is None
    assert tracker .replied == 0


def test_12_rtt_interleaved_and_out_of_order_replies ():
    # Đầu vào: nhiều lần đo xen kẽ, nhận phản hồi khác thứ tự.
    tracker = RttTracker (timeout_s = 2.0)
    tracker .on_probe_sent (probe_id = 1, now = 1.00)
    tracker .on_probe_sent (probe_id = 2, now = 1.02)
    tracker .on_probe_sent (probe_id = 3, now = 1.04)

    # Nhận probe 2 trước: rtt = 1.06 - 1.02 = 0.04
    assert tracker .on_reply (probe_id = 2, now = 1.06) == pytest .approx (0.04)
    # Nhận probe 1: rtt = 1.07 - 1.00 = 0.07
    assert tracker .on_reply (probe_id = 1, now = 1.07) == pytest .approx (0.07)
    # Nhận probe 3: rtt = 1.08 - 1.04 = 0.04
    assert tracker .on_reply (probe_id = 3, now = 1.08) == pytest .approx (0.04)

    assert tracker .sent == 3
    assert tracker .replied == 3
    assert tracker .lost == 0
    assert len (tracker .samples) == 3


def test_13_interval_stats_heartbeat_jitter ():
    # Đầu vào 1: chưa có sự kiện hoặc chỉ có 1 mốc thời gian -> mean, stdev là None (chưa đủ 2 khoảng).
    stats = IntervalStats ()
    assert stats .count == 0
    assert stats .mean is None
    assert stats .stdev is None

    stats .on_event (now = 0.0)
    assert stats .count == 0
    assert stats .mean is None
    assert stats .stdev is None

    stats .on_event (now = 1.0)  # mới có 1 khoảng (1.0 - 0.0 = 1.0) -> chưa đủ 2 khoảng
    assert stats .count == 1
    assert stats .mean is None
    assert stats .stdev is None

    # Đầu vào 2: các mốc 0, 1, 2, 3 -> 3 khoảng cách đều 1.0 s
    stats2 = IntervalStats ()
    for t in [0.0, 1.0, 2.0, 3.0]:
        stats2 .on_event (now = t)
    assert stats2 .count == 3
    assert stats2 .mean == pytest .approx (1.0)
    assert stats2 .stdev == pytest .approx (0.0)

    # Đầu vào 3: các mốc 0, 1, 3 -> 2 khoảng: 1.0 và 2.0 s -> mean 1.5
    stats3 = IntervalStats ()
    for t in [0.0, 1.0, 3.0]:
        stats3 .on_event (now = t)
    assert stats3 .count == 2
    assert stats3 .mean == pytest .approx (1.5)
    assert stats3 .stdev is not None
    assert stats3 .stdev > 0.0


def test_14_stats_helpers_mean_stdev_percentile ():
    # Danh sách rỗng
    assert calc_mean ([]) is None
    assert calc_stdev ([]) is None
    assert calc_percentile ([], 95) is None

    # 1 phần tử
    assert calc_mean ([10.0]) == 10.0
    assert calc_stdev ([10.0]) is None
    assert calc_percentile ([10.0], 95) == 10.0

    # Dãy số thực: [10, 20, 30, 40, 50]
    vals = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert calc_mean (vals) == pytest .approx (30.0)
    # stdev sample: sqrt( (400 + 100 + 0 + 100 + 400) / 4 ) = sqrt(250) ≈ 15.811388
    assert calc_stdev (vals) == pytest .approx (15.811388, rel = 1e-4)
    # p95 nằm giữa 40 và 50
    p95 = calc_percentile (vals, 95)
    assert p95 is not None
    assert 40.0 <= p95 <= 50.0
