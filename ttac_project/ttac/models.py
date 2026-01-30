from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Movie(models.Model):
    title = models.CharField(max_length=200)

    # ✅ Make description optional (you said some movies don’t have it)
    description = models.TextField(blank=True, null=True)

    poster = models.URLField(blank=True, null=True)
    duration_mins = models.IntegerField(default=120)

    language = models.CharField(max_length=50, default="English")
    genre = models.CharField(max_length=100, default="Drama")

    def __str__(self):
        return self.title


class Theatre(models.Model):
    name = models.CharField(max_length=200)
    city = models.CharField(max_length=100)
    location = models.CharField(max_length=200)

    def __str__(self):
        return f"{self.name} - {self.city}"


class Show(models.Model):
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE)
    theatre = models.ForeignKey(Theatre, on_delete=models.CASCADE)

    show_time = models.DateTimeField()
    price_per_seat = models.IntegerField(default=150)

    rows = models.IntegerField(default=5)   # Example: A-E
    cols = models.IntegerField(default=10)  # Example: 1-10

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["show_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["theatre", "show_time"],
                name="unique_show_per_theatre_time"
            )
        ]

    def total_seats(self):
        return self.rows * self.cols

    def __str__(self):
        return f"{self.movie.title} | {self.theatre.name} | {self.show_time.strftime('%d %b %Y %I:%M %p')}"


class Seat(models.Model):
    """
    One seat belongs to one show. Real seat tracking.
    """
    show = models.ForeignKey(Show, on_delete=models.CASCADE, related_name="seats")
    seat_code = models.CharField(max_length=10)   # Example: A1, A2
    is_booked = models.BooleanField(default=False)

    # ✅ Seat Lock system (5 minutes)
    locked_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    locked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("show", "seat_code")

    def __str__(self):
        return f"{self.show.id} - {self.seat_code}"


class Wallet(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    balance = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.user.username} Wallet"


class Ticket(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "PENDING"),     # ✅ Payment not completed yet
        ("BOOKED", "BOOKED"),       # ✅ Payment completed
        ("CANCELLED", "CANCELLED"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    show = models.ForeignKey(Show, on_delete=models.CASCADE)
    seats = models.ManyToManyField(Seat)

    total_price = models.IntegerField()
    booked_at = models.DateTimeField(auto_now_add=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")

    # ✅ Rating feature
    rating = models.IntegerField(null=True, blank=True)  # 1 to 5
    rated_at = models.DateTimeField(null=True, blank=True)

    # ✅ transfer / resale rules
    is_transferred = models.BooleanField(default=False)

    # ✅ QR
    qr_image = models.ImageField(upload_to="qr_codes/", null=True, blank=True)

    def __str__(self):
        return f"Ticket #{self.id} - {self.user.username}"


class Payment(models.Model):
    """
    Track Razorpay payments.
    """
    ticket = models.OneToOneField(Ticket, on_delete=models.CASCADE)
    razorpay_order_id = models.CharField(max_length=200)
    razorpay_payment_id = models.CharField(max_length=200, null=True, blank=True)
    razorpay_signature = models.CharField(max_length=500, null=True, blank=True)

    amount = models.IntegerField()  # INR
    status = models.CharField(max_length=50, default="CREATED")  # CREATED / PAID / FAILED
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Payment {self.status} - Ticket #{self.ticket.id}"


class TicketResale(models.Model):
    """
    Ticket listing for transfer. Price fixed (original price only).
    Transfer allowed only once.
    """
    ticket = models.OneToOneField(Ticket, on_delete=models.CASCADE)
    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name="resale_seller")
    buyer = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name="resale_buyer")

    resale_price = models.IntegerField()
    listed_at = models.DateTimeField(auto_now_add=True)

    is_sold = models.BooleanField(default=False)

    def __str__(self):
        return f"Resale #{self.id} for Ticket #{self.ticket.id}"


class ResalePayment(models.Model):
    resale = models.OneToOneField(TicketResale, on_delete=models.CASCADE)
    razorpay_order_id = models.CharField(max_length=200)
    razorpay_payment_id = models.CharField(max_length=200, null=True, blank=True)
    razorpay_signature = models.CharField(max_length=500, null=True, blank=True)

    amount = models.IntegerField()
    status = models.CharField(max_length=50, default="CREATED")  # CREATED/PAID/FAILED
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"ResalePayment {self.status} - Resale #{self.resale.id}"


class WalletPayment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    razorpay_order_id = models.CharField(max_length=200)
    razorpay_payment_id = models.CharField(max_length=200, null=True, blank=True)
    razorpay_signature = models.CharField(max_length=500, null=True, blank=True)

    amount = models.IntegerField()  # INR
    status = models.CharField(max_length=50, default="CREATED")  # CREATED/PAID/FAILED
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"WalletPayment {self.status} - {self.user.username}"
