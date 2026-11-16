"""Giả lập tầng 3 dùng trong test: đồng hồ và kênh xe."""

from rover .core .model import VehicleEvent


class FakeClock:
    """Đồng hồ giả lập có thể tăng thời gian theo yêu cầu."""

    def __init__ (self, start: float = 0.0) -> None:
        self ._time = start

    def now (self) -> float:
        """Trả thời gian giả lập hiện tại."""
        return self ._time

    def advance (self, seconds: float) -> None:
        """Tăng thời gian giả lập."""
        self ._time += seconds


class FakeVehicleLink:
    """Kênh xe giả lập, trả các sự kiện đã xếp sẵn cho lần poll kế tiếp và ghi lại lệnh gửi đi."""

    def __init__ (self) -> None:
        self ._events: list[VehicleEvent] = []
        self .sent_arm: list[bool] = []
        self .sent_drive: list[tuple[float, float]] = []
        self .manual_mode_requests: int = 0
        self .sent_timesync: list[int] = []
        self .closed = False

    def push (self, event: VehicleEvent) -> None:
        """Xếp một sự kiện để bên dùng nhận trong lần poll kế tiếp."""
        self ._events .append (event)

    def poll (self) -> list[VehicleEvent]:
        """Trả các sự kiện đang chờ rồi xóa chúng khỏi hàng đợi."""
        events = self ._events
        self ._events = []
        return events

    def send_arm (self, arm: bool) -> None:
        """Ghi lại lệnh mở khóa (True) hoặc khóa (False) để test kiểm tra."""
        self .sent_arm .append (arm)

    def send_drive (self, forward: float, turn: float) -> None:
        """Ghi lại mức lái (forward, turn) đã gửi để test kiểm tra."""
        self .sent_drive .append ((forward, turn))

    def send_manual_mode (self) -> None:
        """Đếm số lần yêu cầu xe chuyển sang chế độ Manual."""
        self .manual_mode_requests += 1

    def send_timesync (self, ts1_ns: int) -> None:
        """Ghi lại gói timesync đã gửi để test kiểm tra."""
        self .sent_timesync .append (ts1_ns)

    def close (self) -> None:
        """Đánh dấu link giả lập đã được đóng."""
        self .closed = True