"""Starter API for the booking-v1 task. Implement the methods below."""

class BookingSystem:
    def __init__(self, capacity: int):
        raise NotImplementedError

    def book(self, booking_id: str, seats: int) -> bool:
        raise NotImplementedError

    def cancel(self, booking_id: str) -> bool:
        raise NotImplementedError

    def available(self) -> int:
        raise NotImplementedError

    def reservations(self) -> dict[str, int]:
        raise NotImplementedError
