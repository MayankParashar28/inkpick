import pytest

DOMAINS = ["movies", "songs", "courses"]
SAMPLE_IDS = {"movies": "1", "songs": "0NLkVxf0PyxsXBG3EuZcJf", "courses": "1070968"}


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert set(body["categories"]) == set(DOMAINS)
    assert body["tmdb_configured"] is False


@pytest.mark.parametrize("domain", DOMAINS)
def test_discover_pages(client, domain):
    first = client.get(f"/api/v1/discover/{domain}?limit=5").json()["results"]
    second = client.get(f"/api/v1/discover/{domain}?limit=5&offset=5").json()["results"]
    assert len(first) == 5 and len(second) == 5
    assert {i["movieId"] for i in first}.isdisjoint({i["movieId"] for i in second})


@pytest.mark.parametrize("params", ["limit=0", "limit=-5", "limit=500", "offset=-1"])
def test_discover_rejects_bad_paging(client, params):
    assert client.get(f"/api/v1/discover/movies?{params}").status_code == 422


def test_unknown_domain_404(client):
    assert client.get("/api/v1/discover/podcasts").status_code == 404
    assert client.get("/api/v1/recommend/podcasts/1").status_code == 404


@pytest.mark.parametrize("domain", DOMAINS)
def test_recommend_every_domain_with_reasons(client, domain):
    r = client.get(f"/api/v1/recommend/{domain}/{SAMPLE_IDS[domain]}?limit=5")
    assert r.status_code == 200, r.text
    recs = r.json()["recommendations"]
    assert 0 < len(recs) <= 5
    assert all(str(x["movieId"]) != SAMPLE_IDS[domain] for x in recs), "seed must not recommend itself"
    assert all(isinstance(x["reasons"], list) and x["reasons"] for x in recs)


def test_movie_recs_are_relevant(client):
    recs = client.get("/api/v1/recommend/movies/1?limit=5").json()["recommendations"]
    titles = [r["title"] for r in recs]
    assert any("Toy Story" in t for t in titles)
    assert all(isinstance(r["genres"], list) for r in recs)


def test_movie_genre_filter(client):
    recs = client.get("/api/v1/movies/recommend/1?genre=Comedy&limit=6").json()["recommendations"]
    assert recs and all("Comedy" in r["genres"] for r in recs)
    assert client.get("/api/v1/movies/recommend/1?genre=NoSuchGenre").status_code == 404


def test_invalid_ids(client):
    assert client.get("/api/v1/recommend/movies/abc").status_code == 400
    assert client.get("/api/v1/recommend/courses/abc").status_code == 400
    assert client.get("/api/v1/recommend/movies/999999999").status_code == 404


def test_search_and_fuzzy_suggestion(client):
    hits = client.get("/api/v1/search/movies?q=toy story").json()["results"]
    assert any(h["movieId"] == 1 for h in hits)
    miss = client.get("/api/v1/search/movies?q=Inceptoin").json()
    assert miss["results"] == [] and miss["suggestion"] == "Inception (2010)"


def test_search_genre_pill(client):
    hits = client.get("/api/v1/search/movies?q=Sci-Fi&limit=5").json()["results"]
    assert len(hits) == 5 and all("Sci-Fi" in h["genres"] for h in hits)


def test_search_sanitizes_input(client):
    r = client.get("/api/v1/search/songs?q=<script>")
    assert r.status_code == 200


@pytest.mark.parametrize("domain,q", [("movies", "toy"), ("songs", "kes"), ("courses", "pyth")])
def test_suggest_prefix_first(client, domain, q):
    res = client.get(f"/api/v1/suggest/{domain}?q={q}&limit=5").json()["results"]
    assert 0 < len(res) <= 5
    assert res[0]["title"].lower().startswith(q)
    assert "cached" not in res[0], "suggestions must stay lightweight"


def test_suggest_short_query_empty(client):
    assert client.get("/api/v1/suggest/movies?q=a").json()["results"] == []


def test_mood_mixer_matches_target(client):
    res = client.get("/api/v1/songs/mood?energy=0.9&danceability=0.8&tempo=128&limit=5").json()["results"]
    assert len(res) == 5
    for s in res:
        assert abs(s["energy"] - 0.9) < 0.1
        assert abs(s["danceability"] - 0.8) < 0.1
        assert abs(s["tempo"] - 128) < 10
    assert client.get("/api/v1/songs/mood?energy=2").status_code == 422


@pytest.mark.parametrize("domain", DOMAINS)
def test_item_lookup(client, domain):
    r = client.get(f"/api/v1/item/{domain}/{SAMPLE_IDS[domain]}")
    assert r.status_code == 200
    assert str(r.json()["result"]["movieId"]) == SAMPLE_IDS[domain]


def test_item_lookup_missing(client):
    assert client.get("/api/v1/item/songs/does-not-exist").status_code == 404


@pytest.mark.parametrize("domain", DOMAINS)
def test_surprise(client, domain):
    r = client.get(f"/api/v1/surprise/{domain}")
    assert r.status_code == 200 and r.json()["result"]["title"]


def test_tmdb_batch_validation(client):
    assert client.post("/api/v1/tmdb/batch", json={"ids": "abc"}).status_code == 422
    assert client.post("/api/v1/tmdb/batch", json={"ids": list(range(51))}).status_code == 422
    ok = client.post("/api/v1/tmdb/batch", json={"ids": [862]}).json()["results"]
    if "862" in ok:   # served from the bundled cache
        assert "production_companies" not in ok["862"], "metadata must be slimmed"


def test_trailer_without_api_key(client):
    body = client.get("/api/v1/movies/862/trailer").json()
    assert body == {"trailer": None, "tmdb_configured": False}


def test_metadata_cache_requires_secret(client):
    r = client.post("/api/v1/metadata/cache", json={"tmdbId": 1, "data": {}})
    assert r.status_code == 403


def test_cache_headers(client):
    assert "immutable" in client.get("/static/assets/robot.glb").headers["cache-control"]
    assert client.get("/static/index.html").headers["cache-control"] == "no-cache"
    assert "max-age" in client.get("/api/v1/discover/songs?limit=1").headers["cache-control"]


def test_song_cover_batch_validation(client):
    assert client.post("/api/v1/songs/covers", json={"ids": "x"}).status_code == 422
    assert client.post("/api/v1/songs/covers", json={"ids": ["x"] * 51}).status_code == 422
    # Malformed ids are ignored (never forwarded to Spotify)
    assert client.post("/api/v1/songs/covers", json={"ids": ["../../etc", "short"]}).json() == {"covers": {}}


def test_song_covers_attached_from_cache(client):
    first = client.get("/api/v1/discover/songs?limit=3").json()["results"]
    assert all(s.get("cover", "").startswith("https://") for s in first), "bundled cover cache"
