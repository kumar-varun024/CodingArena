"""Trusted deterministic reference implementation for booking-v1."""

class BookingSystem:
    def __init__(self, capacity: int):
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("capacity must be an integer >= 1")
        self.capacity = capacity
        self._reservations = {}

    def book(self, booking_id: str, seats: int) -> bool:
        if not isinstance(booking_id, str) or not booking_id:
            return False
        if isinstance(seats, bool) or not isinstance(seats, int) or seats <= 0:
            return False
        if booking_id in self._reservations or seats > self.available():
            return False
        self._reservations[booking_id] = seats
        return True

    def cancel(self, booking_id: str) -> bool:
        if not isinstance(booking_id, str) or not booking_id or booking_id not in self._reservations:
            return False
        del self._reservations[booking_id]
        return True

    def available(self) -> int:
        return self.capacity - sum(self._reservations.values())

    def reservations(self) -> dict[str, int]:
        return dict(self._reservations)
