import os
import random

import numpy as np
import pandas as pd

from modules.utils import get_fuzzy_suggestion, safe_float, safe_str


class CourseEngine:
    """The 'Learning Scribbles' discovery engine."""

    def __init__(self, data_path: str = "processed/"):
        print("  📚 Loading Learning Scribbles (Multi-Platform Merge)...")
        dfs = [
            pd.read_csv(path)
            for path in (os.path.join(data_path, "courses_processed.csv"),
                         os.path.join(data_path, "youtube_courses.csv"))
            if os.path.exists(path)
        ]

        if dfs:
            self.df = pd.concat(dfs, ignore_index=True).drop_duplicates("courseId")
            self.df = self.df.reset_index(drop=True)
            for col in ("title", "instructor", "platform", "category", "url"):
                self.df[col] = self.df[col].fillna("")
            self.df["rating"] = pd.to_numeric(self.df["rating"], errors="coerce").fillna(0.0)
            self.df["title_norm"] = self.df["title"].str.lower().str.strip()
            self.df["instructor_norm"] = self.df["instructor"].str.lower().str.strip()
            self.df["platform_norm"] = self.df["platform"].str.lower().str.strip()
            self.df["category_norm"] = self.df["category"].str.lower().str.strip()
            self.df["title_words"] = self.df["title_norm"].str.split().apply(set)
            self.id_to_idx = {int(c): i for i, c in enumerate(self.df["courseId"])}
            self._fuzzy_choices = self.df["title"].tolist() + self.df["instructor"].unique().tolist()
        else:
            print("  ❌ No course metadata found.")
            self.df = pd.DataFrame()
            self.id_to_idx = {}
            self._fuzzy_choices = []

        print(f"  ✅ Learning Engine ready — {len(self.df):,} courses (Udemy + YouTube).")

    def search(self, query: str, limit: int = 15) -> tuple[list[dict], str | None]:
        """Search courses by title, instructor, platform or category."""
        if self.df.empty:
            return [], None
        q = query.lower().strip()
        mask = (
            self.df["title_norm"].str.contains(q, na=False, regex=False)
            | self.df["instructor_norm"].str.contains(q, na=False, regex=False)
            | self.df["platform_norm"].str.contains(q, na=False, regex=False)
            | (self.df["category_norm"] == q)
        )
        hits = self.df[mask].sort_values("rating", ascending=False).head(limit)
        results = [self._format(row) for row in hits.to_dict("records")]
        suggestion = None if results else get_fuzzy_suggestion(query, self._fuzzy_choices)
        return results, suggestion

    def recommend(self, course_id: int, top_n: int = 12, genre: str | None = None) -> list[dict]:
        """Keyword-overlap recommendations within the same category/platform."""
        if self.df.empty:
            return []
        idx = self.id_to_idx.get(int(course_id))
        if idx is None:
            return []

        target = self.df.iloc[idx]
        target_words = target["title_words"]

        if genre:
            mask = self.df["category_norm"] == genre.lower()
        else:
            mask = (self.df["category"] == target["category"]) | (self.df["platform"] == target["platform"])
        candidates = self.df[mask & (self.df["courseId"] != target["courseId"])]
        if candidates.empty:
            return self.discover(limit=top_n)

        overlap = candidates["title_words"].apply(lambda w: len(target_words & w))
        order = np.lexsort((-candidates["rating"].to_numpy(), -overlap.to_numpy()))[:top_n]
        picked = candidates.iloc[order]
        max_overlap = max(len(target_words), 1)
        stop = {"with", "from", "course", "complete", "ultimate", "beginner", "beginners", "advanced",
                "learn", "guide", "masterclass", "bootcamp", "your", "build", "full", "basics", "scratch",
                "novice", "professional", "introduction", "tutorial", "training", "class"}
        results = []
        for row, ov in zip(picked.to_dict("records"), overlap.iloc[order]):
            reasons = []
            if row["category"] == target["category"]:
                reasons.append(f"Also {row['category']}")
            if row["platform"] == target["platform"]:
                reasons.append(f"On {row['platform']}")
            words = sorted(
                (w for w in target_words & row["title_words"] if w.isalpha() and len(w) >= 4 and w not in stop),
                key=len, reverse=True,
            )[:2]
            if words:
                reasons.append("Covers " + ", ".join(words))
            results.append({
                **self._format(row),
                "similarity": round(min(0.98, 0.5 + 0.5 * ov / max_overlap), 4),
                "reasons": reasons or ["Popular with learners"],
            })
        return results

    def get_item(self, course_id) -> dict | None:
        idx = self.id_to_idx.get(int(course_id))
        return None if idx is None else self._format(self.df.iloc[idx].to_dict())

    def suggest(self, query: str, limit: int = 8) -> list[dict]:
        """Fast type-ahead: titles starting with the query first, then containing it."""
        if self.df.empty:
            return []
        q = query.lower().strip()
        col = self.df["title_norm"]
        starts = self.df[col.str.startswith(q, na=False)]
        if len(starts) < limit:
            contains = self.df[col.str.contains(q, na=False, regex=False) & ~col.str.startswith(q, na=False)]
            starts = pd.concat([starts, contains.head(limit - len(starts))])
        return [self._format(row) for row in starts.head(limit).to_dict("records")]

    def discover(self, limit: int = 24, offset: int = 0) -> list[dict]:
        if self.df.empty:
            return []
        return [self._format(row) for row in self.df.iloc[offset: offset + limit].to_dict("records")]

    def random_pick(self) -> dict | None:
        if self.df.empty:
            return None
        return self._format(self.df.iloc[random.randrange(len(self.df))].to_dict())

    @staticmethod
    def _format(course: dict) -> dict:
        """Map course metadata to the shared card format."""
        return {
            "movieId": int(course["courseId"]),
            "title": safe_str(course.get("title")),
            "artist": safe_str(course.get("instructor")),   # instructor
            "album": safe_str(course.get("platform")),      # platform
            "releaseYear": safe_str(course.get("category")),
            "rating": safe_float(course.get("rating"), ndigits=1),
            "tmdbId": -2,                                    # course marker
            "url": safe_str(course.get("url")),
            "category": safe_str(course.get("category")),
        }
