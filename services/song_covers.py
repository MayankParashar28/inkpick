"""
Song Covers (Spotify oEmbed)
============================
Album artwork for tracks via Spotify's public oEmbed endpoint — no API key.
https://open.spotify.com/oembed?url=https://open.spotify.com/track/<id>

Results (including misses) are cached in memory and persisted to
models/song_covers.json, which ships pre-filled for the first pages of the
catalog so the home page shows covers instantly.
"""
import asyncio
import json
import os
import re
from typing import Dict, Iterable

import httpx

OEMBED_URL = "https://open.spotify.com/oembed"
TRACK_ID = re.compile(r"^[A-Za-z0-9]{22}$")


def large_cover(url: str | None) -> str | None:
    """Spotify image ids encode the size: 00001e02 = 300px, 0000b273 = 640px."""
    return url.replace("ab67616d00001e02", "ab67616d0000b273") if url else url


class SongCoverService:
    def __init__(self, cache_file: str = "models/song_covers.json"):
        self.cache_file = cache_file
        self.covers: Dict[str, str | None] = self._load()
        self.dirty = False
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(8)

    def _load(self) -> Dict[str, str | None]:
        try:
            with open(self.cache_file) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self):
        if not self.dirty:
            return
        try:
            tmp = f"{self.cache_file}.tmp"
            with open(tmp, "w") as f:
                json.dump(self.covers, f, separators=(",", ":"))
            os.replace(tmp, self.cache_file)
            self.dirty = False
        except Exception:
            pass  # read-only filesystem (e.g. Vercel): memory cache still works

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0))
        return self._client

    async def close(self):
        self._save()
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def cached(self, track_id: str) -> str | None:
        return self.covers.get(track_id)

    def attach(self, items: list) -> list:
        """Add `cover` to song cards from the cache only (never blocks on the network)."""
        for item in items:
            url = self.covers.get(str(item.get("spotifyId")))
            if url:
                item["cover"] = url
        return items

    async def _fetch(self, track_id: str) -> tuple[str, str | None, bool]:
        """Returns (id, url, cacheable)."""
        async with self._semaphore:
            try:
                r = await self._get_client().get(
                    OEMBED_URL, params={"url": f"https://open.spotify.com/track/{track_id}"}
                )
                if r.status_code in (400, 404):
                    return track_id, None, True          # track gone: remember the miss
                r.raise_for_status()
                url = r.json().get("thumbnail_url")
                return track_id, url if isinstance(url, str) and url.startswith("https://") else None, True
            except Exception:
                return track_id, None, False             # transient: retry later

    async def batch(self, track_ids: Iterable[str]) -> Dict[str, str | None]:
        ids = [t for t in dict.fromkeys(track_ids) if isinstance(t, str) and TRACK_ID.match(t)]
        out = {t: self.covers[t] for t in ids if t in self.covers}
        missing = [t for t in ids if t not in self.covers]
        if missing:
            for track_id, url, cacheable in await asyncio.gather(*(self._fetch(t) for t in missing)):
                out[track_id] = url
                if cacheable:
                    self.covers[track_id] = url
                    self.dirty = True
            self._save()
        return out
