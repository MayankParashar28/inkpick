"""
Hybrid Recommendation Engine
=============================
Weighted blend of content-based and collaborative scores:

    score(i) = α · content(i) + (1 − α) · collab(i)

α defaults to 0.65 (content-biased). Movies the collaborative model has never
seen (cold start) fall back to content-only results.
"""
import os

DEFAULT_ALPHA = float(os.getenv("INKPICK_HYBRID_ALPHA", "0.65"))


class HybridEngine:
    """Blends content + collaborative recommendations."""

    def __init__(self, movie_engine, collab_engine, alpha: float = DEFAULT_ALPHA):
        self.content = movie_engine
        self.collab = collab_engine
        self.alpha = min(1.0, max(0.0, alpha))
        print(f"  🔀 Hybrid Engine ready (α={self.alpha:.2f})")

    def recommend(self, movie_id: int, top_n: int = 12, genre: str | None = None) -> list[dict]:
        pool = top_n * 3
        content_recs = self.content.recommend(movie_id, top_n=pool, genre=genre)

        # Popularity fallback is not personalised — only blend a trained model
        if not (self.collab.ready and self.collab.covers(movie_id)):
            for r in content_recs:
                r["mode"] = "hybrid"
            return content_recs[:top_n]

        collab_recs = self.collab.recommend(movie_id, top_n=pool, genre=genre)
        merged: dict[int, dict] = {}
        for r in content_recs:
            merged[r["movieId"]] = {**r, "_c": r.get("similarity") or 0.0, "_f": 0.0}
        for r in collab_recs:
            entry = merged.setdefault(r["movieId"], {**r, "_c": 0.0, "_f": 0.0, "reasons": []})
            entry["_f"] = r.get("similarity") or 0.0
            entry["reasons"] = (entry.get("reasons") or []) + r.get("reasons", [])

        blended = []
        for r in merged.values():
            r["similarity"] = round(self.alpha * r.pop("_c") + (1 - self.alpha) * r.pop("_f"), 4)
            r["mode"] = "hybrid"
            r["reasons"] = list(dict.fromkeys(r.get("reasons") or []))[:3]
            blended.append(r)
        blended.sort(key=lambda r: r["similarity"], reverse=True)
        return blended[:top_n]
