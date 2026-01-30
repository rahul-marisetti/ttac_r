from django.utils import timezone
from datetime import timedelta
from django.db.models import Avg

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .models import Movie, Ticket

BOOKING_CLOSE_MINS = 30  # keep same rule


def get_user_recommendations(user, top_n=6):
    """
    Content-based recommender using TF-IDF + cosine similarity.
    Uses:
    - rated tickets (even if show not finished) for real-time preference updates
    - recommends only movies with upcoming shows (bookable)
    """

    # ✅ Booking cutoff (only show movies that can still be booked)
    booking_cutoff = timezone.now() + timedelta(minutes=BOOKING_CLOSE_MINS)

    # ✅ Candidate movies = movies having at least 1 future show after cutoff
    candidate_movies = Movie.objects.filter(
        show__show_time__gte=booking_cutoff
    ).distinct()

    # ✅ Rated tickets = best signal (real-time recommendations)
    rated_tickets = Ticket.objects.filter(
        user=user,
        status="BOOKED",
        rating__isnull=False
    ).select_related("show__movie")

    # ✅ If user has no rated history → fallback to trending active movies
    if not rated_tickets.exists():
        return list(
            candidate_movies.annotate(
                avg_rating=Avg("show__ticket__rating")
            ).order_by("-avg_rating")[:top_n]
        )

    rated_movie_ids = rated_tickets.values_list("show__movie_id", flat=True)

    # ✅ Remove already rated movies from recommendation list
    candidate_movies = candidate_movies.exclude(id__in=rated_movie_ids)

    # ✅ If nothing left after removing → fallback trending active movies
    if not candidate_movies.exists():
        return list(
            Movie.objects.filter(show__show_time__gte=booking_cutoff)
            .distinct()
            .annotate(avg_rating=Avg("show__ticket__rating"))
            .order_by("-avg_rating")[:top_n]
        )

    # ✅ Build feature text for all movies
    all_movies = list(Movie.objects.all())
    movie_texts = []
    movie_map = []

    for m in all_movies:
        lang = (m.language or "").strip().lower()
        genre = (m.genre or "").strip().lower()
        title = (m.title or "").strip().lower()

        text = f"{title} language:{lang} genre:{genre}"
        movie_texts.append(text)
        movie_map.append(m.id)

    # ✅ TF-IDF vectorizer
    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform(movie_texts)

    # ✅ Build user profile using rated movies (weighted by rating)
    user_profile_parts = []
    for t in rated_tickets:
        m = t.show.movie
        rating = int(t.rating or 3)

        lang = (m.language or "").strip().lower()
        genre = (m.genre or "").strip().lower()
        title = (m.title or "").strip().lower()

        # repeat by rating weight
        user_profile_parts.extend([f"{title} language:{lang} genre:{genre}"] * rating)

    user_profile_text = " ".join(user_profile_parts)

    user_vector = vectorizer.transform([user_profile_text])

    # ✅ similarity to all movies
    sim_scores = cosine_similarity(user_vector, tfidf_matrix).flatten()

    candidate_ids = set(candidate_movies.values_list("id", flat=True))

    scored_candidates = []
    for idx, movie_id in enumerate(movie_map):
        if movie_id in candidate_ids:
            scored_candidates.append((movie_id, sim_scores[idx]))

    scored_candidates.sort(key=lambda x: x[1], reverse=True)

    top_movie_ids = [mid for mid, score in scored_candidates[:top_n]]

    # ✅ Return movies in same order
    movie_dict = {m.id: m for m in candidate_movies}
    final_movies = [movie_dict[mid] for mid in top_movie_ids if mid in movie_dict]

    return final_movies
