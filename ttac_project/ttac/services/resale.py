from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError

from ttac.models import Ticket, TicketResale

RESALE_CLOSE_HOURS = 3


def resale_expired(ticket):
    expiry_time = ticket.show.show_time - timedelta(hours=RESALE_CLOSE_HOURS)
    return timezone.now() >= expiry_time


@transaction.atomic
def list_ticket_for_resale(user, ticket_id):
    ticket = Ticket.objects.select_for_update().get(id=ticket_id, user=user)

    if ticket.status != "BOOKED":
        raise ValidationError("Only BOOKED tickets can be transferred.")

    if ticket.is_transferred:
        raise ValidationError("Ticket already transferred once. Cannot resell again.")

    if resale_expired(ticket):
        raise ValidationError("Transfer not allowed within 3 hours before showtime.")

    if TicketResale.objects.filter(ticket=ticket).exists():
        raise ValidationError("Ticket already listed.")

    resale = TicketResale.objects.create(
        ticket=ticket,
        seller=user,
        resale_price=ticket.total_price
    )
    return resale

import razorpay
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError

from ttac.models import TicketResale, ResalePayment, Wallet


RESALE_CLOSE_HOURS = 3


def _razorpay_client():
    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def resale_expired(ticket):
    expiry_time = ticket.show.show_time - timedelta(hours=RESALE_CLOSE_HOURS)
    return timezone.now() >= expiry_time


@transaction.atomic
def create_resale_buy_order(user, resale_id):
    resale = TicketResale.objects.select_for_update().get(id=resale_id, is_sold=False)

    if resale.seller == user:
        raise ValidationError("You cannot buy your own ticket.")

    if resale_expired(resale.ticket):
        resale.delete()
        raise ValidationError("Resale closed (less than 3 hours left).")

    client = _razorpay_client()
    order = client.order.create({
        "amount": resale.resale_price * 100,
        "currency": "INR",
        "payment_capture": 1
    })

    rp, _ = ResalePayment.objects.update_or_create(
        resale=resale,
        defaults={
            "razorpay_order_id": order["id"],
            "amount": resale.resale_price,
            "status": "CREATED"
        }
    )

    return rp


@transaction.atomic
def verify_resale_buy_payment(user, resale_id, razorpay_payment_id, razorpay_order_id, razorpay_signature):
    resale = TicketResale.objects.select_for_update().get(id=resale_id, is_sold=False)
    rp = ResalePayment.objects.select_for_update().get(resale=resale)

    if resale.seller == user:
        raise ValidationError("You cannot buy your own ticket.")

    if resale_expired(resale.ticket):
        resale.delete()
        raise ValidationError("Resale closed (less than 3 hours left).")

    client = _razorpay_client()

    try:
        client.utility.verify_payment_signature({
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_order_id": razorpay_order_id,
            "razorpay_signature": razorpay_signature
        })
    except Exception:
        rp.status = "FAILED"
        rp.save()
        raise ValidationError("Resale payment verification failed.")

    rp.razorpay_payment_id = razorpay_payment_id
    rp.razorpay_signature = razorpay_signature
    rp.status = "PAID"
    rp.save()

    # ✅ transfer ticket
    ticket = resale.ticket
    ticket.user = user
    ticket.is_transferred = True
    ticket.save()

    resale.buyer = user
    resale.is_sold = True
    resale.save()

    # ✅ credit seller wallet
    seller_wallet, _ = Wallet.objects.get_or_create(user=resale.seller)
    seller_wallet.balance += resale.resale_price
    seller_wallet.save()

    return rp

