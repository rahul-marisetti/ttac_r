from datetime import timedelta
from django.utils import timezone
from ttac.models import Seat


LOCK_MINS = 5


def release_expired_locks(show):
    expiry = timezone.now() - timedelta(minutes=LOCK_MINS)
    Seat.objects.filter(
        show=show,
        is_booked=False,
        locked_at__lt=expiry
    ).update(locked_by=None, locked_at=None)


def lock_seats(show, seat_codes, user):
    now = timezone.now()

    seats = Seat.objects.select_for_update().filter(
        show=show,
        seat_code__in=seat_codes
    )

    # invalid seat codes
    if seats.count() != len(seat_codes):
        return None, "Invalid seat selection"

    # already booked
    if seats.filter(is_booked=True).exists():
        return None, "Some seats already booked"

    # locked by someone else
    if seats.exclude(locked_by=None).exclude(locked_by=user).exists():
        return None, "Some seats are locked by another user"

    # lock
    seats.update(locked_by=user, locked_at=now)

    return seats, None
