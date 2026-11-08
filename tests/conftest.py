import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# Tests never call real external APIs
os.environ.pop("TMDB_API_KEY", None)
os.environ.pop("SPOTIFY_CLIENT_ID", None)
os.environ.pop("SPOTIFY_CLIENT_SECRET", None)
os.environ["ITUNES_FALLBACK"] = "0"


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    import main

    with TestClient(main.app) as c:   # runs the lifespan (loads all engines once)
        yield c


@pytest.fixture(scope="session")
def cinema(client):
    import main
    return main.app.state.cinema_service
