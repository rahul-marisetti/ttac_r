from django.db import transaction
from django.core.exceptions import ValidationError
from ttac.models import Wallet


def get_wallet(user):
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return wallet


@transaction.atomic
def wallet_pay(user, amount):
    wallet = get_wallet(user)

    if wallet.balance < amount:
        raise ValidationError("Not enough wallet balance")

    wallet.balance -= amount
    wallet.save()
    return wallet

import razorpay
from django.conf import settings
from django.db import transaction
from django.core.exceptions import ValidationError

from ttac.models import Wallet, WalletPayment


def _razorpay_client():
    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def get_wallet(user):
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return wallet


@transaction.atomic
def create_wallet_topup_order(user, amount):
    if amount < 10:
        raise ValidationError("Minimum top-up amount is ₹10")

    client = _razorpay_client()
    order = client.order.create({
        "amount": amount * 100,
        "currency": "INR",
        "payment_capture": 1
    })

    wp = WalletPayment.objects.create(
        user=user,
        razorpay_order_id=order["id"],
        amount=amount,
        status="CREATED"
    )
    return wp


@transaction.atomic
def verify_wallet_topup(payment_id, user, razorpay_payment_id, razorpay_order_id, razorpay_signature):
    wp = WalletPayment.objects.select_for_update().get(id=payment_id, user=user)

    if wp.status == "PAID":
        return wp  # already done

    client = _razorpay_client()

    try:
        client.utility.verify_payment_signature({
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_order_id": razorpay_order_id,
            "razorpay_signature": razorpay_signature
        })
    except Exception:
        wp.status = "FAILED"
        wp.save()
        raise ValidationError("Wallet top-up verification failed.")

    wp.razorpay_payment_id = razorpay_payment_id
    wp.razorpay_signature = razorpay_signature
    wp.status = "PAID"
    wp.save()

    wallet = get_wallet(user)
    wallet.balance += wp.amount
    wallet.save()

    return wp

