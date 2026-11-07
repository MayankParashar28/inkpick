import asyncio
import json
import os
from typing import Any, Dict, Iterable

import httpx


# Only the fields the frontend uses — cuts payloads by ~75%
SLIM_FIELDS = ("id", "title", "poster_path", "backdrop_path", "overview", "tagline",
               "release_date", "runtime", "vote_average")


def slim(meta: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not meta:
        return meta
    out = {k: meta.get(k) for k in SLIM_FIELDS if k in meta}
    if meta.get("genres"):
        out["genres"] = [g.get("name") for g in meta["genres"] if isinstance(g, dict)]
    return out


def _stub(tmdb_id: int) -> Dict[str, Any]:
    return {"id": tmdb_id, "title": "Unknown", "poster_path": None, "overview": "", "vote_average": 0}


class TMDBService:
    def __init__(self, cache_file: str = "models/metadata_cache.json"):
        self.api_key = os.getenv("TMDB_API_KEY")
        self.base_url = os.getenv("TMDB_BASE_URL", "https://api.themoviedb.org/3")
        self.cache_file = cache_file
        self.dirty = False
        self.cache: Dict[str, Any] = self._load_cache()
        self.timeout = httpx.Timeout(4.0, connect=2.0)
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(8)

    # ── Lifecycle ────────────────────────────────────────────────
    def _get_client(self) -> httpx.AsyncClient:
        """Reuse a single pooled client instead of opening one per request."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self):
        self._save_cache()
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── Cache persistence ────────────────────────────────────────
    def _load_cache(self) -> Dict[str, Any]:
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ Cache load error: {e}")
        return {}

    def _save_cache(self):
        if not self.dirty:
            return
        try:
            os.makedirs(os.path.dirname(self.cache_file) or ".", exist_ok=True)
            tmp = f"{self.cache_file}.tmp"
            with open(tmp, "w") as f:
                json.dump(self.cache, f)
            os.replace(tmp, self.cache_file)  # atomic write, no corrupted cache
            self.dirty = False
        except Exception as e:
            print(f"⚠️ Cache save failed (expected on read-only filesystems like Vercel): {e}")

    # ── Fetching ─────────────────────────────────────────────────
    async def _fetch(self, tmdb_id: int) -> Dict[str, Any] | None:
        """Fetch one movie. Returns data, a cached stub on 404, or None on transient errors."""
        async with self._semaphore:
            try:
                response = await self._get_client().get(
                    f"{self.base_url}/movie/{tmdb_id}", params={"api_key": self.api_key}
                )
                if response.status_code == 404:
                    data = _stub(tmdb_id)  # cache misses so we don't retry forever
                else:
                    response.raise_for_status()
                    data = response.json()
                self.cache[str(tmdb_id)] = data
                self.dirty = True
                return data
            except Exception:
                return None

    async def get_movie_details(self, tmdb_id: int) -> Dict[str, Any]:
        """Fetch movie details (cached). Never raises — degrades to a stub."""
        key = str(tmdb_id)
        if key in self.cache:
            return self.cache[key]
        if not self.api_key:
            return _stub(tmdb_id)
        data = await self._fetch(tmdb_id)
        self._save_cache()
        return data or _stub(tmdb_id)

    async def batch_get_movie_details(self, tmdb_ids: Iterable[int]) -> Dict[str, Any]:
        """Fetch multiple movies concurrently. Returns {tmdbId: data}."""
        results: Dict[str, Any] = {}
        to_fetch = []
        for tid in dict.fromkeys(tmdb_ids):  # de-duplicate, keep order
            key = str(tid)
            if key in self.cache:
                results[key] = self.cache[key]
            elif tid and int(tid) > 0:
                to_fetch.append(int(tid))

        if not to_fetch or not self.api_key:
            return results

        fetched = await asyncio.gather(*(self._fetch(tid) for tid in to_fetch))
        for tid, data in zip(to_fetch, fetched):
            if data:
                results[str(tid)] = data
        self._save_cache()
        return results

    async def enrich(self, items: list) -> list:
        """Attach TMDB metadata under `cached` for every item with a valid tmdbId."""
        ids = [r["tmdbId"] for r in items if isinstance(r.get("tmdbId"), int) and r["tmdbId"] > 0]
        if ids:
            batch = await self.batch_get_movie_details(ids)
            for r in items:
                meta = batch.get(str(r.get("tmdbId")))
                if meta:
                    r["cached"] = slim(meta)
        return items

    def update_cache(self, tmdb_id: int, data: dict):
        self.cache[str(tmdb_id)] = data
        self.dirty = True
        self._save_cache()
