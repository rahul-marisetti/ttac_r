import qrcode
import json
from django.core.files.base import ContentFile
from io import BytesIO


def generate_ticket_qr(ticket, payment_mode="Unknown"):
    """
    Generates QR code with JSON data containing ticket details.
    Stored in ticket.qr_image
    """

    seat_list = list(ticket.seats.values_list("seat_code", flat=True))

    data = {
        "app": "T-tac",
        "booking_id": ticket.id,
        "movie": ticket.show.movie.title,
        "language": ticket.show.movie.language,
        "show_time": ticket.show.show_time.isoformat(),
        "theatre": ticket.show.theatre.name,
        "location": ticket.show.theatre.location,
        "city": ticket.show.theatre.city,
        "seats": seat_list,
        "tickets_count": len(seat_list),
        "total_amount": ticket.total_price,
        "payment_mode": payment_mode,
        "status": ticket.status,
    }

    json_data = json.dumps(data, indent=2)

    qr = qrcode.make(json_data)

    buffer = BytesIO()
    qr.save(buffer, format="PNG")

    filename = f"ticket_{ticket.id}.png"
    ticket.qr_image.save(filename, ContentFile(buffer.getvalue()), save=False)
