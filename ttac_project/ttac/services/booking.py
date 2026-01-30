from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

import razorpay

from ttac.models import Show, Seat, Ticket, Payment


LOCK_MINS = 5
BOOKING_CLOSE_MINS = 30


# ----------------------------
# ✅ SEAT LOCK HELPERS
# ----------------------------

def _lock_expiry_time(now):
    return now - timedelta(minutes=LOCK_MINS)


def release_expired_locks(show, now=None):
    """
    ✅ Release expired locks for a specific show
    """
    now = now or timezone.now()
    expiry = _lock_expiry_time(now)

    Seat.objects.filter(
        show=show,
        is_booked=False,
        locked_at__isnull=False,
        locked_at__lt=expiry,
    ).update(
        locked_by=None,
        locked_at=None
    )


# ----------------------------
# ✅ 1) LOCK SEATS (ATOMIC)
# ----------------------------

@transaction.atomic
def lock_seats(user, show_id, seat_codes):
    """
    ✅ Locks seats for 5 minutes for a user.
    Prevents locking seats locked by others (non-expired).
    """
    if not seat_codes:
        raise ValidationError("No seats selected.")

    seat_codes = list(set(seat_codes))  # remove duplicates
    now = timezone.now()

    show = Show.objects.select_for_update().get(id=show_id)

    # ✅ booking cutoff (30 mins rule)
    cutoff = now + timedelta(minutes=BOOKING_CLOSE_MINS)
    if show.show_time < cutoff:
        raise ValidationError("Booking closed for this show (30 mins before showtime).")

    # ✅ clean expired locks before locking
    release_expired_locks(show, now=now)

    # ✅ lock seat rows
    seats_qs = Seat.objects.select_for_update().filter(
        show=show,
        seat_code__in=seat_codes
    )

    seats = list(seats_qs)

    # ✅ validate seat codes exist
    if len(seats) != len(seat_codes):
        existing = {s.seat_code for s in seats}
        missing = [c for c in seat_codes if c not in existing]
        raise ValidationError(f"Invalid seat(s): {missing}")

    # ✅ cannot lock booked seats
    if any(s.is_booked for s in seats):
        raise ValidationError("Some seats are already booked.")

    # ✅ cannot lock if locked by other user (non expired)
    expiry = _lock_expiry_time(now)
    for s in seats:
        if s.locked_by_id and s.locked_by_id != user.id:
            # locked by someone else and still valid
            if s.locked_at and s.locked_at > expiry:
                raise ValidationError(f"Seat locked by another user: {s.seat_code}")

    # ✅ lock seats for this user
    Seat.objects.filter(id__in=[s.id for s in seats]).update(
        locked_by=user,
        locked_at=now
    )

    return seats


# ----------------------------
# ✅ 2) CREATE TICKET (PENDING)
# ----------------------------

@transaction.atomic
def create_ticket_pending(user, show_id, seat_codes):
    """
    ✅ Creates Ticket = PENDING.
    Requires seats are currently locked by the same user.
    """
    if not seat_codes:
        raise ValidationError("No seats selected.")

    seat_codes = list(set(seat_codes))
    now = timezone.now()

    show = Show.objects.select_for_update().get(id=show_id)

    # ✅ clear expired locks first
    release_expired_locks(show, now=now)

    seats_qs = Seat.objects.select_for_update().filter(
        show=show,
        seat_code__in=seat_codes
    )

    seats = list(seats_qs)

    if len(seats) != len(seat_codes):
        raise ValidationError("Invalid seat selection.")

    # ✅ must be locked by same user & lock not expired
    expiry = _lock_expiry_time(now)

    for s in seats:
        if s.locked_by_id != user.id:
            raise ValidationError("Seats are not locked by you (or lock expired).")
        if not s.locked_at or s.locked_at < expiry:
            raise ValidationError("Seat lock expired. Please select seats again.")

    total_price = len(seats) * show.price_per_seat

    ticket = Ticket.objects.create(
        user=user,
        show=show,
        total_price=total_price,
        status="PENDING",
    )

    ticket.seats.set(seats)

    return ticket


# ----------------------------
# ✅ 3) CONFIRM BOOKING AFTER PAYMENT
# ----------------------------

@transaction.atomic
def confirm_ticket_booking(ticket_id: int, user):
    """
    ✅ After payment success:
    - Seats become booked
    - Ticket becomes BOOKED
    - Locks cleared
    """
    ticket = (
        Ticket.objects.select_for_update()
        .prefetch_related("seats")
        .select_related("show", "user")
        .get(id=ticket_id, user=user)
    )

    if ticket.status == "BOOKED":
        return ticket

    if ticket.status != "PENDING":
        raise ValidationError("Ticket is not in payable state.")

    seat_ids = list(ticket.seats.values_list("id", flat=True))

    # ✅ lock seats rows
    Seat.objects.select_for_update().filter(id__in=seat_ids)

    # ✅ book them
    Seat.objects.filter(id__in=seat_ids).update(
        is_booked=True,
        locked_by=None,
        locked_at=None
    )

    ticket.status = "BOOKED"
    ticket.save(update_fields=["status"])

    return ticket


# ----------------------------
# ✅ RAZORPAY HELPERS
# ----------------------------

def _razorpay_client():
    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


# ----------------------------
# ✅ 4) CREATE RAZORPAY ORDER
# ----------------------------

@transaction.atomic
def create_booking_razorpay_order(ticket_id: int, user):
    """
    ✅ Creates Razorpay order for a PENDING ticket
    """
    ticket = Ticket.objects.select_for_update().get(id=ticket_id, user=user)

    if ticket.status != "PENDING":
        raise ValidationError("Ticket is not pending.")

    client = _razorpay_client()

    order = client.order.create({
        "amount": ticket.total_price * 100,
        "currency": "INR",
        "payment_capture": 1
    })

    pay, _ = Payment.objects.update_or_create(
        ticket=ticket,
        defaults={
            "razorpay_order_id": order["id"],
            "amount": ticket.total_price,
            "status": "CREATED",
        }
    )

    return pay


# ----------------------------
# ✅ 5) VERIFY PAYMENT + CONFIRM BOOKING
# ----------------------------

@transaction.atomic
def verify_booking_payment(
    *,
    ticket_id: int,
    user,
    razorpay_payment_id: str,
    razorpay_order_id: str,
    razorpay_signature: str
):
    """
    ✅ Verify Razorpay signature + mark payment as PAID + confirm ticket booking
    """
    ticket = Ticket.objects.select_for_update().get(id=ticket_id, user=user)
    pay = Payment.objects.select_for_update().get(ticket=ticket)

    # ✅ Already verified
    if pay.status == "PAID":
        return pay

    # ✅ Must match same Razorpay order created earlier
    if pay.razorpay_order_id != razorpay_order_id:
        pay.status = "FAILED"
        pay.save(update_fields=["status"])
        raise ValidationError("Order ID mismatch. Payment rejected.")

    client = _razorpay_client()

    # ✅ Verify signature
    try:
        client.utility.verify_payment_signature({
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_order_id": razorpay_order_id,
            "razorpay_signature": razorpay_signature
        })
    except Exception:
        pay.status = "FAILED"
        pay.save(update_fields=["status"])
        raise ValidationError("Payment verification failed.")

    # ✅ Mark paid
    pay.razorpay_payment_id = razorpay_payment_id
    pay.razorpay_signature = razorpay_signature
    pay.status = "PAID"
    pay.save(update_fields=["razorpay_payment_id", "razorpay_signature", "status"])

    # ✅ Confirm booking (book seats + ticket booked)
    confirm_ticket_booking(ticket_id=ticket.id, user=user)

    return pay
