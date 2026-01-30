from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path("", views.home, name="home"),

    # auth
    path("signup/", views.signup_view, name="signup"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    # movies
    path("movie/<int:movie_id>/", views.movie_detail, name="movie_detail"),

    # booking
    path("show/<int:show_id>/seats/", views.seat_select, name="seat_select"),
    path("payment/<int:ticket_id>/", views.payment_page, name="payment_page"),
    path("payment/success/<int:ticket_id>/", views.verify_payment, name="payment_success"),

    # tickets
    path("mytickets/", views.my_tickets, name="my_tickets"),
    path("ticket/<int:ticket_id>/", views.ticket_detail, name="ticket_detail"),

    # wallet
    path("wallet/", views.wallet_page, name="wallet"),

    # resale / transfer
    path("resale/", views.resale_market, name="resale_market"),
    path("resale/list/<int:ticket_id>/", views.list_ticket_for_resale, name="list_ticket_for_resale"),
    path("resale/buy/<int:resale_id>/", views.buy_resale_ticket, name="buy_resale_ticket"),
    path("resale/pay/<int:resale_id>/", views.resale_payment_page, name="resale_payment_page"),
    path("resale/verify/<int:resale_id>/", views.verify_resale_payment, name="verify_resale_payment"),
    path("resale/cancel/<int:resale_id>/", views.cancel_resale_listing, name="cancel_resale_listing"),
    path("wallet/add/", views.wallet_add_money, name="wallet_add_money"),
    path("wallet/pay/<int:payment_id>/", views.wallet_payment_page, name="wallet_payment_page"),
    path("wallet/verify/<int:payment_id>/", views.wallet_verify_payment, name="wallet_verify_payment"),
    
    #rating
    path("ticket/<int:ticket_id>/rate/", views.rate_movie, name="rate_movie"),

    path("forgot-password/", auth_views.PasswordResetView.as_view(
        template_name="forgot_password.html"
    ), name="password_reset"),

    path("forgot-password/done/", auth_views.PasswordResetDoneView.as_view(
        template_name="forgot_password_done.html"
    ), name="password_reset_done"),

    path("reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        template_name="reset_password_confirm.html"
    ), name="password_reset_confirm"),

    path("reset/done/", auth_views.PasswordResetCompleteView.as_view(
        template_name="reset_password_complete.html"
    ), name="password_reset_complete"),
]
