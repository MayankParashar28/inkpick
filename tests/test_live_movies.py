"""Live TMDB movies (new releases) — TMDB is mocked, never called for real."""
import httpx
import pytest

DUNE_2 = {"id": 693134, "title": "Dune: Part Two", "release_date": "2024-02-27",
          "poster_path": "/dune2.jpg", "overview": "Paul joins the Fremen.", "vote_average": 8.2,
          "genre_ids": [878, 12], "budget": 190000000}
TOY_STORY = {"id": 862, "title": "Toy Story", "release_date": "1995-10-30", "poster_path": "/ts.jpg",
             "genre_ids": [16, 35]}
DEADPOOL_3 = {"id": 533535, "title": "Deadpool & Wolverine", "release_date": "2024-07-24",
              "poster_path": "/dp3.jpg", "genre_ids": [28, 35, 878]}


def tmdb_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/movie/now_playing") or path.endswith("/trending/movie/week"):
        return httpx.Response(200, json={"results": [DUNE_2, TOY_STORY, DUNE_2]})
    if path.endswith("/search/movie"):
        return httpx.Response(200, json={"results": [DUNE_2, TOY_STORY]})
    if path.endswith("/movie/693134/recommendations"):
        return httpx.Response(200, json={"results": [DEADPOOL_3, DUNE_2, TOY_STORY]})
    if path.endswith("/movie/693134"):
        return httpx.Response(200, json={**DUNE_2, "genres": [{"id": 878, "name": "Science Fiction"}]})
    return httpx.Response(404)


@pytest.fixture
def live_tmdb(client):
    import main
    svc = main.tmdb_service
    saved = (svc.api_key, svc._client, dict(svc._ttl_cache), dict(svc.cache), svc.dirty)
    svc.api_key = "test-key"
    svc._client = httpx.AsyncClient(transport=httpx.MockTransport(tmdb_handler))
    svc._ttl_cache.clear()
    svc._save_cache = lambda: None          # never write the real cache file in tests
    yield svc
    svc.api_key, svc._client, ttl, cache, svc.dirty = saved
    svc._ttl_cache.clear(); svc._ttl_cache.update(ttl)
    svc.cache.clear(); svc.cache.update(cache)
    del svc._save_cache


def test_fresh_without_key(client):
    body = client.get("/api/v1/movies/fresh").json()
    assert body == {"results": [], "list": "now_playing", "tmdb_configured": False}
    assert client.get("/api/v1/movies/fresh?list=bogus").status_code == 422


def test_fresh_lists_new_movies(client, live_tmdb):
    res = client.get("/api/v1/movies/fresh?list=now_playing").json()["results"]
    assert [r["tmdbId"] for r in res] == [693134, 862], "deduplicated, order kept"
    dune = res[0]
    assert dune["movieId"] == "t693134" and dune["title"] == "Dune: Part Two (2024)"
    assert dune["releaseYear"] == 2024 and dune["genres"] == ["Sci-Fi", "Adventure"]
    assert dune["cached"]["poster_path"] == "/dune2.jpg" and "budget" not in dune["cached"]
    # A movie that exists in the catalog keeps its catalog id
    assert res[1]["movieId"] == 1 and res[1]["source"] == "catalog"


def test_search_includes_new_releases_first(client, live_tmdb):
    res = client.get("/api/v1/search/movies?q=dune&limit=10").json()["results"]
    assert res[0]["movieId"] == "t693134"
    assert any(r["title"] == "Dune (2021)" for r in res), "catalog matches are kept"
    assert sum(1 for r in res if r["tmdbId"] == 862) <= 1


def test_live_item_and_recommendations(client, live_tmdb):
    item = client.get("/api/v1/item/movies/t693134").json()["result"]
    assert item["title"] == "Dune: Part Two (2024)"
    recs = client.get("/api/v1/recommend/movies/t693134?limit=5").json()["recommendations"]
    assert [r["tmdbId"] for r in recs] == [533535, 862], "seed excluded"
    assert recs[0]["reasons"][0] == "Both Sci-Fi"


def test_live_ids_without_key_are_404(client):
    assert client.get("/api/v1/item/movies/t693134").status_code == 404
    assert client.get("/api/v1/recommend/movies/t693134").status_code == 404
    assert client.get("/api/v1/recommend/movies/tabc").status_code == 400
