"""
iTunes / Apple Music public APIs (no key, no account)
=====================================================
Free fallback for new songs when Spotify isn't available:
  - Top songs chart:  https://rss.marketingtools.apple.com/api/v2/<cc>/music/most-played/<n>/songs.json
  - Search / lookup:  https://itunes.apple.com/search , /lookup
Tracks come with cover art and a 30-second preview clip.
Set ITUNES_FALLBACK=0 to disable.
"""
import asyncio
import os
import re
import time
from typing import Any, Dict

import httpx

SEARCH_URL = "https://itunes.apple.com/search"
LOOKUP_URL = "https://itunes.apple.com/lookup"
CHART_URL = "https://rss.marketingtools.apple.com/api/v2/{cc}/music/most-played/{n}/songs.json"
ITUNES_ID = re.compile(r"^it(\d{1,12})$")


def parse_itunes_id(item_id) -> int | None:
    m = ITUNES_ID.match(str(item_id))
    return int(m.group(1)) if m else None


def artwork(url: str | None, size: int = 300) -> str | None:
    """Apple artwork URLs end in /100x100bb.jpg — any size can be requested."""
    if not url or not url.startswith("https://"):
        return None
    return re.sub(r"/\d+x\d+bb\.(jpg|png)$", f"/{size}x{size}bb.jpg", url)


class ITunesService:
    def __init__(self):
        self.enabled = os.getenv("ITUNES_FALLBACK", "1") != "0"
        self.country = os.getenv("INKPICK_COUNTRY", os.getenv("SPOTIFY_MARKET", "IN")).lower()
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(6)
        self._cache: Dict[str, tuple[float, Any]] = {}

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(6.0, connect=3.0), follow_redirects=True)
        return self._client

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get(self, url: str, params: Dict[str, Any] | None = None, ttl: float = 3600):
        if not self.enabled:
            return None
        params = params or {}
        key = url + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        hit = self._cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        async with self._semaphore:
            try:
                r = await self._get_client().get(url, params=params)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                print(f"⚠️ iTunes request failed: {e}")
                return hit[1] if hit else None
        if len(self._cache) > 1000:
            self._cache.clear()
        self._cache[key] = (time.monotonic() + ttl, data)
        return data

    async def top_songs(self, limit: int = 20) -> list[dict]:
        """Most-played chart, enriched via lookup (preview, album, artist id)."""
        n = 25 if limit <= 25 else 50
        data = await self._get(CHART_URL.format(cc=self.country, n=n), ttl=3 * 3600)
        chart = ((data or {}).get("feed") or {}).get("results") or []
        ids = [c["id"] for c in chart if str(c.get("id", "")).isdigit()][:limit]
        tracks = {str(t.get("trackId")): t for t in await self.lookup(ids)}
        # Keep chart order; fall back to the chart entry if lookup missed it
        return [tracks.get(c["id"]) or {
            "trackId": int(c["id"]), "trackName": c.get("name"), "artistName": c.get("artistName"),
            "artistId": int(c["artistId"]) if str(c.get("artistId", "")).isdigit() else None,
            "releaseDate": c.get("releaseDate"), "artworkUrl100": c.get("artworkUrl100"),
            "trackViewUrl": c.get("url"), "kind": "song",
        } for c in chart if c.get("id") in ids]

    async def lookup(self, ids: list) -> list[dict]:
        ids = [str(i) for i in ids if str(i).isdigit()][:100]
        if not ids:
            return []
        data = await self._get(LOOKUP_URL, {"id": ",".join(ids), "country": self.country}, ttl=12 * 3600)
        return [r for r in (data or {}).get("results") or [] if r.get("kind") == "song"]

    async def search(self, term: str, limit: int = 20) -> list[dict]:
        data = await self._get(SEARCH_URL, {"term": term, "media": "music", "entity": "song",
                                            "limit": limit, "country": self.country})
        return [r for r in (data or {}).get("results") or [] if r.get("kind") == "song"]

    async def artist_songs(self, artist_id: int, limit: int = 12) -> list[dict]:
        data = await self._get(LOOKUP_URL, {"id": artist_id, "entity": "song", "limit": limit,
                                            "country": self.country}, ttl=12 * 3600)
        return [r for r in (data or {}).get("results") or [] if r.get("kind") == "song"]
