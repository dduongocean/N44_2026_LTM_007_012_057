"""Tầng 3 – trừu tượng: các interface giữa chương trình đo và driver (VehicleLink, Clock). Giống HAL trên STM32: chương trình đo gọi các hàm ở đây mà không biết bên dưới là MAVLink hay đồng hồ thật; test truyền vào bản giả lập. File này chỉ có chữ ký hàm, không có xử lý."""

# Cho phép ghi kiểu ở dạng chuỗi được đánh giá muộn (ví dụ list [VehicleEvent]) mà không cần đúng thứ tự khai báo.
from __future__ import annotations

# Protocol: khai báo interface chỉ gồm chữ ký hàm. Lớp nào có đủ các hàm đúng tên và tham số thì dùng thay được, không cần kế thừa; giống một struct gồm các con trỏ hàm trong C.
from typing import Protocol

from rover .core .model import VehicleEvent


class VehicleLink (Protocol):
    """Kênh nói chuyện với xe. Hiện thực thật: MavlinkVehicleLink; giả lập trong test: FakeVehicleLink."""

    def poll (self) -> list [VehicleEvent]:
        """Đọc mọi gói đang chờ, không chờ gói mới; chỉ trả gói của xe (bỏ gói autopilot = INVALID như QGroundControl); không có gói nào thì trả danh sách rỗng."""
        ...

    def send_arm (self, arm: bool) -> None:
        """Gửi lệnh mở khóa (arm = True) hoặc khóa (arm = False) tới xe đã thấy gần nhất; xe trả lời sau, qua ArmAck trong poll ()."""
        ...

    def send_drive (self, forward: float, turn: float) -> None:
        """Gửi mức lái tới xe đã thấy gần nhất: forward trong [-1, 1] (dương là tiến, âm là lùi), turn trong [-1, 1] (dương là quay phải, âm là quay trái); chưa thấy xe thì không gửi. Phải gửi đều đặn, xe chỉ chạy khi đang ở chế độ Manual và đã mở khóa."""
        ...

    def send_manual_mode (self) -> None:
        """Yêu cầu xe đã thấy gần nhất chuyển sang chế độ Manual để nhận lệnh lái; chưa thấy xe thì không gửi."""
        ...

    def close (self) -> None:
        """Đóng cổng kết nối."""
        ...


class Clock (Protocol):
    """Đồng hồ. Hiện thực thật: SystemClock (rover/drivers/clock.py); giả lập trong test: FakeClock."""

    def now (self) -> float:
        """Thời điểm hiện tại tính bằng giây, chỉ tăng (không lùi khi đổi giờ hệ thống)."""
        ...