import asyncio

import httpx
import numpy as np
import pandas as pd
import pytest

from modules import utils
from modules.collab_recommender import CollabEngine
from modules.hybrid_recommender import HybridEngine
from services.tmdb import TMDBService, slim


# ── utils ──────────────────────────────────────────────
def test_sanitize_query():
    assert utils.sanitize_query("  <b>Toy   Story</b>!! ") == "bToy Storyb"
    assert utils.sanitize_query("Ocean's Eleven (2001)") == "Ocean's Eleven (2001)"
    assert utils.sanitize_query("Amélie") == "Amélie"
    assert utils.sanitize_query("") == ""


def test_parse_list_field():
    assert utils.parse_list_field("['Action', 'Drama']") == ["Action", "Drama"]
    assert utils.parse_list_field("Action|Drama") == ["Action", "Drama"]
    assert utils.parse_list_field("(no genres listed)") == []
    assert utils.parse_list_field(float("nan")) == []


def test_safe_float():
    assert utils.safe_float(float("nan")) == 0.0
    assert utils.safe_float("x", default=None) is None
    assert utils.safe_float(1.234, ndigits=1) == 1.2


def test_sparse_scores_match_dense():
    rng = np.random.default_rng(1)
    dense = (rng.random((30, 12)) * (rng.random((30, 12)) > 0.6)).astype(np.float32)
    indptr = np.concatenate([[0], np.cumsum((dense != 0).sum(axis=1))])
    indices = np.concatenate([np.flatnonzero(r) for r in dense]).astype(np.int32)
    data = dense[dense != 0]
    row_map = utils.build_row_map(indptr, 30)
    for idx in range(30):
        got = utils.sparse_row_scores(data, indices, row_map, indptr, idx, 30, 12)
        if got is None:
            assert not dense[idx].any()
            continue
        np.testing.assert_allclose(got, dense @ dense[idx], rtol=1e-5)


def test_top_n_excludes_seed_and_zeros():
    scores = np.array([0.9, 0.5, 0.0, 0.7, 0.0])
    assert utils.top_n_indices(scores, 3, exclude_idx=0) == [3, 1]
    assert utils.top_n_indices(np.array([]), 3, exclude_idx=0) == []


# ── TMDB service (mocked HTTP) ─────────────────────────
def _service(tmp_path, handler):
    svc = TMDBService(cache_file=str(tmp_path / "cache.json"))
    svc.api_key = "test-key"
    svc._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return svc


def test_trailer_prefers_official_youtube_trailer(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"results": [
            {"site": "Vimeo", "key": "v1", "type": "Trailer", "official": True},
            {"site": "YouTube", "key": "teaser", "type": "Teaser", "official": True},
            {"site": "YouTube", "key": "fan", "type": "Trailer", "official": False},
            {"site": "YouTube", "key": "best", "type": "Trailer", "official": True, "name": "Official Trailer"},
        ]})

    svc = _service(tmp_path, handler)
    trailer = asyncio.run(svc.get_trailer(862))
    assert trailer == {"key": "best", "name": "Official Trailer", "site": "YouTube"}
    asyncio.run(svc.get_trailer(862))
    assert len(calls) == 1, "trailer lookups must be cached"


def test_trailer_none_when_no_videos(tmp_path):
    svc = _service(tmp_path, lambda r: httpx.Response(200, json={"results": []}))
    assert asyncio.run(svc.get_trailer(1)) is None


def test_movie_details_404_is_cached_stub(tmp_path):
    svc = _service(tmp_path, lambda r: httpx.Response(404))
    data = asyncio.run(svc.get_movie_details(123))
    assert data["title"] == "Unknown" and "123" in svc.cache


def test_movie_details_without_key_never_raises(tmp_path):
    svc = TMDBService(cache_file=str(tmp_path / "c.json"))
    svc.api_key = None
    assert asyncio.run(svc.get_movie_details(5))["id"] == 5


def test_slim_keeps_only_frontend_fields():
    out = slim({"id": 1, "title": "T", "poster_path": "/p.jpg", "budget": 1, "genres": [{"id": 1, "name": "Drama"}]})
    assert out == {"id": 1, "title": "T", "poster_path": "/p.jpg", "genres": ["Drama"]}


# ── Collaborative + hybrid ─────────────────────────────
ANIMATION = [1, 2355, 3114, 6377, 4886, 8961]
HORROR = [1214, 1258, 1387, 2710, 1997, 1350]


@pytest.fixture(scope="module")
def trained_model(tmp_path_factory):
    """Train on synthetic ratings with two clear taste groups."""
    from scripts.train_collab import train

    rng = np.random.default_rng(0)
    rows = []
    for u in range(300):
        fav, other = (ANIMATION, HORROR) if u % 2 == 0 else (HORROR, ANIMATION)
        rows += [(u, m, rng.uniform(4, 5)) for m in fav]
        rows += [(u, int(m), rng.uniform(1, 2)) for m in rng.choice(other, 3, replace=False)]
    d = tmp_path_factory.mktemp("collab")
    pd.DataFrame(rows, columns=["userId", "movieId", "rating"]).to_csv(d / "ratings.csv", index=False)
    train(str(d / "ratings.csv"), str(d), k=8, min_ratings=1, catalog_path=None)
    return str(d) + "/"


def test_collab_learns_taste_groups(cinema, trained_model):
    engine = CollabEngine(cinema.movie_engine, model_path=trained_model)
    assert engine.ready and engine.covers(1)
    recs = engine.recommend(1, top_n=4)
    assert recs and all(r["movieId"] in ANIMATION for r in recs)
    assert all(r["mode"] == "collaborative" for r in recs)


def test_collab_fallback_without_model(cinema, tmp_path):
    engine = CollabEngine(cinema.movie_engine, model_path=str(tmp_path))
    assert not engine.ready
    recs = engine.recommend(318, top_n=5)
    assert len(recs) == 5 and all(r["movieId"] != 318 for r in recs)


def test_hybrid_blends_both_signals(cinema, trained_model):
    collab = CollabEngine(cinema.movie_engine, model_path=trained_model)
    hybrid = HybridEngine(cinema.movie_engine, collab, alpha=0.5)
    recs = hybrid.recommend(1, top_n=6)
    assert recs and all(r["mode"] == "hybrid" for r in recs)
    sims = [r["similarity"] for r in recs]
    assert sims == sorted(sims, reverse=True)
    assert any(any("Fans of" in why for why in r["reasons"]) for r in recs)


def test_hybrid_cold_start_uses_content(cinema, trained_model):
    collab = CollabEngine(cinema.movie_engine, model_path=trained_model)
    assert not collab.covers(2)  # Jumanji is not in the synthetic model
    recs = HybridEngine(cinema.movie_engine, collab).recommend(2, top_n=4)
    content = cinema.movie_engine.recommend(2, top_n=4)
    assert [r["movieId"] for r in recs] == [r["movieId"] for r in content]
