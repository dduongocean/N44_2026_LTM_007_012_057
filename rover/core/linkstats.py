"""Tầng 2 – thống kê đường truyền: theo dõi số hiệu tuần tự (seq) để đếm gói mất.

File này thuộc tầng xử lý thuần, không import pymavlink hay time;
mọi dữ liệu đầu vào được truyền qua tham số.
"""

from __future__ import annotations


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
