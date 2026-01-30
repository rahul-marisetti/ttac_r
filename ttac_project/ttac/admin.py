from django.contrib import admin, messages
from django.utils import timezone
from datetime import datetime, time, timedelta

from .models import Movie, Theatre, Show, Seat, Ticket, Wallet, TicketResale, Payment


# ✅ Register Models (DO NOT register Show here because we use @admin.register for it)
admin.site.register(Movie)
admin.site.register(Theatre)
admin.site.register(Seat)
admin.site.register(Ticket)
admin.site.register(Wallet)
admin.site.register(TicketResale)
admin.site.register(Payment)


# ✅ Default show timings
DEFAULT_TIMES = [
    time(11, 0),  # 11:00 AM
    time(14, 0),  # 2:00 PM
    time(18, 0),  # 6:00 PM
    time(21, 0),  # 9:00 PM
]


# ✅ Custom Admin for Show
@admin.register(Show)
class ShowAdmin(admin.ModelAdmin):
    list_display = ("movie", "theatre", "show_time", "price_per_seat")
    list_filter = ("theatre", "movie", "show_time")
    search_fields = ("movie__title", "theatre__name", "theatre__city")
    ordering = ("-show_time",)

    actions = ["create_default_shows_for_next_7_days"]

    def create_default_shows_for_next_7_days(self, request, queryset):
        created = 0

        for show in queryset:
            movie = show.movie
            theatre = show.theatre
            price = show.price_per_seat

            # ✅ Create shows for next 7 days (including today)
            for day_offset in range(0, 7):
                day = timezone.localdate() + timedelta(days=day_offset)

                for t in DEFAULT_TIMES:
                    dt = datetime.combine(day, t)
                    dt = timezone.make_aware(dt)

                    obj, was_created = Show.objects.get_or_create(
                        movie=movie,
                        theatre=theatre,
                        show_time=dt,
                        defaults={"price_per_seat": price},
                    )

                    if was_created:
                        created += 1

        self.message_user(
            request,
            f"✅ Created {created} default shows (11AM, 2PM, 6PM, 9PM).",
            messages.SUCCESS
        )

    create_default_shows_for_next_7_days.short_description = (
        "Create default shows for next 7 days (11AM, 2PM, 6PM, 9PM)"
    )
