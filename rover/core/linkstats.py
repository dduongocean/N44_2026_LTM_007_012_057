"""Tầng 2 – thống kê đường truyền: theo dõi số hiệu tuần tự (seq) để đếm gói mất.

File này thuộc tầng xử lý thuần, không import pymavlink hay time;
mọi dữ liệu đầu vào được truyền qua tham số.
"""

from __future__ import annotations

import math


class SeqTracker:
    """Theo dõi trường seq của các gói MAVLink nhận được để tính số gói mất, gói nhận và tỷ lệ mất gói."""

    def __init__ (self) -> None:
        self ._received: int = 0
        self ._lost: int = 0
        self ._resyncs: int = 0
        # Ghi nhớ seq gần nhất của từng nguồn: (system_id, component_id) -> seq
        self ._last_seq: dict [tuple [int, int], int] = {}

    @property
    def received (self) -> int:
        """Số gói MAVLink đã nhận được."""
        return self ._received

    @property
    def lost (self) -> int:
        """Số gói MAVLink suy ra là bị mất từ khoảng trống seq."""
        return self ._lost

    @property
    def resyncs (self) -> int:
        """Số lần đứt quãng / gói trùng / gói đến sai thứ tự."""
        return self ._resyncs

    @property
    def loss_rate (self) -> float:
        """Tỷ lệ mất gói: lost / (received + lost); trả về 0.0 khi chưa có gói nào."""
        total = self ._received + self ._lost
        if total == 0:
            return 0.0
        return self ._lost / total

    def on_packet (self, system_id: int, component_id: int, seq: int) -> None:
        """Ghi nhận một gói MAVLink nhận được với system_id, component_id và seq."""
        self ._received += 1
        source = (system_id, component_id)

        if source not in self ._last_seq:
            self ._last_seq [source] = seq
            return

        prev_seq = self ._last_seq [source]
        # Số gói mất giữa hai gói liên tiếp theo modulo 256
        gap = (seq - prev_seq - 1) % 256

        if gap == 0:
            # Gói kế tiếp liên tục bình thường (không mất gói nào)
            pass
        elif gap < 128:
            # Khoảng trống hợp lệ: mất gap gói
            self ._lost += gap
        else:
            # Khoảng trống >= 128: không phân biệt được mất nhiều gói với gói trùng / đến muộn
            # Quy ước: tính là đứt quãng (resync), không cộng vào số mất
            self ._resyncs += 1

        self ._last_seq [source] = seq


def calc_mean (values: list [float]) -> float | None:
    """Tính giá trị trung bình (mean) của danh sách số. Trả None nếu danh sách rỗng."""
    if not values:
        return None
    return sum (values) / len (values)


def calc_stdev (values: list [float]) -> float | None:
    """Tính độ lệch chuẩn mẫu (sample standard deviation). Trả None nếu có ít hơn 2 phần tử."""
    if len (values) < 2:
        return None
    m = sum (values) / len (values)
    variance = sum ((x - m) ** 2 for x in values) / (len (values) - 1)
    return math .sqrt (variance)


def calc_percentile (values: list [float], p: float) -> float | None:
    """Tính phân vị thứ p (0 <= p <= 100), ví dụ p=95 (p95). Dùng nội suy tuyến tính, trả None nếu rỗng."""
    if not values:
        return None
    if len (values) == 1:
        return values [0]
    sorted_vals = sorted (values)
    k = (len (sorted_vals) - 1) * (p / 100.0)
    f = math .floor (k)
    c = math .ceil (k)
    if f == c:
        return sorted_vals [int (k)]
    d0 = sorted_vals [int (f)] * (c - k)
    d1 = sorted_vals [int (c)] * (k - f)
    return d0 + d1


class RttTracker:
    """Theo dõi các gói probe TIMESYNC để tính thời gian khứ hồi (RTT) và đếm gói probe mất."""

    def __init__ (self, timeout_s: float = 2.0) -> None:
        self ._timeout_s = timeout_s
        self ._pending: dict [int, float] = {}  # probe_id -> sent_time (now)
        self ._sent: int = 0
        self ._replied: int = 0
        self ._lost: int = 0
        self ._samples: list [float] = []

    @property
    def sent (self) -> int:
        """Tổng số gói probe đã gửi đi."""
        return self ._sent

    @property
    def replied (self) -> int:
        """Tổng số gói probe đã nhận được phản hồi hợp lệ."""
        return self ._replied

    @property
    def lost (self) -> int:
        """Tổng số gói probe bị quá hạn (hết thời gian chờ mà không có phản hồi)."""
        return self ._lost

    @property
    def samples (self) -> list [float]:
        """Danh sách các mẫu RTT đã đo được (tính bằng giây)."""
        return self ._samples

    def on_probe_sent (self, probe_id: int, now: float) -> None:
        """Ghi nhận vừa gửi một gói probe với mã probe_id tại thời điểm now."""
        self ._sent += 1
        self ._pending [probe_id] = now

    def on_reply (self, probe_id: int, now: float) -> float | None:
        """Ghi nhận nhận được phản hồi cho probe_id tại thời điểm now.

        Trả về RTT (giây) nếu probe_id hợp lệ và đang chờ; trả None nếu probe_id lạ hoặc đã hết hạn.
        """
        if probe_id not in self ._pending:
            return None
        sent_time = self ._pending .pop (probe_id)
        rtt = now - sent_time
        self ._replied += 1
        self ._samples .append (rtt)
        return rtt

    def expire (self, now: float) -> int:
        """Quét và hủy các probe đã chờ quá timeout_s giây tính đến thời điểm now.

        Cộng dồn vào số gói probe mất (lost) và trả về số gói vừa bị quá hạn trong lần gọi này.
        """
        expired_ids = [pid for pid, sent_time in self ._pending .items () if now - sent_time > self ._timeout_s]
        for pid in expired_ids:
            del self ._pending [pid]
        count = len (expired_ids)
        self ._lost += count
        return count


class IntervalStats:
    """Theo dõi khoảng thời gian giữa các sự kiện kế tiếp để tính jitter (độ lệch chuẩn khoảng cách)."""

    def __init__ (self) -> None:
        self ._last_event: float | None = None
        self ._intervals: list [float] = []

    @property
    def count (self) -> int:
        """Số lượng khoảng thời gian giữa hai sự kiện liên tiếp đã ghi nhận."""
        return len (self ._intervals)

    @property
    def mean (self) -> float | None:
        """Khoảng thời gian trung bình giữa các sự kiện. Trả None khi chưa đủ 2 khoảng đo."""
        if len (self ._intervals) < 2:
            return None
        return calc_mean (self ._intervals)

    @property
    def stdev (self) -> float | None:
        """Độ lệch chuẩn khoảng cách (jitter). Trả None khi chưa đủ 2 khoảng đo."""
        if len (self ._intervals) < 2:
            return None
        return calc_stdev (self ._intervals)

    def on_event (self, now: float) -> None:
        """Ghi nhận một sự kiện xảy ra tại thời điểm now."""
        if self ._last_event is not None:
            self ._intervals .append (now - self ._last_event)
        self ._last_event = now


def format_experiment_header (
    command: str,
    start_time: str,
    label: str,
    distance_m: float,
    duration_s: float,
    probe_hz: float,
) -> str:
    """Tạo các dòng chú thích ở đầu file CSV chi tiết theo yêu cầu NET-02."""
    lines = [
        f"# command: {command}",
        f"# start_time: {start_time}",
        f"# label: {label}",
        f"# distance_m: {distance_m:.1f}",
        f"# duration_s: {duration_s:.1f}",
        f"# probe_hz: {probe_hz:.1f}",
        "t,rx,lost,loss_rate,resyncs,probes_sent,probes_lost,rtt_mean_ms,rtt_p95_ms,rtt_jitter_ms,hb_jitter_ms,link_state,lost_events",
    ]
    return "\n" .join (lines) + "\n"


def format_experiment_row (
    t: float,
    rx: int,
    lost: int,
    loss_rate: float,
    resyncs: int,
    probes_sent: int,
    probes_lost: int,
    rtt_mean_ms: float | None,
    rtt_p95_ms: float | None,
    rtt_jitter_ms: float | None,
    hb_jitter_ms: float | None,
    link_state: str,
    lost_events: int,
) -> str:
    """Tạo một dòng dữ liệu mỗi giây cho file CSV chi tiết."""
    def _fmt (val: float | None) -> str:
        return f"{val:.2f}" if val is not None else ""

    return (
        f"{t:.1f},{rx},{lost},{loss_rate:.4f},{resyncs},{probes_sent},{probes_lost},"
        f"{_fmt (rtt_mean_ms)},{_fmt (rtt_p95_ms)},{_fmt (rtt_jitter_ms)},"
        f"{_fmt (hb_jitter_ms)},{link_state},{lost_events}\n"
    )


def format_summary_header () -> str:
    """Tiêu đề cho file data/summary.csv."""
    return "label,distance,duration,rx,lost,loss_rate,rtt_mean_ms,rtt_p95_ms,rtt_jitter_ms,hb_jitter_ms,probes_lost,lost_events\n"


def format_summary_row (
    label: str,
    distance: float,
    duration: float,
    rx: int,
    lost: int,
    loss_rate: float,
    rtt_mean_ms: float | None,
    rtt_p95_ms: float | None,
    rtt_jitter_ms: float | None,
    hb_jitter_ms: float | None,
    probes_lost: int,
    lost_events: int,
) -> str:
    """Tạo một dòng tổng kết cho data/summary.csv."""
    def _fmt (val: float | None) -> str:
        return f"{val:.2f}" if val is not None else ""

    return (
        f"{label},{distance:.1f},{duration:.1f},{rx},{lost},{loss_rate:.4f},"
        f"{_fmt (rtt_mean_ms)},{_fmt (rtt_p95_ms)},{_fmt (rtt_jitter_ms)},"
        f"{_fmt (hb_jitter_ms)},{probes_lost},{lost_events}\n"
    )
