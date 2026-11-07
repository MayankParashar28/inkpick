from modules.music_recommender import MusicEngine


class AudioService:
    """
    Audio Domain Service
    ====================
    Wraps the MusicEngine to provide a high-level service interface
    for audio discovery and recommendation.
    """
    def __init__(self, data_path: str = "processed/", model_path: str = "models/"):
        self.engine = MusicEngine(data_path=data_path, model_path=model_path)
        print("  📻 Audio Service initialized")

    @staticmethod
    def parse_id(item_id):
        return str(item_id)

    def search(self, query: str, limit: int = 12):
        return self.engine.search(query, limit=limit)

    def recommend(self, item_id: str, top_n: int = 12, genre: str = None, **_):
        return self.engine.recommend(item_id, top_n=top_n)

    def discover(self, limit: int = 24, offset: int = 0):
        return self.engine.discover(limit=limit, offset=offset)

    def random_pick(self):
        return self.engine.random_pick()

    def get_item(self, item_id):
        return self.engine.get_item(item_id)

    def mood(self, **kwargs):
        return self.engine.mood(**kwargs)

    def suggest(self, query: str, limit: int = 8):
        return self.engine.suggest(query, limit=limit)
