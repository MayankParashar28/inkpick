from modules.course_recommender import CourseEngine


class EduService:
    """
    Education Domain Service
    ========================
    Wraps the CourseEngine to provide academic content discovery
    for the Udemy + YouTube catalog.
    """
    def __init__(self, data_path: str = "processed/"):
        self.engine = CourseEngine(data_path=data_path)
        print("  🎓 Education Service initialized")

    @staticmethod
    def parse_id(item_id):
        # Course IDs are numeric in the CSVs; URL params arrive as strings
        return int(item_id)

    def search(self, query: str, limit: int = 12):
        return self.engine.search(query, limit=limit)

    def recommend(self, item_id, top_n: int = 12, genre: str = None, **_):
        return self.engine.recommend(item_id, top_n=top_n, genre=genre)

    def discover(self, limit: int = 24, offset: int = 0):
        return self.engine.discover(limit=limit, offset=offset)

    def random_pick(self):
        return self.engine.random_pick()

    def get_item(self, item_id):
        return self.engine.get_item(item_id)

    def suggest(self, query: str, limit: int = 8):
        return self.engine.suggest(query, limit=limit)
