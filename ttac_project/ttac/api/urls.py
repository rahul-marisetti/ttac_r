from django.urls import path
from ttac.api import views

urlpatterns = [
    # Auth
    path("auth/login/", views.api_login, name="api_login"),
    path("auth/logout/", views.api_logout, name="api_logout"),

    # Movies
    path("movies/", views.api_movies, name="api_movies"),
    path("movies/<int:movie_id>/", views.api_movie_detail, name="api_movie_detail"),

    # Shows
    path("shows/<int:show_id>/", views.api_show_detail, name="api_show_detail"),
    path("shows/<int:show_id>/seats/", views.api_show_seats, name="api_show_seats"),

    # Booking
    path("bookings/lock-seats/", views.api_lock_seats, name="api_lock_seats"),
    path("bookings/create/", views.api_create_booking, name="api_create_booking"),

    # ✅ Booking payment
    path("payments/booking/create/", views.api_booking_payment_create, name="api_booking_payment_create"),
    path("payments/booking/verify/", views.api_booking_payment_verify, name="api_booking_payment_verify"),

    # Me
    path("me/tickets/", views.api_my_tickets, name="api_my_tickets"),
    path("me/wallet/", views.api_my_wallet, name="api_my_wallet"),
    path("me/recommendations/", views.api_my_recommendations, name="api_my_recommendations"),

    # Resale
    path("resale/", views.api_resale_list, name="api_resale_list"),
    path("resale/<int:ticket_id>/list/", views.api_resale_list_ticket, name="api_resale_list_ticket"),

    # ✅ Resale buy
    path("resale/buy/create/", views.api_resale_buy_create, name="api_resale_buy_create"),
    path("resale/buy/verify/", views.api_resale_buy_verify, name="api_resale_buy_verify"),

    # ✅ Wallet topup
    path("wallet/topup/create/", views.api_wallet_topup_create, name="api_wallet_topup_create"),
    path("wallet/topup/verify/", views.api_wallet_topup_verify, name="api_wallet_topup_verify"),
]
