from rest_framework import serializers
from ttac.models import Movie, Show, Seat, Ticket, Wallet, TicketResale


class MovieSerializer(serializers.ModelSerializer):
    avg_rating = serializers.FloatField(read_only=True)
    rating_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Movie
        fields = ["id", "title", "description", "poster", "duration_mins", "language", "genre",
                  "avg_rating", "rating_count"]


class ShowSerializer(serializers.ModelSerializer):
    movie_title = serializers.CharField(source="movie.title", read_only=True)
    theatre_name = serializers.CharField(source="theatre.name", read_only=True)
    theatre_city = serializers.CharField(source="theatre.city", read_only=True)

    class Meta:
        model = Show
        fields = ["id", "movie", "movie_title", "theatre", "theatre_name", "theatre_city",
                  "show_time", "price_per_seat", "rows", "cols"]


class SeatSerializer(serializers.ModelSerializer):
    class Meta:
        model = Seat
        fields = ["id", "seat_code", "is_booked", "locked_by", "locked_at"]


class TicketSerializer(serializers.ModelSerializer):
    movie_title = serializers.CharField(source="show.movie.title", read_only=True)
    show_time = serializers.DateTimeField(source="show.show_time", read_only=True)
    seats = serializers.StringRelatedField(many=True)

    class Meta:
        model = Ticket
        fields = ["id", "movie_title", "show_time", "total_price", "status", "rating", "rated_at", "seats", "booked_at"]


class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = ["balance"]


class TicketResaleSerializer(serializers.ModelSerializer):
    movie_title = serializers.CharField(source="ticket.show.movie.title", read_only=True)
    show_time = serializers.DateTimeField(source="ticket.show.show_time", read_only=True)
    theatre_name = serializers.CharField(source="ticket.show.theatre.name", read_only=True)
    theatre_city = serializers.CharField(source="ticket.show.theatre.city", read_only=True)
    seat_count = serializers.SerializerMethodField()

    def get_seat_count(self, obj):
        return obj.ticket.seats.count()

    class Meta:
        model = TicketResale
        fields = ["id", "movie_title", "show_time", "theatre_name", "theatre_city",
                  "resale_price", "listed_at", "is_sold", "seat_count"]

from ttac.models import Payment, WalletPayment, ResalePayment


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ["id", "razorpay_order_id", "amount", "status", "created_at"]


class WalletPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletPayment
        fields = ["id", "razorpay_order_id", "amount", "status", "created_at"]


class ResalePaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResalePayment
        fields = ["id", "razorpay_order_id", "amount", "status", "created_at"]
