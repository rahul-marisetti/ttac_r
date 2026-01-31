from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.conf import settings
from django.db import transaction
from django.contrib.auth.models import User

from datetime import timedelta
import razorpay

from django.db.models import Avg, Count, Q

from .models import Movie, Show, Seat, Ticket, Payment, Wallet, TicketResale
from .qr_utils import generate_ticket_qr
from .recommender import get_user_recommendations
from .utils import release_expired_seat_locks


# ==========================
# ✅ CONSTANTS
# ==========================
BOOKING_CLOSE_MINS = 30
SEAT_LOCK_MINS = 5
RESALE_CLOSE_HOURS = 3


# ==========================
# ✅ RESALE EXPIRY HELPER
# ==========================
def expire_resales():
    """
    Auto delete resale listings if show_time is within 3 hours.
    Ticket stays with seller, so it appears in My Tickets again.
    """
    now = timezone.now()
    resales = TicketResale.objects.filter(is_sold=False, ticket__status="BOOKED")

    for r in resales:
        expiry_time = r.ticket.show.show_time - timedelta(hours=RESALE_CLOSE_HOURS)
        if now >= expiry_time:
            r.delete()


# ==========================
# ✅ AUTH VIEWS
# ==========================
def signup_view(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        confirm = request.POST.get("confirm_password", "")

        if not username or not email or not password or not confirm:
            messages.error(request, "All fields are required.")
            return redirect("signup")

        if password != confirm:
            messages.error(request, "Passwords do not match.")
            return redirect("signup")

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
            return redirect("signup")

        user = User.objects.create_user(username=username, email=email, password=password)
        login(request, user)
        messages.success(request, "Account created successfully ✅")
        return redirect("home")

    return render(request, "signup.html")


def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            messages.success(request, "Logged in successfully ✅")
            return redirect("home")

        messages.error(request, "Invalid username or password.")
        return redirect("login")

    return render(request, "login.html")


def logout_view(request):
    logout(request)
    messages.success(request, "Logged out successfully ✅")
    return redirect("home")


# ==========================
# ✅ HOME + MOVIES
# ==========================
BOOKING_CLOSE_MINS = 30

def home(request):
    query = request.GET.get("q", "").strip()
    language = request.GET.get("language", "").strip()
    genre = request.GET.get("genre", "").strip()

    booking_cutoff = timezone.now() + timedelta(minutes=BOOKING_CLOSE_MINS)

    # ✅ Default movies = only active shows
    movies = Movie.objects.filter(show__show_time__gte=booking_cutoff).distinct()

    # ✅ Search movies even without active shows
    if query:
        movies = Movie.objects.filter(title__icontains=query).distinct()

    if language:
        movies = movies.filter(language__iexact=language)

    if genre:
        movies = movies.filter(genre__iexact=genre)

    # ✅ Correct ORM JOIN: show__ticket__rating
    # ✅ Only BOOKED tickets should count (not pending)
    movies = movies.annotate(
        avg_rating=Avg("show__ticket__rating", filter=Q(show__ticket__status="BOOKED")),
        rating_count=Count("show__ticket__rating", filter=Q(show__ticket__status="BOOKED")),
    ).order_by("-avg_rating")

    recommended = []
    if request.user.is_authenticated:
        recommended = get_user_recommendations(request.user, top_n=6)

    return render(request, "home.html", {
        "movies": movies,
        "recommended": recommended,
        "query": query,
    })



def movie_detail(request, movie_id):
    movie = get_object_or_404(Movie, id=movie_id)

    booking_cutoff = timezone.now() + timedelta(minutes=BOOKING_CLOSE_MINS)

    shows = Show.objects.filter(
        movie=movie,
        show_time__gte=booking_cutoff
    ).select_related("theatre").order_by("show_time")

    return render(request, "movie_detail.html", {
        "movie": movie,
        "shows": shows
    })


# ==========================
# ✅ BOOKING + SEATS (5 min LOCK)
# ==========================
@login_required
def seat_select(request, show_id):
    show = get_object_or_404(Show, id=show_id)

    # ✅ Release expired locks before displaying seats
    release_expired_seat_locks(show)

    booking_cutoff = timezone.now() + timedelta(minutes=BOOKING_CLOSE_MINS)
    if show.show_time <= booking_cutoff:
        messages.error(request, "⏳ Booking closed for this show (30 minutes before showtime).")
        return redirect("movie_detail", movie_id=show.movie.id)

    seats = Seat.objects.filter(show=show).order_by("seat_code")

    wallet, _ = Wallet.objects.get_or_create(user=request.user)

    if request.method == "POST":
        selected_codes = request.POST.getlist("seats")
        pay_method = request.POST.get("pay_method", "RAZORPAY")

        if not selected_codes:
            messages.error(request, "Please select at least one seat.")
            return redirect("seat_select", show_id=show_id)

        # ✅ Re-check booking cutoff again
        booking_cutoff = timezone.now() + timedelta(minutes=BOOKING_CLOSE_MINS)
        if show.show_time <= booking_cutoff:
            messages.error(request, "⏳ Booking closed for this show.")
            return redirect("movie_detail", movie_id=show.movie.id)

        with transaction.atomic():
            selected_seats = Seat.objects.select_for_update().filter(
                show=show,
                seat_code__in=selected_codes
            )

            # ✅ Validate selection count
            if selected_seats.count() != len(selected_codes):
                messages.error(request, "Invalid seat selection. Please try again.")
                return redirect("seat_select", show_id=show_id)

            # ✅ Check booked seats
            if selected_seats.filter(is_booked=True).exists():
                messages.error(request, "Some seats are already booked.")
                return redirect("seat_select", show_id=show_id)

            # ✅ Check seat locks (not expired)
            lock_expiry = timezone.now() - timedelta(minutes=SEAT_LOCK_MINS)

            for s in selected_seats:
                if s.locked_by and s.locked_by != request.user and s.locked_at and s.locked_at > lock_expiry:
                    messages.error(request, f"Seat {s.seat_code} is temporarily locked by another user.")
                    return redirect("seat_select", show_id=show_id)

            # ✅ LOCK seats for 5 minutes (do NOT mark booked yet)
            selected_seats.update(
                locked_by=request.user,
                locked_at=timezone.now()
            )

            total_price = len(selected_codes) * show.price_per_seat

            # ✅ Create ticket as PENDING until payment success
            ticket = Ticket.objects.create(
                user=request.user,
                show=show,
                total_price=total_price,
                status="PENDING"
            )
            ticket.seats.set(selected_seats)

            # ✅ WALLET PAYMENT
            if pay_method == "WALLET":
                if wallet.balance < total_price:
                    # release locks
                    selected_seats.update(locked_by=None, locked_at=None)
                    ticket.delete()
                    messages.error(request, "❌ Not enough wallet balance. Please add money.")
                    return redirect("wallet_add_money")

                wallet.balance -= total_price
                wallet.save()

                Payment.objects.create(
                    ticket=ticket,
                    razorpay_order_id=f"WALLET_{ticket.id}",
                    amount=total_price,
                    status="PAID"
                )

                # ✅ Ticket booked
                ticket.status = "BOOKED"
                ticket.save()

                # ✅ Mark seats booked + unlock
                selected_seats.update(is_booked=True, locked_by=None, locked_at=None)

                generate_ticket_qr(ticket, payment_mode="Wallet")
                messages.success(request, "✅ Ticket booked successfully using Wallet!")
                return redirect("my_tickets")

            # ✅ RAZORPAY PAYMENT
            try:
                client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
                order = client.order.create({
                    "amount": total_price * 100,
                    "currency": "INR",
                    "payment_capture": 1
                })
            except Exception as e:
                selected_seats.update(locked_by=None, locked_at=None)
                ticket.delete()
                messages.error(request, f"❌ Razorpay order creation failed: {str(e)}")
                return redirect("seat_select", show_id=show_id)

            Payment.objects.create(
                ticket=ticket,
                razorpay_order_id=order["id"],
                amount=total_price,
                status="CREATED"
            )

            return redirect("payment_page", ticket_id=ticket.id)

    return render(request, "seat_select.html", {
        "show": show,
        "seats": seats,
        "wallet": wallet
    })


@login_required
def payment_page(request, ticket_id):
    ticket = get_object_or_404(Ticket, id=ticket_id, user=request.user)
    payment = get_object_or_404(Payment, ticket=ticket)

    # ✅ if already paid
    if payment.status == "PAID":
        messages.info(request, "Payment already completed.")
        return redirect("my_tickets")

    return render(request, "payment.html", {
        "ticket": ticket,
        "payment": payment,
        "razorpay_key": settings.RAZORPAY_KEY_ID
    })


@login_required
@transaction.atomic
def verify_payment(request, ticket_id):
    if request.method != "POST":
        return redirect("home")

    ticket = get_object_or_404(Ticket, id=ticket_id, user=request.user)
    payment = get_object_or_404(Payment, ticket=ticket)

    razorpay_payment_id = request.POST.get("razorpay_payment_id")
    razorpay_order_id = request.POST.get("razorpay_order_id")
    razorpay_signature = request.POST.get("razorpay_signature")

    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

    try:
        client.utility.verify_payment_signature({
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_order_id": razorpay_order_id,
            "razorpay_signature": razorpay_signature
        })

        payment.razorpay_payment_id = razorpay_payment_id
        payment.razorpay_signature = razorpay_signature
        payment.status = "PAID"
        payment.save()

        # ✅ ticket confirmed
        ticket.status = "BOOKED"
        ticket.save()

        # ✅ seats booked + unlocked
        ticket.seats.all().update(is_booked=True, locked_by=None, locked_at=None)

        generate_ticket_qr(ticket, payment_mode="Razorpay")
        messages.success(request, "✅ Payment Successful! Ticket Confirmed.")
        return redirect("my_tickets")

    except Exception:
        # ❌ Payment failed -> release locks, delete ticket
        ticket.seats.all().update(locked_by=None, locked_at=None)

        payment.status = "FAILED"
        payment.save()

        ticket.delete()
        messages.error(request, "❌ Payment verification failed. Seat locks released.")
        return redirect("home")


# ==========================
# ✅ MY TICKETS + WALLET
# ==========================
@login_required
def my_tickets(request):
    expire_resales()
    tickets = Ticket.objects.filter(user=request.user).exclude(status="PENDING").order_by("-booked_at")
    return render(request, "my_tickets.html", {"tickets": tickets})


@login_required
def wallet_page(request):
    wallet, _ = Wallet.objects.get_or_create(user=request.user)
    return render(request, "wallet.html", {"wallet": wallet})


# ==========================
# ✅ TRANSFER MARKET + FILTERS
# ==========================
@login_required
def resale_market(request):
    expire_resales()

    resale_list = TicketResale.objects.filter(
        is_sold=False,
        ticket__status="BOOKED"
    ).select_related(
        "ticket__show__movie",
        "ticket__show__theatre"
    ).annotate(
        seat_count=Count("ticket__seats")
    ).order_by("-listed_at")

    movie_q = request.GET.get("movie", "").strip()
    city_q = request.GET.get("city", "").strip()
    locality_q = request.GET.get("locality", "").strip()
    theatre_q = request.GET.get("theatre", "").strip()
    tickets_q = request.GET.get("tickets", "").strip()

    if movie_q:
        resale_list = resale_list.filter(ticket__show__movie__title__icontains=movie_q)

    if city_q:
        resale_list = resale_list.filter(ticket__show__theatre__city__icontains=city_q)

    if locality_q:
        resale_list = resale_list.filter(ticket__show__theatre__location__icontains=locality_q)

    if theatre_q:
        resale_list = resale_list.filter(ticket__show__theatre__name__icontains=theatre_q)

    if tickets_q.isdigit():
        resale_list = resale_list.filter(seat_count=int(tickets_q))

    return render(request, "resale_market.html", {
        "resale_list": resale_list,
        "movie_q": movie_q,
        "city_q": city_q,
        "locality_q": locality_q,
        "theatre_q": theatre_q,
        "tickets_q": tickets_q,
        "now": timezone.now(),
    })


@login_required
def list_ticket_for_resale(request, ticket_id):
    expire_resales()

    ticket = get_object_or_404(Ticket, id=ticket_id, user=request.user)

    if ticket.status != "BOOKED":
        messages.error(request, "Only booked tickets can be transferred.")
        return redirect("my_tickets")

    if ticket.is_transferred:
        messages.error(request, "This ticket was already transferred once.")
        return redirect("my_tickets")

    expiry_time = ticket.show.show_time - timedelta(hours=RESALE_CLOSE_HOURS)
    if timezone.now() >= expiry_time:
        messages.error(request, "❌ Transfer not allowed. Less than 3 hours left for show.")
        return redirect("my_tickets")

    if TicketResale.objects.filter(ticket=ticket).exists():
        messages.warning(request, "Ticket already listed.")
        return redirect("my_tickets")

    TicketResale.objects.create(
        ticket=ticket,
        seller=request.user,
        resale_price=ticket.total_price
    )

    messages.success(request, "✅ Ticket listed for transfer (until 3 hours before show).")
    return redirect("resale_market")


@login_required
@transaction.atomic
def buy_resale_ticket(request, resale_id):
    expire_resales()

    resale = get_object_or_404(TicketResale, id=resale_id, is_sold=False)

    if resale.seller == request.user:
        messages.error(request, "You cannot buy your own ticket.")
        return redirect("resale_market")

    expiry_time = resale.ticket.show.show_time - timedelta(hours=RESALE_CLOSE_HOURS)
    if timezone.now() >= expiry_time:
        resale.delete()
        messages.error(request, "❌ Transfer closed! Less than 3 hours left.")
        return redirect("resale_market")

    # ✅ Razorpay order create
    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    order = client.order.create({
        "amount": resale.resale_price * 100,
        "currency": "INR",
        "payment_capture": 1
    })

    from .models import ResalePayment
    ResalePayment.objects.update_or_create(
        resale=resale,
        defaults={
            "razorpay_order_id": order["id"],
            "amount": resale.resale_price,
            "status": "CREATED"
        }
    )

    return redirect("resale_payment_page", resale_id=resale.id)


@login_required
def resale_payment_page(request, resale_id):
    resale = get_object_or_404(TicketResale, id=resale_id, is_sold=False)

    from .models import ResalePayment
    pay = get_object_or_404(ResalePayment, resale=resale)

    return render(request, "resale_payment.html", {
        "resale": resale,
        "payment": pay,
        "razorpay_key": settings.RAZORPAY_KEY_ID
    })


@login_required
@transaction.atomic
def verify_resale_payment(request, resale_id):
    if request.method != "POST":
        return redirect("resale_market")

    resale = get_object_or_404(TicketResale, id=resale_id, is_sold=False)

    expiry_time = resale.ticket.show.show_time - timedelta(hours=RESALE_CLOSE_HOURS)
    if timezone.now() >= expiry_time:
        resale.delete()
        messages.error(request, "❌ Transfer closed. Less than 3 hours left.")
        return redirect("resale_market")

    from .models import ResalePayment
    pay = get_object_or_404(ResalePayment, resale=resale)

    razorpay_payment_id = request.POST.get("razorpay_payment_id")
    razorpay_order_id = request.POST.get("razorpay_order_id")
    razorpay_signature = request.POST.get("razorpay_signature")

    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

    try:
        client.utility.verify_payment_signature({
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_order_id": razorpay_order_id,
            "razorpay_signature": razorpay_signature
        })

        pay.razorpay_payment_id = razorpay_payment_id
        pay.razorpay_signature = razorpay_signature
        pay.status = "PAID"
        pay.save()

        ticket = resale.ticket
        ticket.user = request.user
        ticket.is_transferred = True
        ticket.save()
        generate_ticket_qr(ticket, payment_mode="Resale")

        resale.buyer = request.user
        resale.is_sold = True
        resale.save()

        seller_wallet, _ = Wallet.objects.get_or_create(user=resale.seller)
        seller_wallet.balance += resale.resale_price
        seller_wallet.save()

        messages.success(request, "✅ Ticket transferred successfully after payment!")
        return redirect("my_tickets")

    except:
        pay.status = "FAILED"
        pay.save()
        messages.error(request, "❌ Payment verification failed!")
        return redirect("resale_market")


# ==========================
# ✅ WALLET TOPUP
# ==========================
@login_required
def wallet_add_money(request):
    if request.method == "POST":
        amount = int(request.POST.get("amount", 0))

        if amount < 10:
            messages.error(request, "Minimum top-up amount is ₹10.")
            return redirect("wallet_add_money")

        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        order = client.order.create({
            "amount": amount * 100,
            "currency": "INR",
            "payment_capture": 1
        })

        from .models import WalletPayment
        wp = WalletPayment.objects.create(
            user=request.user,
            razorpay_order_id=order["id"],
            amount=amount,
            status="CREATED"
        )

        return redirect("wallet_payment_page", payment_id=wp.id)

    return render(request, "wallet_add_money.html")


@login_required
def wallet_payment_page(request, payment_id):
    from .models import WalletPayment
    wp = get_object_or_404(WalletPayment, id=payment_id, user=request.user)

    return render(request, "wallet_payment.html", {
        "payment": wp,
        "razorpay_key": settings.RAZORPAY_KEY_ID
    })


@login_required
@transaction.atomic
def wallet_verify_payment(request, payment_id):
    if request.method != "POST":
        return redirect("wallet")

    from .models import WalletPayment
    wp = get_object_or_404(WalletPayment, id=payment_id, user=request.user)

    razorpay_payment_id = request.POST.get("razorpay_payment_id")
    razorpay_order_id = request.POST.get("razorpay_order_id")
    razorpay_signature = request.POST.get("razorpay_signature")

    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

    try:
        client.utility.verify_payment_signature({
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_order_id": razorpay_order_id,
            "razorpay_signature": razorpay_signature
        })

        wp.razorpay_payment_id = razorpay_payment_id
        wp.razorpay_signature = razorpay_signature
        wp.status = "PAID"
        wp.save()

        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        wallet.balance += wp.amount
        wallet.save()

        messages.success(request, f"✅ Wallet credited with ₹{wp.amount}")
        return redirect("wallet")

    except:
        wp.status = "FAILED"
        wp.save()
        messages.error(request, "❌ Wallet top-up verification failed.")
        return redirect("wallet")


# ==========================
# ✅ CANCEL RESALE LISTING
# ==========================
@login_required
def cancel_resale_listing(request, resale_id):
    resale = get_object_or_404(TicketResale, id=resale_id)

    if resale.seller != request.user:
        messages.error(request, "You are not allowed to cancel this listing.")
        return redirect("my_tickets")

    if resale.is_sold:
        messages.error(request, "Already sold. Cannot cancel.")
        return redirect("my_tickets")

    resale.delete()
    messages.success(request, "✅ Transfer listing cancelled. Ticket is back in your tickets.")
    return redirect("my_tickets")


# ==========================
# ✅ TICKET DETAILS + RATE MOVIE
# ==========================
@login_required
def ticket_detail(request, ticket_id):
    ticket = get_object_or_404(Ticket, id=ticket_id, user=request.user)
    payment = Payment.objects.filter(ticket=ticket).first()

    payment_mode = "Unknown"
    if payment:
        if payment.razorpay_order_id and str(payment.razorpay_order_id).startswith("WALLET_"):
            payment_mode = "Wallet"
        else:
            payment_mode = "Razorpay"

    return render(request, "ticket_detail.html", {
        "ticket": ticket,
        "payment": payment,
        "payment_mode": payment_mode,
        "now": timezone.now(),
    })


@login_required
def rate_movie(request, ticket_id):
    ticket = get_object_or_404(Ticket, id=ticket_id, user=request.user)

    if ticket.status != "BOOKED":
        messages.error(request, "You can rate only booked tickets.")
        return redirect("ticket_detail", ticket_id=ticket.id)

    if timezone.now() < ticket.show.show_time:
        messages.error(request, "You can rate only after the showtime.")
        return redirect("ticket_detail", ticket_id=ticket.id)

    if request.method == "POST":
        try:
            rating = int(request.POST.get("rating", 0))
        except:
            rating = 0

        if rating < 1 or rating > 5:
            messages.error(request, "Rating must be between 1 and 5.")
            return redirect("ticket_detail", ticket_id=ticket.id)

        ticket.rating = rating
        ticket.rated_at = timezone.now()
        ticket.save()

        messages.success(request, "✅ Thanks! Your rating was saved.")
        return redirect("ticket_detail", ticket_id=ticket.id)

    return redirect("ticket_detail", ticket_id=ticket.id)
