# booking-v1 specification

All materials in this task pack are deterministic fixtures. The starter and public cases are contestant-visible; reference code and held-out cases are engine-only.

Implement `src/booking.py` with `BookingSystem(capacity: int)`, where `capacity >= 1`, and these methods:

- `book(booking_id: str, seats: int) -> bool`
- `cancel(booking_id: str) -> bool`
- `available() -> int`
- `reservations() -> dict[str, int]`

Requirements:

- **BOOK-01:** A successful booking reserves exactly seats; capacity can never be exceeded.
- **BOOK-02:** Insufficient capacity returns `False` and leaves the entire reservation state unchanged; group bookings are all-or-nothing.
- **BOOK-03:** Cancelling an existing reservation returns `True`, removes it and releases exactly its booked seats.
- **BOOK-04:** Cancelling an unknown or already-cancelled ID returns `False` and changes nothing.
- **BOOK-05:** An already-active booking ID returns `False` and changes nothing. A cancelled ID may be reused.
- **BOOK-06:** `book` returns `False` without mutation for empty/non-string ID, non-integer seats (including `bool`), or seats <= 0. `cancel` with empty/non-string ID also returns `False` without mutation.
- **BOOK-07:** `available()` equals capacity minus all active seats; `reservations()` returns the active ID-to-seat mapping. Different `BookingSystem` instances do not share bookings.

The constructor requires an integer capacity of at least 1. Scenarios invoke operations with positional JSON arguments and compare exact return values.
