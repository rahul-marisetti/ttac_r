from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status

from django.contrib.auth import authenticate, login, logout
from django.db.models import Avg, Count
from django.core.exceptions import ValidationError

from ttac.models import Movie, Show, Seat, Ticket, TicketResale, Wallet

from ttac.api.serializers import (
    MovieSerializer, ShowSerializer, SeatSerializer, TicketSerializer,
    WalletSerializer, TicketResaleSerializer, PaymentSerializer, WalletPaymentSerializer, ResalePaymentSerializer
)

from ttac.services.booking import lock_seats, create_ticket_pending,create_booking_razorpay_order, verify_booking_payment
from ttac.services.recommendations import get_user_recommendations
from ttac.services.resale import list_ticket_for_resale,create_resale_buy_order, verify_resale_buy_payment
from ttac.services.wallet import get_wallet,create_wallet_topup_order, verify_wallet_topup




# ==========================
# ✅ AUTH APIs
# ==========================
@api_view(["POST"])
@permission_classes([AllowAny])
def api_login(request):
    username = request.data.get("username")
    password = request.data.get("password")

    user = authenticate(request, username=username, password=password)
    if not user:
        return Response({"error": "Invalid credentials"}, status=400)

    login(request, user)
    return Response({"message": "Logged in ✅"})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_logout(request):
    logout(request)
    return Response({"message": "Logged out ✅"})


# ==========================
# ✅ MOVIES APIs
# ==========================
@api_view(["GET"])
@permission_classes([AllowAny])
def api_movies(request):
    movies = Movie.objects.annotate(
        avg_rating=Avg("show__ticket__rating"),
        rating_count=Count("show__ticket__rating"),
    ).order_by("-avg_rating")

    return Response(MovieSerializer(movies, many=True).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def api_movie_detail(request, movie_id):
    movie = Movie.objects.annotate(
        avg_rating=Avg("show__ticket__rating"),
        rating_count=Count("show__ticket__rating"),
    ).get(id=movie_id)

    return Response(MovieSerializer(movie).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def api_show_detail(request, show_id):
    show = Show.objects.select_related("movie", "theatre").get(id=show_id)
    return Response(ShowSerializer(show).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def api_show_seats(request, show_id):
    seats = Seat.objects.filter(show_id=show_id).order_by("seat_code")
    return Response(SeatSerializer(seats, many=True).data)


# ==========================
# ✅ BOOKING APIs
# ==========================
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_lock_seats(request):
    show_id = request.data.get("show_id")
    seat_codes = request.data.get("seats", [])

    if not show_id or not seat_codes:
        return Response({"error": "show_id and seats required"}, status=400)

    try:
        seats = lock_seats(request.user, show_id, seat_codes)
        return Response({"message": "Seats locked ✅", "locked": [s.seat_code for s in seats]})
    except ValidationError as e:
        return Response({"error": str(e)}, status=400)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_create_booking(request):
    show_id = request.data.get("show_id")
    seat_codes = request.data.get("seats", [])

    try:
        ticket = create_ticket_pending(request.user, show_id, seat_codes)
        return Response({
            "message": "Ticket created (PENDING) ✅",
            "ticket_id": ticket.id,
            "total_price": ticket.total_price
        })
    except ValidationError as e:
        return Response({"error": str(e)}, status=400)


# ==========================
# ✅ ME APIs
# ==========================
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_my_tickets(request):
    tickets = Ticket.objects.filter(user=request.user).order_by("-booked_at")
    return Response(TicketSerializer(tickets, many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_my_wallet(request):
    wallet = get_wallet(request.user)
    return Response(WalletSerializer(wallet).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_my_recommendations(request):
    rec = get_user_recommendations(request.user, top_n=6)
    return Response(MovieSerializer(rec, many=True).data)


# ==========================
# ✅ RESALE APIs
# ==========================
@api_view(["GET"])
@permission_classes([AllowAny])
def api_resale_list(request):
    resale_list = TicketResale.objects.filter(is_sold=False, ticket__status="BOOKED").order_by("-listed_at")
    return Response(TicketResaleSerializer(resale_list, many=True).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_resale_list_ticket(request, ticket_id):
    try:
        resale = list_ticket_for_resale(request.user, ticket_id)
        return Response({"message": "Ticket listed for transfer ✅", "resale_id": resale.id})
    except ValidationError as e:
        return Response({"error": str(e)}, status=400)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_booking_payment_create(request):
    ticket_id = request.data.get("ticket_id")

    if not ticket_id:
        return Response({"error": "ticket_id is required"}, status=400)

    try:
        pay = create_booking_razorpay_order(ticket_id=ticket_id, user=request.user)
        return Response({
            "message": "Razorpay order created ✅",
            "payment": PaymentSerializer(pay).data
        })
    except ValidationError as e:
        return Response({"error": str(e)}, status=400)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_booking_payment_verify(request):
    ticket_id = request.data.get("ticket_id")

    razorpay_payment_id = request.data.get("razorpay_payment_id")
    razorpay_order_id = request.data.get("razorpay_order_id")
    razorpay_signature = request.data.get("razorpay_signature")

    if not all([ticket_id, razorpay_payment_id, razorpay_order_id, razorpay_signature]):
        return Response({"error": "Missing payment verification fields"}, status=400)

    try:
        pay = verify_booking_payment(
            ticket_id=ticket_id,
            user=request.user,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_order_id=razorpay_order_id,
            razorpay_signature=razorpay_signature
        )
        return Response({"message": "Payment verified ✅ Ticket BOOKED ✅", "payment": PaymentSerializer(pay).data})
    except ValidationError as e:
        return Response({"error": str(e)}, status=400)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_wallet_topup_create(request):
    amount = request.data.get("amount")

    try:
        amount = int(amount)
    except:
        return Response({"error": "amount must be an integer"}, status=400)

    try:
        wp = create_wallet_topup_order(request.user, amount)
        return Response({
            "message": "Wallet topup order created ✅",
            "wallet_payment": WalletPaymentSerializer(wp).data
        })
    except ValidationError as e:
        return Response({"error": str(e)}, status=400)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_wallet_topup_verify(request):
    payment_id = request.data.get("payment_id")

    razorpay_payment_id = request.data.get("razorpay_payment_id")
    razorpay_order_id = request.data.get("razorpay_order_id")
    razorpay_signature = request.data.get("razorpay_signature")

    if not all([payment_id, razorpay_payment_id, razorpay_order_id, razorpay_signature]):
        return Response({"error": "Missing wallet verification fields"}, status=400)

    try:
        wp = verify_wallet_topup(
            payment_id=payment_id,
            user=request.user,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_order_id=razorpay_order_id,
            razorpay_signature=razorpay_signature
        )
        return Response({"message": "Wallet credited ✅", "wallet_payment": WalletPaymentSerializer(wp).data})
    except ValidationError as e:
        return Response({"error": str(e)}, status=400)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_resale_buy_create(request):
    resale_id = request.data.get("resale_id")

    if not resale_id:
        return Response({"error": "resale_id is required"}, status=400)

    try:
        rp = create_resale_buy_order(request.user, resale_id)
        return Response({
            "message": "Resale buy Razorpay order created ✅",
            "resale_payment": ResalePaymentSerializer(rp).data
        })
    except ValidationError as e:
        return Response({"error": str(e)}, status=400)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_resale_buy_verify(request):
    resale_id = request.data.get("resale_id")

    razorpay_payment_id = request.data.get("razorpay_payment_id")
    razorpay_order_id = request.data.get("razorpay_order_id")
    razorpay_signature = request.data.get("razorpay_signature")

    if not all([resale_id, razorpay_payment_id, razorpay_order_id, razorpay_signature]):
        return Response({"error": "Missing resale verification fields"}, status=400)

    try:
        rp = verify_resale_buy_payment(
            user=request.user,
            resale_id=resale_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_order_id=razorpay_order_id,
            razorpay_signature=razorpay_signature
        )
        return Response({"message": "Ticket transferred ✅", "resale_payment": ResalePaymentSerializer(rp).data})
    except ValidationError as e:
        return Response({"error": str(e)}, status=400)
