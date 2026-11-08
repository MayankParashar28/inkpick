"""
Live Songs (Spotify, with a free iTunes fallback)
=================================================
The song dataset ends in 2023. This adds live data — new releases, search,
track lookup and "more by this artist" recommendations — converted to the
same card format as catalog songs.

Spotify is used first. When it is not configured or refuses (e.g. the app
owner has no Premium), Apple's free iTunes APIs are used instead; those
tracks get ids like "it1831237608" and come with 30-second previews.

Spotify track ids are the same ids the catalog uses, so a track that exists in
the catalog is served from the catalog (with full similarity recommendations).
"""
import re
from typing import Any, Dict

from services.itunes import ITunesService, artwork, parse_itunes_id
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
    def __init__(self, spotify: SpotifyService, music_engine, itunes: ITunesService | None = None):
        self.spotify = spotify
        self.engine = music_engine
        self.itunes = itunes

    @property
    def enabled(self) -> bool:
        return self.spotify.enabled or bool(self.itunes and self.itunes.enabled)

    # ── iTunes conversion ───────────────────────────────────────
    @staticmethod
    def itunes_card(t: Dict[str, Any]) -> Dict[str, Any] | None:
        track_id = t.get("trackId")
        name = re.sub(r"\s+", " ", t.get("trackName") or "").strip()
        if not track_id or not name:
            return None
        year = (t.get("releaseDate") or "")[:4]
        preview = t.get("previewUrl")
        card = {
            "movieId": f"it{track_id}",
            "title": name,
            "artist": t.get("artistName") or "Unknown",
            "album": re.sub(r" - Single$", "", t.get("collectionName") or "Single"),
            "releaseYear": int(year) if year.isdigit() else None,
            "tmdbId": -1,
            "itunesId": int(track_id),
            "artistId": t.get("artistId"),
            "similarity": 0,
            "tempo": None,
            "energy": None,
            "danceability": None,
            "source": "itunes",
            "mode": "live",
            "genre": t.get("primaryGenreName"),
        }
        cover = artwork(t.get("artworkUrl100"), 300)
        if cover:
            card["cover"] = cover
        if isinstance(preview, str) and preview.startswith("https://"):
            card["preview"] = preview
        if isinstance(t.get("trackViewUrl"), str) and t["trackViewUrl"].startswith("https://"):
            card["appleUrl"] = t["trackViewUrl"]
        return card

    def _itunes_cards(self, tracks: list) -> list[dict]:
        cards, seen = [], set()
        for t in tracks:
            card = self.itunes_card(t)
            if card and card["itunesId"] not in seen:
                seen.add(card["itunesId"])
                cards.append(card)
        return cards

    @staticmethod
    def _song_key(card: dict) -> tuple:
        first_artist = re.split(r",|&| x | feat", (card.get("artist") or "").lower())[0].strip()
        return (re.sub(r"\W+", "", (card.get("title") or "").lower()), first_artist)

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
    async def fresh(self, limit: int = 20) -> tuple[list[dict], str | None]:
        """New releases from Spotify, else Apple's top-songs chart. Returns (cards, source)."""
        cards = await self._spotify_fresh(limit) if self.spotify.enabled else []
        if cards:
            return cards, "spotify"
        if self.itunes and self.itunes.enabled:
            cards = self._itunes_cards(await self.itunes.top_songs(limit))
            if cards:
                return cards, "itunes"
        return [], None

    async def _spotify_fresh(self, limit: int) -> list[dict]:
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
        live = []
        if self.spotify.enabled:
            live = [c for c in self._cards(await self.spotify.search_tracks(query))
                    if c["spotifyId"] not in have and c["source"] == "spotify"]
        if not live and self.itunes and self.itunes.enabled:
            known = {self._song_key(h) for h in catalog_hits}
            live = [c for c in self._itunes_cards(await self.itunes.search(query))
                    if self._song_key(c) not in known]
        newer = [c for c in live if (c["releaseYear"] or 0) >= NEW_RELEASE_YEAR]
        older = [c for c in live if c not in newer]
        return (newer + catalog_hits + older)[:limit]

    async def get_item(self, track_id: str) -> dict | None:
        itunes_id = parse_itunes_id(track_id)
        if itunes_id is not None:
            if not (self.itunes and self.itunes.enabled):
                return None
            found = self._itunes_cards(await self.itunes.lookup([itunes_id]))
            return found[0] if found else None
        if not self.spotify.enabled or not TRACK_ID.match(str(track_id)):
            return None
        track = await self.spotify.track(track_id)
        return self.to_card(track) if track else None

    async def recommend(self, track_id: str, top_n: int = 12) -> list[dict]:
        """No Spotify recommendations API for new apps: use the artist's top tracks
        plus catalog songs by the same artist."""
        if parse_itunes_id(track_id) is not None:
            return await self._itunes_recommend(track_id, top_n)
        if not self.spotify.enabled or not TRACK_ID.match(str(track_id)):
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

    async def _itunes_recommend(self, track_id: str, top_n: int) -> list[dict]:
        seed = await self.get_item(track_id)
        if not seed:
            return []
        artist = seed["artist"]
        results, seen = [], {seed["itunesId"]}
        if seed.get("artistId"):
            for card in self._itunes_cards(await self.itunes.artist_songs(seed["artistId"], limit=top_n + 1)):
                if card["itunesId"] not in seen:
                    seen.add(card["itunesId"])
                    card["reasons"] = [f"Also by {artist}"]
                    results.append(card)
        main_artist = re.split(r",|&", artist)[0].strip()
        if main_artist:
            hits, _ = self.engine.search(main_artist, limit=top_n)
            known = {self._song_key(r) for r in results}
            for card in hits:
                if self._song_key(card) not in known:
                    card["reasons"] = [f"Also by {main_artist}"]
                    results.append(card)
        return results[:top_n]
