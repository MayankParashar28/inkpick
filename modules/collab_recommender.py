"""
Collaborative Filtering Engine
==============================
Item-item collaborative filtering on latent factors learned from MovieLens
ratings (see scripts/train_collab.py). "People who liked X also liked Y."

Model files (NumPy only, no pickle):
  models/collab_factors.npy    float32 [n_movies, k], L2-normalised rows
  models/collab_movie_ids.npy  int32   [n_movies]    movieId for each row

Until those exist, a curated popularity fallback is served instead.
"""
import os

import numpy as np

from modules.utils import top_n_indices

# Commonly top-rated MovieLens titles (fallback only)
POPULAR_IDS = [318, 296, 356, 527, 260, 593, 2571, 1, 480, 1196, 589, 2858,
               110, 1198, 47, 50, 2959, 4993, 58559, 79132]


class CollabEngine:
    """Collaborative filtering engine with popularity fallback."""

    def __init__(self, movie_engine=None, model_path: str = "models/"):
        self.movie_engine = movie_engine
        self.factors = None
        self.row_of = {}
        self.movie_ids = None
        factors_path = os.path.join(model_path, "collab_factors.npy")
        ids_path = os.path.join(model_path, "collab_movie_ids.npy")

        if os.path.exists(factors_path) and os.path.exists(ids_path):
            try:
                factors = np.load(factors_path).astype(np.float32, copy=False)
                movie_ids = np.load(ids_path).astype(np.int64, copy=False)
                if factors.ndim != 2 or len(factors) != len(movie_ids):
                    raise ValueError(f"shape mismatch {factors.shape} vs {movie_ids.shape}")
                norms = np.linalg.norm(factors, axis=1, keepdims=True)
                self.factors = np.divide(factors, norms, out=np.zeros_like(factors), where=norms > 0)
                self.movie_ids = movie_ids
                self.row_of = {int(m): i for i, m in enumerate(movie_ids)}
            except Exception as e:
                print(f"  ⚠️  Collaborative Engine: failed to load factors ({e}); using fallback")
                self.factors = None

        if self.ready:
            print(f"  ✅ Collaborative Engine ready — {len(self.row_of):,} movies × {self.factors.shape[1]} factors.")
        else:
            print("  ⚠️  Collaborative Engine: model not trained yet (popularity fallback active)")

    @property
    def ready(self) -> bool:
        return self.factors is not None

    def covers(self, movie_id: int) -> bool:
        return movie_id in self.row_of

    def recommend(self, movie_id: int, top_n: int = 12, genre: str | None = None) -> list[dict]:
        if self.movie_engine is None:
            return []
        if self.ready and movie_id in self.row_of:
            return self._recommend_factors(movie_id, top_n, genre)
        return self._fallback(movie_id, top_n, genre)

    def _recommend_factors(self, movie_id: int, top_n: int, genre: str | None) -> list[dict]:
        row = self.row_of[movie_id]
        scores = self.factors @ self.factors[row]
        if genre:
            g = genre.lower()
            allowed = self.movie_engine.genre_mask.get(g)
            if allowed is None:
                return []
            cat_idx = self._catalog_index()
            ok = (cat_idx >= 0) & allowed[np.clip(cat_idx, 0, None)]
            scores = np.where(ok, scores, 0.0)

        top = top_n_indices(scores, top_n * 2, exclude_idx=row)
        ids = [int(self.movie_ids[i]) for i in top]
        by_id = {r["movieId"]: r for r in self.movie_engine.get_by_ids(ids)}
        seed = self.movie_engine.get_item(movie_id)
        results = []
        for i, mid in zip(top, ids):
            r = by_id.get(mid)
            if not r:
                continue
            r["similarity"] = round(float(min(0.98, max(0.0, scores[i]))), 4)
            r["mode"] = "collaborative"
            r["reasons"] = ["Fans of " + (seed["title"] if seed else "this") + " also loved it"]
            results.append(r)
            if len(results) == top_n:
                break
        return results

    def _catalog_index(self) -> np.ndarray:
        """Factor row -> catalog row (-1 if missing), computed once."""
        if getattr(self, "_cat_idx", None) is None:
            lookup = self.movie_engine.id_to_idx
            self._cat_idx = np.array([lookup.get(int(m), -1) for m in self.movie_ids], dtype=np.int64)
        return self._cat_idx

    def _fallback(self, movie_id: int, top_n: int, genre: str | None) -> list[dict]:
        ids = [m for m in POPULAR_IDS if m != movie_id]
        results = self.movie_engine.get_by_ids(ids)
        if genre:
            g = genre.lower()
            results = [r for r in results if g in {x.lower() for x in r["genres"]}]
        for r in results:
            r["similarity"] = 0.85
            r["mode"] = "collab-fallback"
            r["reasons"] = ["All-time audience favourite"]
        return results[:top_n]
