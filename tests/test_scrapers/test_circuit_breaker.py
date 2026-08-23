"""Tests for the per-source CircuitBreaker."""
from __future__ import annotations

from deal_hunter.scrapers.runner import CircuitBreaker


class TestCircuitBreaker:
    def test_success_clears_failures(self) -> None:
        cb = CircuitBreaker(threshold=3)
        cb.record_failure("reddit")
        cb.record_success("reddit")
        assert cb.is_open("reddit") is False

    def test_failures_trip_but_not_open_below_threshold(self) -> None:
        cb = CircuitBreaker(threshold=3)
        assert cb.record_failure("src") == "tripped"
        assert cb.record_failure("src") == "tripped"
        assert cb.is_open("src") is False

    def test_threshold_opens_circuit(self) -> None:
        cb = CircuitBreaker(threshold=3)
        assert cb.record_failure("src") == "tripped"
        assert cb.record_failure("src") == "tripped"
        assert cb.record_failure("src") == "open"
        assert cb.is_open("src") is True  # within cooldown

    def test_cooldown_expiry_resets(self) -> None:
        cb = CircuitBreaker(threshold=3, cooldown=0.001)
        cb.record_failure("src")
        cb.record_failure("src")
        cb.record_failure("src")
        assert cb.is_open("src") is True
        # after the tiny cooldown elapses, next check should reset and allow
        import time

        time.sleep(0.01)
        assert cb.is_open("src") is False
