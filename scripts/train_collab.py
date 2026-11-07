"""
Train Inkpick's collaborative-filtering model.

Usage (from the repo root):
    pip install -r scripts/requirements-train.txt
    # any MovieLens ratings.csv works: ml-latest-small (100k), ml-32m (32M) ...
    python scripts/train_collab.py --ratings path/to/ratings.csv

Writes:
    models/collab_factors.npy    float32 [n_movies, k]  (L2-normalised)
    models/collab_movie_ids.npy  int32   [n_movies]

Method: user-mean-centred rating matrix -> truncated SVD -> item factors.
Cosine similarity between item factors = "people who liked X also liked Y".
"""
import argparse
import os
import time

import numpy as np
import pandas as pd


def build_matrix(ratings: pd.DataFrame):
    from scipy.sparse import csr_matrix

    users = pd.Categorical(ratings["userId"])
    movies = pd.Categorical(ratings["movieId"])
    # Centre each user's ratings so "liked" vs "disliked" is relative to their own scale
    centred = ratings["rating"] - ratings.groupby("userId")["rating"].transform("mean")
    X = csr_matrix(
        (centred.astype(np.float32).to_numpy(), (movies.codes, users.codes)),
        shape=(movies.categories.size, users.categories.size),
    )
    return X, np.asarray(movies.categories, dtype=np.int32)


def train(ratings_path: str, out_dir: str, k: int, min_ratings: int, catalog_path: str | None):
    t0 = time.time()
    print(f"⏳ Loading ratings from {ratings_path} ...")
    ratings = pd.read_csv(
        ratings_path, usecols=["userId", "movieId", "rating"],
        dtype={"userId": "int32", "movieId": "int32", "rating": "float32"},
    )

    if catalog_path and os.path.exists(catalog_path):
        known = set(pd.read_csv(catalog_path, usecols=["movieId"])["movieId"])
        ratings = ratings[ratings["movieId"].isin(known)]

    counts = ratings["movieId"].value_counts()
    ratings = ratings[ratings["movieId"].isin(counts[counts >= min_ratings].index)]
    print(f"   {len(ratings):,} ratings · {ratings['userId'].nunique():,} users · "
          f"{ratings['movieId'].nunique():,} movies (≥{min_ratings} ratings each)")

    X, movie_ids = build_matrix(ratings)
    k = max(2, min(k, min(X.shape) - 1))
    print(f"⚡ Truncated SVD (k={k}) on {X.shape[0]:,} × {X.shape[1]:,} ...")
    from sklearn.decomposition import TruncatedSVD
    factors = TruncatedSVD(n_components=k, algorithm="randomized", random_state=42).fit_transform(X)

    norms = np.linalg.norm(factors, axis=1, keepdims=True)
    factors = np.divide(factors, norms, out=np.zeros_like(factors), where=norms > 0).astype(np.float32)

    os.makedirs(out_dir, exist_ok=True)
    np.save(os.path.join(out_dir, "collab_factors.npy"), factors)
    np.save(os.path.join(out_dir, "collab_movie_ids.npy"), movie_ids)
    size_mb = factors.nbytes / 1e6
    print(f"✅ Saved {factors.shape} factors ({size_mb:.1f} MB) in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ratings", default="processed/ratings_filtered.csv", help="MovieLens ratings.csv")
    parser.add_argument("--out", default="models", help="output directory")
    parser.add_argument("--factors", type=int, default=64, help="latent dimensions")
    parser.add_argument("--min-ratings", type=int, default=5, help="drop movies with fewer ratings")
    parser.add_argument("--catalog", default="processed/movies_processed.csv",
                        help="limit to movies in the app catalog")
    a = parser.parse_args()
    train(a.ratings, a.out, a.factors, a.min_ratings, a.catalog)
