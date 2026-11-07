"""
Collaborative Filtering Engine
==============================
Placeholder for a latent-factor model. Until factors are trained it
serves a curated popularity fallback (never including the seed movie).
"""
import os

# Commonly top-rated MovieLens titles
POPULAR_IDS = [318, 296, 356, 527, 260, 593, 2571, 1, 480, 1196, 589, 2858,
               110, 1198, 47, 50, 2959, 4993, 58559, 79132]


class CollabEngine:
    """Collaborative filtering engine with popularity fallback."""

    def __init__(self, movie_engine=None, model_path: str = "models/"):
        self.movie_engine = movie_engine
        self.ready = os.path.exists(os.path.join(model_path, "collab_factors.npy"))
        if self.ready:
            print("  ✅ Collaborative Engine: Model factors found.")
        else:
            print("  ⚠️  Collaborative Engine: model not trained yet (popularity fallback active)")

    def recommend(self, movie_id: int, top_n: int = 12, genre: str | None = None) -> list[dict]:
        """Returns popular movies (excluding the seed) until a model is trained."""
        if self.movie_engine is None:
            return []
        ids = [m for m in POPULAR_IDS if m != movie_id]
        results = self.movie_engine.get_by_ids(ids)
        if genre:
            g = genre.lower()
            results = [r for r in results if g in {x.lower() for x in r["genres"]}]
        for r in results:
            r["similarity"] = 0.85
            r["mode"] = "collab-fallback"
        return results[:top_n]
