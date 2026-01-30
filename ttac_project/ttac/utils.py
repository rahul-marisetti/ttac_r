import string
from .models import Seat

def create_show_seats(show):
    rows = string.ascii_uppercase[:show.rows]  # A,B,C...
    for r in rows:
        for c in range(1, show.cols + 1):
            Seat.objects.get_or_create(show=show, seat_code=f"{r}{c}")

from django.utils import timezone
from datetime import timedelta

LOCK_TIME_MINUTES = 5

def release_expired_seat_locks(show):
    expiry = timezone.now() - timedelta(minutes=LOCK_TIME_MINUTES)

    Seat.objects.filter(
        show=show,
        is_booked=False,
        locked_at__lt=expiry
    ).update(locked_by=None, locked_at=None)

from .models import TicketResale

def cleanup_expired_resales():
    expired = TicketResale.objects.filter(is_sold=False)

    for r in expired:
        if r.is_expired():
            r.delete()
