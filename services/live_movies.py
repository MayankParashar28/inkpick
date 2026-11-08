"""
Live Movies (TMDB)
==================
The MovieLens catalog ends in mid-2023. This service adds live data from
TMDB — trending, now playing, upcoming, search and recommendations — and
converts it to the same card format the rest of the app uses.

IDs: a movie that exists in the catalog keeps its catalog movieId (so the
full content/hybrid engine still works for it). A movie that only exists on
TMDB gets the id "t<tmdbId>", e.g. "t693134".
"""
import re
from typing import Any, Dict

from services.tmdb import TMDBService, slim

# Official TMDB movie genre ids (stable), named like the catalog's genres
TMDB_GENRES = {
    28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy", 80: "Crime",
    99: "Documentary", 18: "Drama", 10751: "Children", 14: "Fantasy", 36: "History",
    27: "Horror", 10402: "Musical", 9648: "Mystery", 10749: "Romance", 878: "Sci-Fi",
    10770: "TV Movie", 53: "Thriller", 10752: "War", 37: "Western",
}
LIVE_ID = re.compile(r"^t(\d{1,10})$")
CATALOG_CUTOFF_YEAR = 2023


def parse_live_id(item_id: str) -> int | None:
    m = LIVE_ID.match(str(item_id))
    return int(m.group(1)) if m else None


class LiveMovies:
    def __init__(self, tmdb: TMDBService, movie_engine):
        self.tmdb = tmdb
        self.engine = movie_engine

    @property
    def enabled(self) -> bool:
        return bool(self.tmdb.api_key)

    # ── Conversion ──────────────────────────────────────────────
    def to_card(self, r: Dict[str, Any]) -> Dict[str, Any] | None:
        tmdb_id = r.get("id")
        title = (r.get("title") or "").strip()
        if not tmdb_id or not title:
            return None
        year = (r.get("release_date") or "")[:4]
        meta = slim(r) or {}
        genres = r.get("genre_ids")
        if genres is not None:
            meta["genres"] = [TMDB_GENRES[g] for g in genres if g in TMDB_GENRES]

        movie_id = self.engine.tmdb_to_movie.get(int(tmdb_id))
        if movie_id is not None:
            item = self.engine.get_item(movie_id)
            if item:
                return {**item, "cached": {**meta, **(item.get("cached") or {})}, "source": "catalog"}

        return {
            "movieId": f"t{tmdb_id}",
            "title": f"{title} ({year})" if year else title,
            "genres": meta.get("genres", []),
            "releaseYear": int(year) if year.isdigit() else None,
            "tmdbId": int(tmdb_id),
            "imdbId": -1,
            "similarity": None,
            "mode": "live",
            "source": "tmdb",
            "cached": meta,
        }

    def _cards(self, results: list) -> list[dict]:
        cards, seen = [], set()
        for r in results:
            card = self.to_card(r)
            if card and card["tmdbId"] not in seen:
                seen.add(card["tmdbId"])
                cards.append(card)
        return cards

    # ── Public API ──────────────────────────────────────────────
    async def fresh(self, kind: str, page: int = 1) -> list[dict]:
        return self._cards(await self.tmdb.list_movies(kind, page))

    async def search(self, query: str, catalog_hits: list[dict], limit: int) -> list[dict]:
        """Merge TMDB search into catalog results: newer/unknown titles first."""
        if not self.enabled or len(query) < 3:
            return catalog_hits
        have = {h.get("tmdbId") for h in catalog_hits}
        live = [c for c in self._cards(await self.tmdb.search_movies(query))
                if c["tmdbId"] not in have and c["source"] == "tmdb"]
        newer = [c for c in live if (c["releaseYear"] or 0) >= CATALOG_CUTOFF_YEAR]
        older = [c for c in live if c not in newer]
        return (newer + catalog_hits + older)[:limit]

    async def get_item(self, tmdb_id: int) -> dict | None:
        if not self.enabled:
            return None
        details = await self.tmdb.get_movie_details(tmdb_id)
        if not details or details.get("title") in (None, "Unknown"):
            return None
        details = {**details, "genre_ids": [g["id"] for g in details.get("genres", []) if isinstance(g, dict)]}
        return self.to_card(details)

    async def recommend(self, tmdb_id: int, top_n: int = 12) -> list[dict]:
        seed = await self.get_item(tmdb_id)
        seed_genres = {g.lower() for g in (seed or {}).get("genres", [])}
        cards = [c for c in self._cards(await self.tmdb.recommendations(tmdb_id)) if c["tmdbId"] != tmdb_id]
        for c in cards[:top_n]:
            shared = [g for g in c.get("genres", []) if g.lower() in seed_genres][:3]
            c["reasons"] = (["Both " + " + ".join(shared)] if shared else []) + ["Popular with TMDB viewers of this film"]
            c["mode"] = "live"
        return cards[:top_n]
