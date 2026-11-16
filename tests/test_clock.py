"""Kiểm tra tầng 4 – đồng hồ SystemClock."""

from rover .drivers .clock import SystemClock


def test_system_clock_uses_monotonic_time (monkeypatch):
    monkeypatch .setattr ("rover.drivers.clock.time.monotonic", lambda: 12.5)

    assert SystemClock () .now () == 12.5
