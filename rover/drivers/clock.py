"""Tầng 4 – đồng hồ hệ thống (hiện thực Clock)."""

import time


class SystemClock:
    """Đồng hồ hệ thống chỉ tăng, không phụ thuộc giờ lịch."""

    def now (self) -> float:
        """Trả thời gian hiện tại theo giây từ time.monotonic ()."""
        return time .monotonic ()
