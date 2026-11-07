"""
Content-Based Movie Recommendation Engine (Zero-Scipy Edition)
============================================================
Loads pre-trained TF-IDF assets and serves recommendations via
a vectorized sparse dot-product implemented in pure NumPy.
"""

import os
import random
import re

import numpy as np
import pandas as pd

from modules.utils import (
    build_row_map,
    format_movie_response,
    get_fuzzy_suggestion,
    parse_list_field,
    sparse_row_scores,
    top_n_indices,
)


class MovieEngine:
    """Content-based recommendation engine (Zero-Scipy)."""

    def __init__(self, data_path: str = "processed/", model_path: str = "models/", mapping_service=None):
        print("  📦 Loading Content-Based Engine...")
        self.mapping_service = mapping_service

        # ── 1. Movie metadata ───────────────────────────────────────
        self.df = pd.read_csv(os.path.join(data_path, "movies_processed.csv"))
        self.df["title_norm"] = self.df["title"].str.lower().str.strip()
        self.df["genres_list"] = self.df["genres"].apply(parse_list_field)
        self.df["genres_norm"] = self.df["genres_list"].apply(lambda gs: {g.lower() for g in gs})

        # Resolve external IDs once (instead of per-response lookups)
        if self.mapping_service:
            self.df["tmdbId"] = self.df["movieId"].map(self.mapping_service.get_tmdb_id).fillna(-1).astype(int)
            self.df["imdbId"] = self.df["movieId"].map(self.mapping_service.get_imdb_id).fillna(-1).astype(int)
        else:
            for col in ("tmdbId", "imdbId"):
                if col not in self.df.columns:
                    self.df[col] = -1

        self.all_genres = set().union(*self.df["genres_norm"])
        # Precomputed genre -> row indices (popular titles with posters first)
        has_tmdb = self.df["tmdbId"].to_numpy() > 0
        self.genre_mask = {
            g: self.df["genres_norm"].apply(lambda gs, g=g: g in gs).to_numpy() for g in self.all_genres
        }
        self.genre_index = {g: np.flatnonzero(m & has_tmdb) for g, m in self.genre_mask.items()}
        self.id_to_idx = {int(m): i for i, m in enumerate(self.df["movieId"])}

        # Discovery pool: movies with valid TMDB IDs (posters)
        self.discover_pool = np.flatnonzero(self.df["tmdbId"].to_numpy() > 0).tolist()

        # ── 2. Numpy-only CSR components ────────────────────────────
        self.data = np.load(os.path.join(model_path, "tfidf_data.npy"))
        self.indices = np.load(os.path.join(model_path, "tfidf_indices.npy"))
        self.indptr = np.load(os.path.join(model_path, "tfidf_indptr.npy"))
        with open(os.path.join(model_path, "tfidf_shape.txt"), "r") as f:
            rows, cols = f.read().strip().split(",")
            self.num_rows, self.num_cols = int(rows), int(cols)

        if self.num_rows != len(self.df):
            raise ValueError(f"TF-IDF rows ({self.num_rows}) != movies count ({len(self.df)})")

        # ── 3. Row map for vectorized dot products (no Python loop) ──
        self.row_map = build_row_map(self.indptr, self.num_rows)

        # ── 4. Fuzzy search pool (titles without year) ──────────────
        self._fuzzy_map = {
            re.sub(r"\s+\(\d{4}\)$", "", str(title)): title
            for title in self.df["title"].iloc[:40000]
        }
        self._fuzzy_choices = list(self._fuzzy_map.keys())

        print(f"  ✅ Content Engine ready — {len(self.df):,} movies.")

    # ── Public API ──────────────────────────────────────────────────

    def search(self, query: str, limit: int = 15) -> tuple[list[dict], str | None]:
        """Search movies by title (or exact genre) with fuzzy fallback."""
        q = query.lower().strip()
        if q in self.all_genres:
            # Genre pills (e.g. "Comedy", "Sci-Fi") search by genre, not title
            hits = self.df.iloc[self.genre_index[q][:limit]]
        else:
            hits = self.df[self.df["title_norm"].str.contains(q, na=False, regex=False)]
        results = [self._format(row) for row in hits.head(limit).to_dict("records")]

        suggestion = None
        if not results:
            match = get_fuzzy_suggestion(query, self._fuzzy_choices, threshold=0.5)
            if match:
                suggestion = self._fuzzy_map.get(match)
        return results, suggestion

    def recommend(self, movie_id: int, top_n: int = 12, genre: str | None = None) -> list[dict]:
        """Vectorized content-based recommendations (O(nnz))."""
        idx = self.id_to_idx.get(movie_id)
        if idx is None:
            return []
        scores = sparse_row_scores(
            self.data, self.indices, self.row_map, self.indptr, idx, self.num_rows, self.num_cols
        )
        if scores is None:
            return []

        if genre:
            allowed = self.genre_mask.get(genre.lower())
            if allowed is None:
                return []
            scores = np.where(allowed, scores, 0.0)

        top = top_n_indices(scores, top_n, exclude_idx=idx)
        seed = self.df.iloc[idx]
        rows = self.df.iloc[top].to_dict("records")
        return [
            {
                **self._format(row, score=self._normalize_score(float(scores[i])), mode="content"),
                "reasons": self._explain(seed, row),
            }
            for row, i in zip(rows, top)
        ]

    @staticmethod
    def _explain(seed, row) -> list[str]:
        """Human-readable reasons why `row` matched `seed` (shared metadata)."""
        reasons = []
        shared = [g for g in row["genres_list"] if g.lower() in seed["genres_norm"]]
        if shared:
            reasons.append("Both " + " + ".join(shared[:3]))
        franchise = re.sub(r"\s*\(\d{4}\)$", "", str(seed["title"])).split(":")[0].strip().lower()
        if len(franchise) > 3 and franchise in str(row["title"]).lower():
            reasons.append("Same franchise")
        sy, ry = seed.get("release_year"), row.get("release_year")
        if pd.notna(sy) and pd.notna(ry) and abs(sy - ry) <= 5:
            reasons.append(f"Same era ({int(ry) // 10 * 10}s)")
        return reasons or ["Similar themes & tags"]

    def discover(self, limit: int = 24, offset: int = 0) -> list[dict]:
        """Return a deterministic page of movies from the discovery pool."""
        sample = self.discover_pool[offset: offset + limit]
        return [self._format(row) for row in self.df.iloc[sample].to_dict("records")]

    def random_pick(self) -> dict | None:
        """Return a random movie with a valid poster (Surprise Me)."""
        if not self.discover_pool:
            return None
        return self._format(self.df.iloc[random.choice(self.discover_pool)].to_dict())

    def get_item(self, movie_id: int) -> dict | None:
        idx = self.id_to_idx.get(movie_id)
        return None if idx is None else self._format(self.df.iloc[idx].to_dict())

    def get_by_ids(self, movie_ids) -> list[dict]:
        """Look up movies by movieId, preserving order and skipping unknowns."""
        idxs = [self.id_to_idx[m] for m in movie_ids if m in self.id_to_idx]
        return [self._format(row) for row in self.df.iloc[idxs].to_dict("records")]

    # ── Helpers ─────────────────────────────────────────────────────

    def _format(self, movie: dict, score=None, mode="content") -> dict:
        return format_movie_response(movie, score=score, mode=mode)

    @staticmethod
    def _normalize_score(score: float) -> float:
        if score <= 0:
            return 0.0
        return round(min(0.98, 0.5 + score * 0.5), 4)
