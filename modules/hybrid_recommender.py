"""
Hybrid Recommendation Engine
=============================
Blends content-based and collaborative results.
Falls back to content-only when the collaborative model is not trained.
"""


class HybridEngine:
    """Blends content + collaborative recommendations."""

    def __init__(self, movie_engine, collab_engine):
        self.content = movie_engine
        self.collab = collab_engine
        print("  🔀 Hybrid Engine ready")

    def recommend(self, movie_id: int, top_n: int = 12, genre: str | None = None) -> list[dict]:
        content_recs = self.content.recommend(movie_id, top_n=top_n, genre=genre)

        # The popularity fallback is not personalised — only blend a real model
        if not self.collab.ready:
            blended = content_recs
        else:
            collab_recs = self.collab.recommend(movie_id, top_n=top_n, genre=genre)
            seen, blended = set(), []
            for i in range(max(len(content_recs), len(collab_recs))):
                for source in (content_recs, collab_recs):
                    if i < len(source) and source[i]["movieId"] not in seen:
                        seen.add(source[i]["movieId"])
                        blended.append(source[i])

        for r in blended:
            r["mode"] = "hybrid"
        return blended[:top_n]
