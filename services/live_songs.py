"""
Live Songs (Spotify)
====================
The song dataset ends in 2023. This adds live data from the Spotify Web API:
new releases, search, track lookup and "more by this artist" recommendations,
converted to the same card format as catalog songs.

Spotify track ids are the same ids the catalog uses, so a track that exists in
the catalog is served from the catalog (with full similarity recommendations).
"""
import re
from typing import Any, Dict

from services.spotify import SpotifyService

TRACK_ID = re.compile(r"^[A-Za-z0-9]{22}$")

NEW_RELEASE_YEAR = 2023


def pick_image(images: list | None, target: int = 300) -> str | None:
    """Album image closest to `target` px (Spotify lists 640, 300 and 64)."""
    usable = [i for i in images or [] if isinstance(i, dict) and str(i.get("url", "")).startswith("https://")]
    if not usable:
        return None
    return min(usable, key=lambda i: abs((i.get("width") or target) - target))["url"]


class LiveSongs:
    def __init__(self, spotify: SpotifyService, music_engine):
        self.spotify = spotify
        self.engine = music_engine

    @property
    def enabled(self) -> bool:
        return self.spotify.enabled

    def to_card(self, track: Dict[str, Any], album: Dict[str, Any] | None = None) -> Dict[str, Any] | None:
        track_id = track.get("id")
        name = (track.get("name") or "").strip()
        if not track_id or not name:
            return None
        album = album or track.get("album") or {}
        cover = pick_image(album.get("images"))

        catalog = self.engine.get_item(track_id)
        if catalog:
            return {**catalog, **({"cover": cover} if cover else {}), "source": "catalog"}

        year = (album.get("release_date") or "")[:4]
        artists = [a for a in track.get("artists") or [] if a.get("name")]
        card = {
            "movieId": track_id,
            "title": name,
            "artist": ", ".join(a["name"] for a in artists) or "Unknown",
            "album": album.get("name") or "Single",
            "releaseYear": int(year) if year.isdigit() else None,
            "tmdbId": -1,
            "spotifyId": track_id,
            "similarity": 0,
            "tempo": None,
            "energy": None,
            "danceability": None,
            "source": "spotify",
            "mode": "live",
            "artistIds": [a["id"] for a in artists if a.get("id")][:3],
        }
        if cover:
            card["cover"] = cover
        return card

    def _cards(self, tracks: list, album: dict | None = None) -> list[dict]:
        cards, seen = [], set()
        for t in tracks:
            card = self.to_card(t, album)
            if card and card["spotifyId"] not in seen:
                seen.add(card["spotifyId"])
                cards.append(card)
        return cards

    # ── Public API ──────────────────────────────────────────────
    async def fresh(self, limit: int = 20) -> list[dict]:
        """Lead track of each newly released album."""
        new_albums = await self.spotify.new_release_albums(limit)
        full = {a["id"]: a for a in await self.spotify.albums([a["id"] for a in new_albums if a.get("id")])}
        cards = []
        for simple in new_albums:
            album = full.get(simple.get("id")) or simple
            tracks = (album.get("tracks") or {}).get("items") or []
            if tracks:
                card = self.to_card(tracks[0], {**simple, **album})
                if card:
                    cards.append(card)
        return cards

    async def search(self, query: str, catalog_hits: list[dict], limit: int) -> list[dict]:
        """Blend Spotify search into catalog results: newer/unknown tracks first."""
        if not self.enabled or len(query) < 3:
            return catalog_hits
        have = {h.get("spotifyId") for h in catalog_hits}
        live = [c for c in self._cards(await self.spotify.search_tracks(query))
                if c["spotifyId"] not in have and c["source"] == "spotify"]
        newer = [c for c in live if (c["releaseYear"] or 0) >= NEW_RELEASE_YEAR]
        older = [c for c in live if c not in newer]
        return (newer + catalog_hits + older)[:limit]

    async def get_item(self, track_id: str) -> dict | None:
        if not self.enabled or not TRACK_ID.match(str(track_id)):
            return None
        track = await self.spotify.track(track_id)
        return self.to_card(track) if track else None

    async def recommend(self, track_id: str, top_n: int = 12) -> list[dict]:
        """No Spotify recommendations API for new apps: use the artist's top tracks
        plus catalog songs by the same artist."""
        if not self.enabled or not TRACK_ID.match(str(track_id)):
            return []
        track = await self.spotify.track(track_id)
        if not track:
            return []
        artists = [a for a in track.get("artists") or [] if a.get("id")]
        results, seen = [], {track_id}

        for artist in artists[:2]:
            for card in self._cards(await self.spotify.artist_top_tracks(artist["id"])):
                if card["spotifyId"] not in seen:
                    seen.add(card["spotifyId"])
                    card["reasons"] = [f"Also by {artist['name']}", "Popular right now on Spotify"]
                    results.append(card)

        if artists:
            hits, _ = self.engine.search(artists[0]["name"], limit=top_n)
            for card in hits:
                if card["spotifyId"] not in seen:
                    seen.add(card["spotifyId"])
                    card["reasons"] = [f"Also by {artists[0]['name']}"]
                    results.append(card)
        return results[:top_n]
