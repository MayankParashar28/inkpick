"""
Music Discovery Engine (Zero-Scipy / Vercel Optimized)
=====================================================
Serves ~90,000 song "sketches" via vectorized NumPy sparse math.
"""

import os
import random

import numpy as np
import pandas as pd

from modules.utils import (
    build_row_map,
    get_fuzzy_suggestion,
    safe_float,
    safe_str,
    sparse_row_scores,
    top_n_indices,
)


class MusicEngine:
    """The 'Playlist Scribbles' discovery engine."""

    def __init__(self, data_path: str = "processed/", model_path: str = "models/", mapping_service=None):
        print("  🎸 Loading Playlist Scribbles...")
        self.mapping_service = mapping_service

        self.df = pd.read_csv(os.path.join(data_path, "songs_processed.csv"))
        for col in ("name", "artists_clean", "album"):
            self.df[col] = self.df[col].fillna("Unknown")
        self.df["name_norm"] = self.df["name"].str.lower()
        self.df["artist_norm"] = self.df["artists_clean"].str.lower()
        self.id_to_idx = {sid: i for i, sid in enumerate(self.df["id"])}

        self.data = np.load(os.path.join(model_path, "songs_tfidf_data.npy"))
        self.indices = np.load(os.path.join(model_path, "songs_tfidf_indices.npy"))
        self.indptr = np.load(os.path.join(model_path, "songs_tfidf_indptr.npy"))
        with open(os.path.join(model_path, "songs_tfidf_shape.txt"), "r") as f:
            rows, cols = f.read().strip().split(",")
            self.num_rows, self.num_cols = int(rows), int(cols)

        self.row_map = build_row_map(self.indptr, self.num_rows)

        # Normalized audio features for the mood mixer
        self._energy = self.df["energy"].fillna(0).to_numpy(np.float32)
        self._dance = self.df["danceability"].fillna(0).to_numpy(np.float32)
        self._tempo = np.clip(self.df["tempo"].fillna(0).to_numpy(np.float32) / self.MOOD_TEMPO_MAX, 0, 1)

        self._fuzzy_choices = (
            self.df["name"].iloc[:40000].tolist()
            + self.df["artists_clean"].iloc[:5000].unique().tolist()
        )
        print(f"  ✅ Music Engine ready — {len(self.df):,} tracks.")

    def search(self, query: str, limit: int = 15) -> tuple[list[dict], str | None]:
        """Search songs by name or artist with fuzzy fallback."""
        q = query.lower().strip()
        mask = (self.df["name_norm"].str.contains(q, na=False, regex=False)
                | self.df["artist_norm"].str.contains(q, na=False, regex=False))
        results = [self._format(row) for row in self.df[mask].head(limit).to_dict("records")]
        suggestion = None if results else get_fuzzy_suggestion(query, self._fuzzy_choices)
        return results, suggestion

    def recommend(self, song_id: str, top_n: int = 12, genre: str | None = None) -> list[dict]:
        """Acoustically/textually similar tracks via sparse cosine scores."""
        idx = self.id_to_idx.get(song_id)
        if idx is None or idx >= self.num_rows:
            return []
        scores = sparse_row_scores(
            self.data, self.indices, self.row_map, self.indptr, idx, self.num_rows, self.num_cols
        )
        if scores is None:
            return []
        top = top_n_indices(scores, top_n, exclude_idx=idx)
        seed = self.df.iloc[idx]
        rows = self.df.iloc[top].to_dict("records")
        return [{**self._format(row, scores[i]), "reasons": self._explain(seed, row)} for row, i in zip(rows, top)]

    @staticmethod
    def _explain(seed, row) -> list[str]:
        reasons = []
        seed_artists = {a.strip().lower() for a in str(seed["artists_clean"]).split(";")}
        shared = [a.strip() for a in str(row["artists_clean"]).split(";") if a.strip().lower() in seed_artists]
        if shared:
            reasons.append(f"Also by {shared[0]}")
        if abs(safe_float(seed["tempo"]) - safe_float(row["tempo"])) <= 8:
            reasons.append(f"Similar tempo (~{round(safe_float(row['tempo']))} BPM)")
        if abs(safe_float(seed["energy"]) - safe_float(row["energy"])) <= 0.1:
            reasons.append("Matching energy")
        if abs(safe_float(seed["year"]) - safe_float(row["year"])) <= 2:
            reasons.append(f"Same period ({int(safe_float(row['year']))})")
        return reasons or ["Similar style & keywords"]

    # ── Mood mixer ──────────────────────────────────────────────────
    MOOD_TEMPO_MAX = 220.0

    def mood(self, energy=None, danceability=None, tempo=None, limit: int = 24) -> list[dict]:
        """Songs closest to a target mood (energy/danceability 0-1, tempo in BPM)."""
        dims = []
        if energy is not None:
            dims.append((self._energy, float(energy)))
        if danceability is not None:
            dims.append((self._dance, float(danceability)))
        if tempo is not None:
            dims.append((self._tempo, float(tempo) / self.MOOD_TEMPO_MAX))
        if not dims or self.df.empty:
            return self.discover(limit=limit)
        dist = np.zeros(len(self.df), dtype=np.float32)
        for col, target in dims:
            dist += (col - target) ** 2
        k = min(limit, len(dist))
        top = np.argpartition(dist, k - 1)[:k]
        top = top[np.argsort(dist[top])]
        rows = self.df.iloc[top].to_dict("records")
        return [
            {**self._format(row), "similarity": round(float(max(0.0, 1 - np.sqrt(dist[i] / len(dims)))), 4)}
            for row, i in zip(rows, top)
        ]

    def get_item(self, song_id: str) -> dict | None:
        idx = self.id_to_idx.get(song_id)
        return None if idx is None else self._format(self.df.iloc[idx].to_dict())

    def suggest(self, query: str, limit: int = 8) -> list[dict]:
        """Fast type-ahead: titles starting with the query first, then containing it."""
        q = query.lower().strip()
        col = self.df["name_norm"]
        starts = self.df[col.str.startswith(q, na=False)]
        if len(starts) < limit:
            contains = self.df[col.str.contains(q, na=False, regex=False) & ~col.str.startswith(q, na=False)]
            starts = pd.concat([starts, contains.head(limit - len(starts))])
        return [self._format(row) for row in starts.head(limit).to_dict("records")]

    def discover(self, limit: int = 24, offset: int = 0) -> list[dict]:
        return [self._format(row) for row in self.df.iloc[offset: offset + limit].to_dict("records")]

    def random_pick(self) -> dict | None:
        if self.df.empty:
            return None
        return self._format(self.df.iloc[random.randrange(len(self.df))].to_dict())

    @staticmethod
    def _format(song: dict, score=0.0) -> dict:
        """Maps Spotify metadata to the hand-drawn card format."""
        score = safe_float(score)
        year = safe_float(song.get("year"), default=None)
        return {
            "movieId": song["id"],
            "title": safe_str(song.get("name"), "Unknown"),
            "artist": safe_str(song.get("artists_clean"), "Unknown").replace(";", ", "),
            "album": safe_str(song.get("album"), "Unknown"),
            "releaseYear": int(year) if year else None,
            "tmdbId": -1,
            "spotifyId": song["id"],
            "similarity": round(score, 4) if score > 0 else 0,
            "tempo": safe_float(song.get("tempo"), ndigits=1),
            "energy": safe_float(song.get("energy"), ndigits=2),
            "danceability": safe_float(song.get("danceability"), ndigits=2),
        }
