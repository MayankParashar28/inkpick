import ast
import difflib
import math
import re

import pandas as pd


def sanitize_query(q: str) -> str:
    """Strip unsafe characters, keeping letters (incl. unicode), digits, spaces, - ' ( ) & ."""
    if not q:
        return ""
    clean = re.sub(r"[^\w \-\'\(\)&\.]", "", q, flags=re.UNICODE)
    return re.sub(r"\s+", " ", clean).strip()


def parse_list_field(val):
    """Safely parse stringified Python lists from CSV back to real lists."""
    if isinstance(val, list):
        return val
    if not isinstance(val, str) or val in ("[]", "(no genres listed)"):
        return []
    try:
        parsed = ast.literal_eval(val)
        return parsed if isinstance(parsed, list) else []
    except (ValueError, SyntaxError):
        # Fallback for pipe-separated strings
        return [g.strip() for g in val.split("|") if g.strip()]


def safe_float(val, default=0.0, ndigits=None):
    """Convert to a JSON-safe float (NaN/inf become the default)."""
    try:
        f = float(val)
    except (TypeError, ValueError):
        return default
    if math.isnan(f) or math.isinf(f):
        return default
    return round(f, ndigits) if ndigits is not None else f


def safe_str(val, default=""):
    """Convert to str, mapping NaN/None to the default."""
    if val is None or (isinstance(val, float) and math.isnan(val)) or val is pd.NA:
        return default
    return str(val)


def format_movie_response(row, score=None, mode="content"):
    """Standardizes the movie dictionary format used across all engines."""
    year = row.get("release_year")
    return {
        "movieId": int(row["movieId"]),
        "title": row["title"],
        "genres": parse_list_field(row.get("genres")),
        "releaseYear": int(year) if pd.notna(year) else None,
        "tmdbId": int(row.get("tmdbId", -1)),
        "imdbId": int(row.get("imdbId", -1)),
        "similarity": score,
        "mode": mode,
    }


def get_fuzzy_suggestion(query: str, choices: list, threshold: float = 0.6) -> str | None:
    """Find the best fuzzy match for a query among a list of choices."""
    matches = difflib.get_close_matches(query, choices, n=1, cutoff=threshold)
    return matches[0] if matches else None


def build_row_map(indptr, num_rows):
    """Map each non-zero CSR element to its row index (vectorized)."""
    import numpy as np
    return np.repeat(np.arange(num_rows, dtype=np.int32), np.diff(indptr[: num_rows + 1]))


def sparse_row_scores(data, indices, row_map, indptr, idx, num_rows, num_cols=None):
    """
    Dot product of CSR row `idx` against every row of the matrix.
    Fully vectorized: scatter the query row into a dense vector and gather.
    Returns None if the row is empty.
    """
    import numpy as np
    start, end = indptr[idx], indptr[idx + 1]
    if start >= end:
        return None
    q_idx = indices[start:end]
    if num_cols is None:
        num_cols = int(indices.max()) + 1
    query = np.zeros(num_cols, dtype=np.float32)
    query[q_idx] = data[start:end]
    contributions = data * query[indices]
    return np.bincount(row_map, weights=contributions, minlength=num_rows)


def top_n_indices(scores, top_n, exclude_idx):
    """Return indices of the top-N scores (descending), excluding one index and zero scores."""
    import numpy as np
    k = min(top_n + 1, len(scores))
    if k <= 0:
        return []
    part = np.argpartition(scores, -k)[-k:]
    ordered = part[np.argsort(scores[part])[::-1]]
    return [int(i) for i in ordered if i != exclude_idx and scores[i] > 0][:top_n]
