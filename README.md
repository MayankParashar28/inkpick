<div align="center">

<h1> Inkpick</h1>

<p><strong>High-Performance Multi-Domain Content Discovery & Recommendation Engine</strong></p>

<p>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/FastAPI-Async-009688?style=flat-square&logo=fastapi&logoColor=white"/>
  <img src="https://img.shields.io/badge/NumPy-CSR%20Inference-013243?style=flat-square&logo=numpy&logoColor=white"/>
  <img src="https://img.shields.io/badge/Frontend-Vanilla%20ES6%2B-F7DF1E?style=flat-square&logo=javascript&logoColor=black"/>
  <img src="https://img.shields.io/badge/Deploy-Render%20%7C%20Railway%20%7C%20Heroku-430098?style=flat-square"/>
</p>

<p>
  <a href="#architecture">Architecture</a> •
  <a href="#recommendation-methodology">Methodology</a> •
  <a href="#api-reference">API</a> •
  <a href="#installation">Installation</a> •
  <a href="#deployment">Deployment</a>
</p>

</div>

---

## Overview

Inkpick is a multi-domain content discovery platform delivering sub-50ms recommendation inference across cinema, audio, and educational catalogs exceeding 80,000 items. The system is engineered around a custom sparse-matrix recommendation core — bypassing heavy ML framework overhead in favor of native NumPy vectorized operations — achieving a memory and latency profile suited for production deployment on constrained infrastructure.

**Supported Domains**
| Domain | Dataset | Items |
|--------|---------|-------|
| Cinema | MovieLens | ~80,000+ |
| Audio | Custom Metadata | — |
| Education | Udemy Catalog | — |

**Highlights**
- ✨ **More like this** on every item, with a plain-English *“Why this pick?”* (shared genres, same era/franchise, same artist, similar tempo/energy, shared course topics)
- 📒 **My Sketchbook**: tap ♡ to save movies, songs and courses (kept in your browser)
- 🔗 **Shareable links**: every item has its own URL, e.g. `/#/movies/1`, `/#/songs/<spotifyId>`
- 🎧 **New songs every week** from Spotify, or free from Apple's charts (no key), with ▶ 30-second previews
- 🎨 **Real album covers** for songs via Spotify's public oEmbed (no API key; the first ~1,200 ship pre-cached in `models/song_covers.json`)
- 🎚️ **Mood mixer**: find songs by energy, danceability and tempo, or pick Chill / Focus / Workout / Party
- 🆕 **New releases, live from TMDB**: the MovieLens catalog ends in 2023, so Trending / Now Playing / Upcoming, a "New in cinemas" row and search for newer films come straight from TMDB (needs `TMDB_API_KEY`)
- 🎲 **Surprise me**: a random pick from the current category
- 🔎 **Live search suggestions** as you type (arrow keys + Enter)
- 💡 **Because you saved…**: a personal row built from your latest save
- 🎞️ **Trailers** play inline in the movie view (with `TMDB_API_KEY`)
- 🖍️ **Chalkboard dark mode**: follows your system, or toggle it
- 🤖 **Sketchy**: a lit, animated 3D robot mascot, lazy-loaded so it never slows the page

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                        Client Layer                      │
│         Vanilla JS (ES6+) · WebGL Mascot · CSS3          │
└──────────────────────────┬──────────────────────────────┘
                           │  HTTP / REST
┌──────────────────────────▼──────────────────────────────┐
│                     FastAPI (Async)                      │
│             Endpoint Management · ASGI / Uvicorn         │
└──────┬──────────────┬───────────────┬───────────────────┘
       │              │               │
┌──────▼──────┐ ┌─────▼──────┐ ┌─────▼──────────────────┐
│  Content-   │ │Collaborative│ │    Fuzzy Search         │
│  Based      │ │  Filtering  │ │  Levenshtein Engine     │
│  (TF-IDF +  │ │(Latent      │ │                         │
│  CSR Dot)   │ │ Factor)     │ │                         │
└──────┬──────┘ └─────┬──────┘ └─────────────────────────┘
       └──────┬────────┘
       ┌──────▼──────────────────────────────────────────┐
       │          Hybrid Interleaving Layer               │
       │       Weighted Blending · Cold-Start Mitigation  │
       └──────────────────┬──────────────────────────────┘
                          │
       ┌──────────────────▼──────────────────────────────┐
       │         Service Registry (Modular Domains)       │
       │    cinema_service · audio_service · edu_service  │
       └─────────────────────────────────────────────────┘
```

### Backend

| Component | Technology | Purpose |
|-----------|------------|---------|
| Web Framework | FastAPI (async) | High-throughput API endpoint management |
| Inference Core | NumPy CSR (custom) | Dependency-light sparse dot-product similarity |
| Data Pipeline | Pandas (vectorized) | Metadata ingestion, cleansing, and augmentation |
| Service Layer | Registry pattern | Modular, domain-decoupled recommendation services |
| Server | Uvicorn (ASGI) | Production-grade async request handling |

> **Design Decision — Custom CSR over SciPy:** The recommendation engine implements Compressed Sparse Row matrix operations directly in NumPy rather than delegating to SciPy. This eliminates a ~30MB transitive dependency, reduces cold-start memory allocation, and gives direct control over the dot-product similarity pipeline critical to inference latency.

### Frontend

| Component | Technology | Purpose |
|-----------|------------|---------|
| Runtime | Vanilla JS (ES6+) | Zero-framework, minimal parse/exec overhead |
| Styling | CSS3 Variables | Newsprint/Tactile design system, high-density grids |
| 3D Mascot | WebGL / Model-Viewer | Interactive feedback during navigation |
| Bundle | None (no bundler) | Maximum rendering speed, instant first paint |

---

## Recommendation Methodology

### 1. Content-Based Filtering

Item profiles are constructed using **TF-IDF (Term Frequency–Inverse Document Frequency)** vectorization over item metadata (title, genre, tags, description). At inference time, a manually implemented **sparse dot-product similarity** algorithm computes cosine distances across the full catalog using NumPy CSR arrays.

```
similarity(q, i) = (q · i) / (‖q‖ · ‖i‖)
```

- **Inference latency:** < 50ms on catalogs of 80,000+ items
- **Cold-start behavior:** Fully functional — no user history required

### 2. Collaborative Filtering

A **latent factor model** ("people who liked X also liked Y"): user-mean-centred MovieLens ratings are factorised with truncated SVD, and movies are compared by the cosine similarity of their factors.

Train it once from any MovieLens `ratings.csv` ([ml-latest-small](https://files.grouplens.org/datasets/movielens/ml-latest-small.zip) for a quick start, ml-32m for the full model):

```bash
pip install -r scripts/requirements-train.txt
python scripts/train_collab.py --ratings path/to/ratings.csv
```

This writes `models/collab_factors.npy` and `models/collab_movie_ids.npy` (plain NumPy, no pickle). The app picks them up on its next start; `GET /api/v1/health` shows `"collaborative_model": true`. Until then a popularity fallback is used and hybrid mode is content-only.

### 3. Hybrid Interleaving

A weighted blend merges the content-based and collaborative scores. Movies the collaborative model has never seen (cold start) automatically fall back to content-only results.

```
score_hybrid(i) = α · score_cb(i) + (1 - α) · score_cf(i)
```

Where `α ∈ [0, 1]` is set by `INKPICK_HYBRID_ALPHA` (default `0.65`, content-biased).

### 4. Fuzzy Search Fallback

When metadata queries yield no direct matches, a **Levenshtein edit-distance** engine generates corrected query candidates ranked by similarity score. This ensures graceful degradation for misspelled or ambiguous inputs.

---

## Project Structure

```
inpick/
├── main.py                  # ASGI entrypoint, FastAPI app factory
├── services/
│   ├── registry.py          # Domain service registry
│   ├── cinema_service.py    # MovieLens recommendation logic
│   ├── audio_service.py     # Audio domain handler
│   └── edu_service.py       # Udemy/education domain handler
├── core/
│   ├── tfidf.py             # TF-IDF vectorizer implementation
│   ├── csr_ops.py           # Custom NumPy CSR dot-product engine
│   ├── collaborative.py     # Latent factor model stub
│   ├── hybrid.py            # Weighted interleaving layer
│   └── fuzzy.py             # Levenshtein search fallback
├── data/
│   └── pipelines/           # Pandas ingestion & augmentation pipelines
├── static/
│   ├── index.html           # Single-page app shell
│   ├── app.js               # ES6+ frontend logic
│   ├── style.css            # CSS3 variable-driven design system
│   └── assets/              # WebGL mascot model & static assets
├── requirements.txt
├── Procfile                 # WSGI/ASGI process definition
└── wsgi.py                  # Production WSGI adapter
```

---

## Installation

### Prerequisites

- Python **3.10+**
- `pip` or [`uv`](https://github.com/astral-sh/uv) (recommended)

### Quickstart

```bash
# 1. Clone the repository
git clone https://github.com/MayankParashar28/inpick.git
cd inpick

# 2. (Recommended) Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
# or, using uv:
uv pip install -r requirements.txt

# 4. Start the development server
uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.  
Interactive docs (Swagger UI) at `http://localhost:8000/docs`.

---

## API Reference

All endpoints live under `/api/v1`. `{domain}` is one of `movies`, `songs`, `courses`.
`limit` is clamped to `1–50`. Movies that exist only on TMDB (newer than the catalog) use ids like `t693134`; they work with `/item`, `/recommend` and shareable links.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/discover/{domain}?limit=24&offset=0` | Paginated home-page feed |
| `GET` | `/search/{domain}?q=...&limit=24` | Title/artist/instructor search (genre names work for movies) with fuzzy "did you mean" fallback |
| `GET` | `/recommend/{domain}/{item_id}?limit=12&genre=...` | Similar items for one catalog item |
| `GET` | `/movies/recommend/{movie_id}?mode=hybrid&genre=...` | Movie recs with `content`, `collaborative` or `hybrid` mode |
| `GET` | `/surprise/{domain}` | 🎲 One random pick |
| `GET` | `/item/{domain}/{item_id}` | One item by ID (powers shareable links) |
| `GET` | `/songs/mood?energy=0.8&danceability=0.7&tempo=128` | 🎚️ Songs closest to a target mood (all params optional) |
| `GET` | `/suggest/{domain}?q=toy` | 🔎 Instant type-ahead titles (prefix matches first) |
| `POST` | `/songs/covers` | `{"ids": ["<spotifyId>", …]}` → album cover URLs for up to 50 tracks |
| `GET` | `/songs/fresh` | 🆕 New songs: Spotify new releases, or Apple's top-songs chart (no key) — `source` says which |
| `GET` | `/movies/fresh?list=trending` | 🆕 Live movies: `trending`, `now_playing`, `upcoming`, `popular` |
| `GET` | `/movies/{tmdb_id}/trailer` | 🎞️ Best official YouTube trailer (`null` without `TMDB_API_KEY`) |
| `GET` | `/tmdb/movie/{tmdb_id}` | Cached TMDB metadata proxy (hides the API key) |
| `POST` | `/tmdb/batch` | `{"ids": [862, 8844]}` → metadata for up to 50 movies |
| `GET` | `/health` | Status, active categories, TMDB cache size |

**Example**
```bash
curl "http://localhost:8000/api/v1/recommend/movies/1?limit=3"
```

```json
{
  "category": "movies",
  "recommendations": [
    {
      "movieId": 3114, "title": "Toy Story 2 (1999)", "tmdbId": 863, "similarity": 0.98,
      "genres": ["Adventure", "Animation", "Children", "Comedy", "Fantasy"],
      "reasons": ["Both Adventure + Animation + Children", "Same franchise", "Same era (1990s)"]
    }
  ]
}
```

---

## Deployment

The project ships with a `Procfile` and `wsgi.py` for one-command deployment to any WSGI/ASGI-compatible platform.

### Render / Railway / Heroku

```
# Procfile (already configured)
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```

Simply connect the repository to your platform of choice — no additional configuration required.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TMDB_API_KEY` | — | **Recommended.** Posters, overviews and trailers for all ~87k movies. Without it only the ~3,100 cached titles have posters and trailers fall back to a YouTube search. Free key: [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | — | Live new-release songs, Spotify search and "more by this artist" (song dataset ends in 2023). From [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard). ⚠️ Spotify only serves Web API requests when the **app owner's account has Premium**; otherwise `/api/v1/health` shows the reason in `spotify_error`. |
| `SPOTIFY_MARKET` | `IN` | Country used for Spotify search and new releases (also the iTunes chart country) |
| `ITUNES_FALLBACK` | `1` | Free fallback for new songs when Spotify isn't available: Apple's top-songs chart + iTunes search, with 30-second previews. `0` disables it |
| `INKPICK_HYBRID_ALPHA` | `0.65` | Content weight in hybrid blending (1 = content only) |
| `INTERNAL_SECRET_TOKEN` | — | Protects `POST /api/v1/metadata/cache` |
| `PORT` | `8000` | Server bind port (auto-set by most platforms) |

Copy `.env.example` to `.env` for local development.

**On Vercel:** Project → Settings → Environment Variables → add `TMDB_API_KEY` (Production and Preview) → redeploy. Check it worked with `GET /api/v1/health` → `"tmdb_configured": true`.

---

## Performance

| Metric | Value |
|--------|-------|
| P99 inference latency | < 50ms |
| Catalog size (tested) | 80,000+ items |
| Memory footprint (inference) | Reduced vs. SciPy baseline |
| Cold-start support |  Full (content-based fallback) |

---

## Roadmap

- [x] Trained matrix factorization model (truncated SVD) replacing CF stub
- [ ] Redis-backed inference cache for repeat queries
- [ ] Streaming SSE endpoint for real-time recommendation updates
- [ ] User session tracking for implicit feedback loop
- [ ] Docker Compose setup for local multi-service development

---

## Contributing

Pull requests are welcome. For significant changes, please open an issue first to discuss the proposed modification.

```bash
# Run with auto-reload for development
uvicorn main:app --reload --log-level debug

# Run the test suite (also runs in GitHub Actions on every push / PR)
pip install -r requirements-dev.txt
python -m pytest -q
```

---

## License

Distributed under the MIT License. See `LICENSE` for details.

---

<div align="center">
  <sub>Built by <a href="https://github.com/MayankParashar28">Mayank Parashar</a> · SRMIST Ghaziabad</sub>
</div>
