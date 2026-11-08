from modules.movie_recommender import MovieEngine
from modules.collab_recommender import CollabEngine
from modules.hybrid_recommender import HybridEngine
from services.mapping import MappingService


class CinemaService:
    """
    Cinema Domain Service
    =====================
    Orchestrates movie discovery by integrating content-based,
    collaborative, and hybrid recommendation strategies.
    """
    def __init__(self, data_path: str = "processed/", model_path: str = "models/"):
        mapping_service = MappingService(data_path=data_path)
        self.movie_engine = MovieEngine(data_path=data_path, model_path=model_path, mapping_service=mapping_service)
        self.collab_engine = CollabEngine(movie_engine=self.movie_engine, model_path=model_path)
        self.hybrid_engine = HybridEngine(self.movie_engine, self.collab_engine)
        print("  🎬 Cinema Service initialized")

    @staticmethod
    def parse_id(item_id):
        return int(item_id)

    def search(self, query: str, limit: int = 12):
        return self.movie_engine.search(query, limit=limit)

    def recommend(self, movie_id: int, top_n: int = 12, mode: str = "hybrid", genre: str = None):
        if mode == "collaborative":
            return self.collab_engine.recommend(movie_id, top_n=top_n, genre=genre)
        if mode == "content":
            return self.movie_engine.recommend(movie_id, top_n=top_n, genre=genre)
        return self.hybrid_engine.recommend(movie_id, top_n=top_n, genre=genre)

    def discover(self, limit: int = 24, offset: int = 0):
        return self.movie_engine.discover(limit=limit, offset=offset)

    def random_pick(self):
        return self.movie_engine.random_pick()

    def get_item(self, item_id):
        return self.movie_engine.get_item(item_id)

    def suggest(self, query: str, limit: int = 8):
        return self.movie_engine.suggest(query, limit=limit)
