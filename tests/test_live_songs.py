"""Live Spotify songs — the Spotify API is mocked, never called for real."""
import httpx
import pytest

NEW_ID = "N" * 22           # a 2025 track not in the catalog
ARTIST = {"id": "artist1", "name": "Anuv Jain"}
IMAGES = [{"url": "https://i.scdn.co/image/640", "width": 640},
          {"url": "https://i.scdn.co/image/300", "width": 300},
          {"url": "https://i.scdn.co/image/64", "width": 64}]
ALBUM = {"id": "alb1", "name": "Fresh Album", "release_date": "2025-03-01", "images": IMAGES}
NEW_TRACK = {"id": NEW_ID, "name": "Brand New Song", "artists": [ARTIST], "album": ALBUM}
CATALOG_TRACK = {"id": "0NLkVxf0PyxsXBG3EuZcJf", "name": "Gul", "artists": [ARTIST], "album": ALBUM}
TOP_TRACK = {"id": "T" * 22, "name": "Hit Song", "artists": [ARTIST], "album": ALBUM}
calls = []


def spotify_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    calls.append(path)
    if path == "/api/token":
        assert request.headers["authorization"].startswith("Basic ")
        return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
    assert request.headers["authorization"] == "Bearer tok"
    if path == "/v1/search":
        return httpx.Response(200, json={"tracks": {"items": [NEW_TRACK, CATALOG_TRACK]}})
    if path == "/v1/browse/new-releases":
        return httpx.Response(200, json={"albums": {"items": [{**ALBUM, "tracks": None}]}})
    if path == "/v1/albums":
        return httpx.Response(200, json={"albums": [{**ALBUM, "tracks": {"items": [
            {k: v for k, v in NEW_TRACK.items() if k != "album"}]}}]})
    if path == f"/v1/tracks/{NEW_ID}":
        return httpx.Response(200, json=NEW_TRACK)
    if path == "/v1/artists/artist1/top-tracks":
        return httpx.Response(200, json={"tracks": [NEW_TRACK, TOP_TRACK]})
    return httpx.Response(404)


@pytest.fixture
def live_spotify(client):
    import main
    svc = main.spotify_service
    saved = (svc.client_id, svc.client_secret, svc._client, svc._token)
    svc.client_id, svc.client_secret, svc._token = "id", "secret", None
    svc._client = httpx.AsyncClient(transport=httpx.MockTransport(spotify_handler))
    svc._cache.clear()
    calls.clear()
    yield svc
    svc.client_id, svc.client_secret, svc._client, svc._token = saved
    svc._cache.clear()


def test_without_credentials(client):
    assert client.get("/api/v1/songs/fresh").json() == {"results": [], "spotify_configured": False, "error": None}
    assert client.get(f"/api/v1/item/songs/{NEW_ID}").status_code == 404
    assert client.get("/api/v1/health").json()["spotify_configured"] is False


def test_fresh_songs(client, live_spotify):
    res = client.get("/api/v1/songs/fresh").json()["results"]
    assert len(res) == 1
    song = res[0]
    assert song["title"] == "Brand New Song" and song["releaseYear"] == 2025
    assert song["cover"] == "https://i.scdn.co/image/300", "picks the 300px image"
    assert song["tempo"] is None and song["source"] == "spotify"


def test_search_blends_new_tracks_first(client, live_spotify):
    res = client.get("/api/v1/search/songs?q=anuv jain&limit=6").json()["results"]
    assert res[0]["spotifyId"] == NEW_ID
    ids = [r["spotifyId"] for r in res]
    assert ids.count("0NLkVxf0PyxsXBG3EuZcJf") <= 1, "catalog track not duplicated"


def test_live_item_and_recommendations(client, live_spotify):
    assert client.get(f"/api/v1/item/songs/{NEW_ID}").json()["result"]["title"] == "Brand New Song"
    recs = client.get(f"/api/v1/recommend/songs/{NEW_ID}?limit=5").json()["recommendations"]
    ids = [r["spotifyId"] for r in recs]
    assert NEW_ID not in ids and ids[0] == "T" * 22
    assert all(r["reasons"][0] == "Also by Anuv Jain" for r in recs)
    assert any(r.get("source") != "spotify" for r in recs), "includes catalog songs by the artist"


def test_token_is_reused(client, live_spotify):
    client.get("/api/v1/songs/fresh")
    client.get(f"/api/v1/item/songs/{NEW_ID}")
    assert calls.count("/api/token") == 1


def test_invalid_song_ids_never_reach_spotify(client, live_spotify):
    assert client.get("/api/v1/item/songs/..%2F..%2Fme").status_code == 404
    assert client.get("/api/v1/recommend/songs/abc").status_code == 404
    assert not [c for c in calls if c.startswith("/v1/tracks")]


def test_premium_required_error_is_reported(client, live_spotify):
    import main
    msg = "Active premium subscription required for the owner of the app."
    original = live_spotify._client
    live_spotify._client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if r.url.path == "/api/token" else httpx.Response(403, text=msg)))
    body = client.get("/api/v1/songs/fresh").json()
    assert body["results"] == [] and body["error"] == msg
    assert client.get("/api/v1/health").json()["spotify_error"] == msg
    live_spotify._client = original
    live_spotify.last_error = None
