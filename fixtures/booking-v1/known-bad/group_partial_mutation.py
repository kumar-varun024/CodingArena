"""Known-bad example: group booking partially mutates on insufficient capacity."""
class BookingSystem:
    def __init__(self, capacity):
        self.capacity, self._reservations = capacity, {}
    def available(self): return self.capacity - sum(self._reservations.values())
    def reservations(self): return dict(self._reservations)
    def book(self, booking_id, seats):
        if booking_id in self._reservations or not isinstance(booking_id, str) or not booking_id or isinstance(seats, bool) or not isinstance(seats, int) or seats <= 0: return False
        self._reservations[booking_id] = min(seats, self.available())
        return self._reservations[booking_id] == seats
    def cancel(self, booking_id):
        if booking_id not in self._reservations: return False
        del self._reservations[booking_id]; return True
