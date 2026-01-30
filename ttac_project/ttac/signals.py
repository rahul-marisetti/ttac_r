from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import Wallet, Show
from .utils import create_show_seats


@receiver(post_save, sender=User)
def create_wallet(sender, instance, created, **kwargs):
    if created:
        Wallet.objects.create(user=instance)


@receiver(post_save, sender=Show)
def create_seats_for_show(sender, instance, created, **kwargs):
    if created:
        create_show_seats(instance)
