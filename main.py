import concurrent.futures
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from modules.inkpick_registry import InkpickRegistry
from modules.utils import sanitize_query
from services.audio_service import AudioService
from services.cinema_service import CinemaService
from services.edu_service import EduService
from services.live_movies import LiveMovies, parse_live_id
from services.tmdb import TMDBService, slim

load_dotenv()

DATA_PATH = "processed/"
MODEL_PATH = "models/"
MAX_LIMIT = 50


# ── API Models ──────────────────────────────────────────────────
class CacheUpdate(BaseModel):
    tmdbId: int
    data: Dict[str, Any]


class BatchRequest(BaseModel):
    ids: List[int] = Field(default_factory=list, max_length=MAX_LIMIT)


# ── Services ────────────────────────────────────────────────────
registry = InkpickRegistry()
tmdb_service = TMDBService()


def load_services(data_path: str, model_path: str):
    """Load and initialize domain services in parallel."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        f_cinema = executor.submit(CinemaService, data_path=data_path, model_path=model_path)
        f_audio = executor.submit(AudioService, data_path=data_path, model_path=model_path)
        f_edu = executor.submit(EduService, data_path=data_path)
        return f_cinema.result(), f_audio.result(), f_edu.result()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Initializing Inkpick Engines...")
    started = time.perf_counter()
    cinema, audio, edu = load_services(DATA_PATH, MODEL_PATH)

    app.state.cinema_service = cinema
    app.state.live_movies = LiveMovies(tmdb_service, cinema.movie_engine)
    registry.register("movies", cinema)
    registry.register("songs", audio)
    registry.register("courses", edu)
    app.state.started_at = time.time()
    print(f"✅ Engines ready in {time.perf_counter() - started:.1f}s")

    if not tmdb_service.api_key:
        print("  ⚠️  TMDB_API_KEY is missing — using cached metadata / stubs only.")
    else:
        # Warm the TMDB cache to reduce cold-start latency
        warmup_count = 6 if os.getenv("VERCEL") == "1" else 12
        try:
            await tmdb_service.enrich(cinema.discover(limit=warmup_count))
            print(f"🔥 TMDB cache warmed ({warmup_count} titles).")
        except Exception as e:
            print(f"⚠️ Cache warmup skipped: {e}")

    yield
    await tmdb_service.close()


app = FastAPI(
    title="Inkpick Discovery API",
    version="2.2.0",
    description="Hybrid Recommendation Engine for Movies, Songs and Courses.",
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.middleware("http")
async def cache_headers(request: Request, call_next):
    """Let browsers cache static assets and short-lived API reads."""
    response = await call_next(request)
    path = request.url.path
    if response.status_code == 200 and "cache-control" not in response.headers:
        if path.startswith(("/static/vendor/", "/static/assets/")):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif path.startswith("/static/"):
            # index.html revalidates; css/js are versioned via ?v=
            response.headers["Cache-Control"] = (
                "no-cache" if path.endswith(".html") else "public, max-age=86400"
            )
        elif path.startswith(("/api/v1/discover/", "/api/v1/recommend/", "/api/v1/search/",
                              "/api/v1/item/", "/api/v1/tmdb/movie/", "/api/v1/songs/mood",
                              "/api/v1/suggest/", "/api/v1/movies/fresh")):
            response.headers["Cache-Control"] = "public, max-age=300"
    return response

app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Helpers ─────────────────────────────────────────────────────
def get_engine_or_404(domain: str):
    engine = registry.get_engine(domain)
    if not engine:
        raise HTTPException(status_code=404, detail=f"Category '{domain}' is not active.")
    return engine


def parse_item_id(engine, domain: str, item_id: str):
    try:
        return engine.parse_id(item_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid ID for {domain}: '{item_id}'")


async def maybe_enrich(domain: str, items: list) -> list:
    return await tmdb_service.enrich(items) if domain == "movies" else items


# ── Routes ──────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def read_root():
    return RedirectResponse(url="/static/index.html")


@app.get("/api/v1/health")
async def health():
    """Liveness + readiness info."""
    return {
        "status": "ok",
        "categories": registry.list_categories(),
        "tmdb_configured": bool(tmdb_service.api_key),
        "tmdb_cached_titles": len(tmdb_service.cache),
        "collaborative_model": bool(
            getattr(app.state, "cinema_service", None) and app.state.cinema_service.collab_engine.ready
        ),
        "uptime_s": round(time.time() - getattr(app.state, "started_at", time.time()), 1),
    }


@app.get("/api/v1/categories")
async def list_categories():
    return {"categories": registry.list_categories()}


@app.get("/api/v1/tmdb/movie/{tmdb_id}")
async def get_tmdb_movie(tmdb_id: int):
    """Proxy request to TMDB to hide the API key and cache metadata."""
    return slim(await tmdb_service.get_movie_details(tmdb_id))


@app.post("/api/v1/tmdb/batch")
async def batch_tmdb(payload: BatchRequest):
    """Batch fetch TMDB details for up to 50 movies at once."""
    if not payload.ids:
        return {"results": {}}
    batch = await tmdb_service.batch_get_movie_details(payload.ids)
    return {"results": {k: slim(v) for k, v in batch.items()}}


@app.get("/api/v1/search/{domain}")
async def universal_search(
    domain: str,
    q: str = Query(..., min_length=2, max_length=100),
    limit: int = Query(24, ge=1, le=MAX_LIMIT),
):
    """Unified search endpoint."""
    engine = get_engine_or_404(domain)
    q = sanitize_query(q)
    if len(q) < 2:
        return {"results": [], "suggestion": None}
    results, suggestion = engine.search(q, limit=limit)
    if domain == "movies":
        # Catalog ends mid-2023: blend in newer titles from TMDB search
        results = await app.state.live_movies.search(q, results, limit)
        if results:
            suggestion = None
    return {"results": await maybe_enrich(domain, results), "suggestion": suggestion}


@app.get("/api/v1/suggest/{domain}")
async def suggest(
    domain: str,
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(8, ge=1, le=15),
):
    """Type-ahead suggestions (titles only, no TMDB enrichment — must be instant)."""
    engine = get_engine_or_404(domain)
    q = sanitize_query(q)
    if len(q) < 2:
        return {"results": []}
    return {"results": engine.suggest(q, limit=limit)}


@app.get("/api/v1/movies/fresh")
async def fresh_movies(
    kind: str = Query("now_playing", alias="list", pattern="^(trending|now_playing|upcoming|popular)$"),
    page: int = Query(1, ge=1, le=20),
):
    """🆕 Live new releases from TMDB (the MovieLens catalog ends in 2023)."""
    live = app.state.live_movies
    return {"results": await live.fresh(kind, page), "list": kind, "tmdb_configured": live.enabled}


@app.get("/api/v1/movies/{tmdb_id}/trailer")
async def movie_trailer(tmdb_id: int):
    """🎞️ Best YouTube trailer for a movie (needs TMDB_API_KEY)."""
    trailer = await tmdb_service.get_trailer(tmdb_id)
    return {"trailer": trailer, "tmdb_configured": bool(tmdb_service.api_key)}


@app.get("/api/v1/movies/search")
async def search_movies(q: str = Query(..., min_length=2, max_length=100)):
    """Legacy endpoint — delegates to universal search."""
    return await universal_search("movies", q, 24)


@app.get("/api/v1/songs/search")
async def search_songs(q: str = Query(..., min_length=2, max_length=100)):
    """Legacy endpoint — delegates to universal search."""
    return await universal_search("songs", q, 24)


@app.get("/api/v1/courses/search")
async def search_courses(q: str = Query(..., min_length=2, max_length=100)):
    """Legacy endpoint — delegates to universal search."""
    return await universal_search("courses", q, 24)


@app.get("/api/v1/movies/recommend/{movie_id}")
async def recommend_movies(
    movie_id: int,
    mode: str = Query("hybrid", pattern="^(content|collaborative|hybrid)$"),
    genre: Optional[str] = None,
    limit: int = Query(12, ge=1, le=MAX_LIMIT),
):
    """Generate recommendations for a specific movieId."""
    recs = app.state.cinema_service.recommend(movie_id, top_n=limit, mode=mode, genre=genre)
    if not recs:
        raise HTTPException(status_code=404, detail="No recommendations found.")
    return {"recommendations": await tmdb_service.enrich(recs), "mode": mode, "genre": genre}


@app.get("/api/v1/recommend/{content_type}/{item_id}")
async def universal_recommend(
    content_type: str,
    item_id: str,
    limit: int = Query(12, ge=1, le=MAX_LIMIT),
    genre: Optional[str] = None,
):
    """Unified recommendation endpoint for Movies, Songs and Courses."""
    engine = get_engine_or_404(content_type)
    parsed_id = parse_item_id(engine, content_type, item_id)
    live_id = parse_live_id(parsed_id) if content_type == "movies" else None
    if live_id is not None:
        recs = await app.state.live_movies.recommend(live_id, top_n=limit)
        if not recs:
            raise HTTPException(status_code=404, detail="Item not found.")
        return {"recommendations": recs, "category": content_type}
    recs = engine.recommend(parsed_id, top_n=limit, genre=genre)
    if not recs:
        raise HTTPException(status_code=404, detail="Item not found.")
    return {"recommendations": await maybe_enrich(content_type, recs), "category": content_type}


@app.get("/api/v1/discover/{content_type}")
async def discover_content(
    content_type: str,
    limit: int = Query(24, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    """Serve a page of content for the home page."""
    engine = get_engine_or_404(content_type)
    results = engine.discover(limit=limit, offset=offset)
    return {"results": await maybe_enrich(content_type, results)}


@app.get("/api/v1/item/{content_type}/{item_id}")
async def get_item(content_type: str, item_id: str):
    """Look up a single item (used for shareable deep links)."""
    engine = get_engine_or_404(content_type)
    parsed_id = parse_item_id(engine, content_type, item_id)
    live_id = parse_live_id(parsed_id) if content_type == "movies" else None
    item = await app.state.live_movies.get_item(live_id) if live_id is not None else engine.get_item(parsed_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")
    enriched = await maybe_enrich(content_type, [item])
    return {"result": enriched[0]}


@app.get("/api/v1/songs/mood")
async def song_mood(
    energy: Optional[float] = Query(None, ge=0, le=1),
    danceability: Optional[float] = Query(None, ge=0, le=1),
    tempo: Optional[float] = Query(None, ge=40, le=220),
    limit: int = Query(24, ge=1, le=MAX_LIMIT),
):
    """🎚️ Mood mixer: songs closest to a target energy / danceability / tempo."""
    audio = get_engine_or_404("songs")
    return {"results": audio.mood(energy=energy, danceability=danceability, tempo=tempo, limit=limit)}


@app.get("/api/v1/surprise/{content_type}")
async def surprise_me(content_type: str):
    """✨ New: return one random pick from a category."""
    engine = get_engine_or_404(content_type)
    pick = engine.random_pick()
    if not pick:
        raise HTTPException(status_code=404, detail="Nothing to pick from.")
    enriched = await maybe_enrich(content_type, [pick])
    return {"result": enriched[0]}


@app.post("/api/v1/metadata/cache", include_in_schema=False)
async def update_metadata_cache(payload: CacheUpdate, x_internal_secret: Optional[str] = Header(None)):
    """Internal endpoint to update metadata cache. Protected by secret token."""
    secret = os.getenv("INTERNAL_SECRET_TOKEN")
    if not secret or x_internal_secret != secret:
        raise HTTPException(status_code=403, detail="Unauthorized internal request.")
    tmdb_service.update_cache(payload.tmdbId, payload.data)
    return {"status": "Cached"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
