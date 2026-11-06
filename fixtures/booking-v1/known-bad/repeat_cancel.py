"""Known-bad example: cancellation of an absent/already-cancelled ID succeeds."""
class BookingSystem:
    def __init__(self, capacity): self.capacity, self._reservations = capacity, {}
    def available(self): return self.capacity - sum(self._reservations.values())
    def reservations(self): return dict(self._reservations)
    def book(self, booking_id, seats):
        if not isinstance(booking_id, str) or not booking_id or isinstance(seats, bool) or not isinstance(seats, int) or seats <= 0 or booking_id in self._reservations or seats > self.available(): return False
        self._reservations[booking_id] = seats; return True
    def cancel(self, booking_id):
        if not isinstance(booking_id, str) or not booking_id: return False
        self._reservations.pop(booking_id, None); return True
