"""
Spotify Web API (Client Credentials flow)
=========================================
Server-to-server access for public catalog data — no user login.
Needs SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET (never commit them).

Note: since Nov 2024 Spotify blocks new apps from audio features,
recommendations and previews, so this only uses search, new releases,
albums, tracks and artist top tracks.
"""
import asyncio
import base64
import os
import time
from typing import Any, Dict

import httpx

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"


class SpotifyService:
    def __init__(self):
        self.client_id = os.getenv("SPOTIFY_CLIENT_ID")
        self.client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        self.market = os.getenv("SPOTIFY_MARKET", "IN")
        self._token: str | None = None
        self._token_expires = 0.0
        self._token_lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(6)
        self._cache: Dict[str, tuple[float, Any]] = {}
        self.last_error: str | None = None   # surfaced in /health and /songs/fresh

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(6.0, connect=3.0))
        return self._client

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get_token(self, force: bool = False) -> str | None:
        if not self.enabled:
            return None
        async with self._token_lock:
            if self._token and not force and time.monotonic() < self._token_expires - 60:
                return self._token
            basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
            try:
                r = await self._get_client().post(
                    TOKEN_URL, data={"grant_type": "client_credentials"},
                    headers={"Authorization": f"Basic {basic}"},
                )
                r.raise_for_status()
                body = r.json()
            except Exception as e:
                print(f"⚠️ Spotify token request failed: {e}")
                self.last_error = "Spotify rejected the client ID/secret."
                return None
            self._token = body.get("access_token")
            self._token_expires = time.monotonic() + float(body.get("expires_in", 3600))
            return self._token

    async def get(self, path: str, params: Dict[str, Any] | None = None, ttl: float = 3600) -> Dict[str, Any] | None:
        """GET /v1/<path> with token refresh, short TTL cache and stale-on-error."""
        params = {k: v for k, v in (params or {}).items() if v is not None}
        key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        hit = self._cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        token = await self._get_token()
        if not token:
            return hit[1] if hit else None
        async with self._semaphore:
            try:
                r = await self._get_client().get(f"{API_URL}/{path}", params=params,
                                                 headers={"Authorization": f"Bearer {token}"})
                if r.status_code == 401:   # token expired early: refresh once
                    token = await self._get_token(force=True)
                    r = await self._get_client().get(f"{API_URL}/{path}", params=params,
                                                     headers={"Authorization": f"Bearer {token}"})
                if r.status_code == 404:
                    return None
                if r.status_code in (401, 403):
                    # e.g. "Active premium subscription required for the owner of the app."
                    self.last_error = (r.text or f"HTTP {r.status_code}").strip()[:200]
                r.raise_for_status()
                data = r.json()
                self.last_error = None
            except Exception as e:
                print(f"⚠️ Spotify GET {path} failed: {e}")
                return hit[1] if hit else None
        if len(self._cache) > 1000:
            self._cache.clear()
        self._cache[key] = (time.monotonic() + ttl, data)
        return data

    # ── Endpoints ───────────────────────────────────────────────
    async def search_tracks(self, query: str, limit: int = 20) -> list[dict]:
        data = await self.get("search", {"q": query, "type": "track", "limit": limit, "market": self.market})
        return ((data or {}).get("tracks") or {}).get("items") or []

    async def new_release_albums(self, limit: int = 20) -> list[dict]:
        data = await self.get("browse/new-releases", {"limit": limit, "country": self.market}, ttl=6 * 3600)
        return ((data or {}).get("albums") or {}).get("items") or []

    async def albums(self, album_ids: list[str]) -> list[dict]:
        if not album_ids:
            return []
        data = await self.get("albums", {"ids": ",".join(album_ids[:20]), "market": self.market}, ttl=6 * 3600)
        return [a for a in (data or {}).get("albums") or [] if a]

    async def track(self, track_id: str) -> dict | None:
        return await self.get(f"tracks/{track_id}", {"market": self.market}, ttl=24 * 3600)

    async def artist_top_tracks(self, artist_id: str) -> list[dict]:
        data = await self.get(f"artists/{artist_id}/top-tracks", {"market": self.market}, ttl=12 * 3600)
        return (data or {}).get("tracks") or []
