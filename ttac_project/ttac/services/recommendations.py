from django.utils import timezone
from datetime import timedelta
from django.db.models import Avg

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from ttac.models import Movie, Ticket


BOOKING_CLOSE_MINS = 30


def get_user_recommendations(user, top_n=6):
    watched = Ticket.objects.filter(
        user=user,
        status="BOOKED",
        show__show_time__lt=timezone.now()
    ).select_related("show__movie")

    # fallback: trending
    if not watched.exists():
        return Movie.objects.annotate(
            avg_rating=Avg("show__ticket__rating")
        ).order_by("-avg_rating")[:top_n]

    watched_movie_ids = watched.values_list("show__movie_id", flat=True)

    booking_cutoff = timezone.now() + timedelta(minutes=BOOKING_CLOSE_MINS)
    candidates = Movie.objects.filter(show__show_time__gte=booking_cutoff).distinct()
    candidates = candidates.exclude(id__in=watched_movie_ids)

    if not candidates.exists():
        return Movie.objects.none()

    all_movies = list(Movie.objects.all())
    movie_texts = []
    movie_ids = []

    for m in all_movies:
        title = (m.title or "").lower()
        lang = (m.language or "").lower()
        genre = (m.genre or "").lower()
        movie_texts.append(f"{title} language:{lang} genre:{genre}")
        movie_ids.append(m.id)

    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform(movie_texts)

    # build user profile text weighted by rating
    profile = []
    for t in watched:
        m = t.show.movie
        rating = t.rating if t.rating else 3
        text = f"{m.title.lower()} language:{m.language.lower()} genre:{m.genre.lower()}"
        profile.extend([text] * rating)

    user_vector = vectorizer.transform([" ".join(profile)])
    sim = cosine_similarity(user_vector, tfidf_matrix).flatten()

    candidate_ids = set(candidates.values_list("id", flat=True))
    scored = [(movie_ids[i], sim[i]) for i in range(len(movie_ids)) if movie_ids[i] in candidate_ids]

    scored.sort(key=lambda x: x[1], reverse=True)
    top_ids = [mid for mid, score in scored[:top_n]]

    cand_map = {m.id: m for m in candidates}
    return [cand_map[mid] for mid in top_ids if mid in cand_map]
