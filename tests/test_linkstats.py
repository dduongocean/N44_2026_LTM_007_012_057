"""Kiểm tra tầng 2 – đếm mất gói theo số hiệu tuần tự (SeqTracker)."""

import pytest

from rover .core .linkstats import SeqTracker


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
