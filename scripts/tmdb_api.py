"""
Box Office Jedi — TMDB API Integration
========================================
Fetches movie data from The Movie Database (TMDB) free API.
Used for: All-Time charts, individual Movie Pages (poster, budget, revenue, overview).

SETUP REQUIRED:
  1. Go to https://www.themoviedb.org/signup and create a free account
  2. Go to https://www.themoviedb.org/settings/api and request an API key (free, instant)
  3. Set your key as an environment variable:
       export TMDB_API_KEY="your_key_here"
     Or paste it directly into the TMDB_API_KEY variable below (not recommended for public repos).

Output files:
  data/alltime.json       — Top 100 all-time domestic grossers (revenue data)
  data/movies/<id>.json   — Individual movie detail pages
"""

import requests
import json
import os
import time
from datetime import datetime

# ── Configuration ─────────────────────────────────────────────────────────────

# Get API key from environment variable (recommended) or paste directly
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "YOUR_API_KEY_HERE")
TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

# ── Helpers ───────────────────────────────────────────────────────────────────

def tmdb_get(endpoint: str, params: dict = None) -> dict | None:
    """Make a TMDB API request and return JSON response."""
    if TMDB_API_KEY == "YOUR_API_KEY_HERE":
        print("ERROR: No TMDB API key set. See setup instructions at top of this file.")
        return None

    url = f"{TMDB_BASE}{endpoint}"
    all_params = {"api_key": TMDB_API_KEY, "language": "en-US"}
    if params:
        all_params.update(params)

    try:
        time.sleep(0.3)  # Respect rate limits (40 req/10s on free tier)
        resp = requests.get(url, params=all_params, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 401:
            print("ERROR: Invalid TMDB API key.")
        elif resp.status_code == 429:
            print("Rate limited — waiting 10s...")
            time.sleep(10)
            return tmdb_get(endpoint, params)
        else:
            print(f"HTTP {resp.status_code} for {endpoint}")
    except requests.RequestException as e:
        print(f"Request failed: {e}")
    return None


def poster_url(path: str, size: str = "w342") -> str:
    """Build a full TMDB poster image URL."""
    if not path:
        return ""
    return f"{TMDB_IMAGE_BASE}/{size}{path}"


def save_json(filename: str, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  ✓ Saved {path}")


# ── All-Time Chart ────────────────────────────────────────────────────────────

def fetch_alltime_chart(pages: int = 5) -> list[dict]:
    """
    Build an all-time chart by fetching TMDB's highest revenue movies.
    TMDB lets you sort /discover/movie by revenue — this gives us a solid top list.
    pages=5 gives roughly 100 movies (20 per page).
    """
    print(f"\n[All-Time] Fetching top movies by revenue ({pages} pages)...")
    all_movies = []

    for page in range(1, pages + 1):
        data = tmdb_get("/discover/movie", {
            "sort_by": "revenue.desc",
            "page": page,
            "vote_count.gte": 100,  # Filter out obscure entries with no votes
        })
        if not data or "results" not in data:
            break

        for m in data["results"]:
            all_movies.append({
                "rank":            len(all_movies) + 1,
                "tmdb_id":         m["id"],
                "title":           m["title"],
                "release_date":    m.get("release_date", ""),
                "revenue":         m.get("revenue", 0),
                "poster_url":      poster_url(m.get("poster_path")),
                "overview":        m.get("overview", ""),
                "vote_average":    m.get("vote_average", 0),
            })
        print(f"  Page {page}: +{len(data['results'])} movies")

    # Re-rank after full sort
    all_movies.sort(key=lambda x: x["revenue"], reverse=True)
    for i, m in enumerate(all_movies):
        m["rank"] = i + 1

    print(f"  Total: {len(all_movies)} movies")
    return all_movies


# ── Individual Movie Pages ────────────────────────────────────────────────────

def fetch_movie_detail(tmdb_id: int) -> dict | None:
    """
    Fetch full details for a single movie — for individual movie pages.
    Includes: budget, revenue, runtime, genres, cast, trailer, weekly earnings.
    """
    print(f"  Fetching movie {tmdb_id}...")

    # Main details
    detail = tmdb_get(f"/movie/{tmdb_id}", {"append_to_response": "credits,videos,release_dates"})
    if not detail:
        return None

    # Extract trailer (YouTube)
    trailer_key = None
    if "videos" in detail and detail["videos"].get("results"):
        for v in detail["videos"]["results"]:
            if v["site"] == "YouTube" and v["type"] == "Trailer":
                trailer_key = v["key"]
                break

    # Extract top cast (first 10)
    cast = []
    if "credits" in detail:
        for member in detail["credits"].get("cast", [])[:10]:
            cast.append({
                "name":       member["name"],
                "character":  member.get("character", ""),
                "profile":    poster_url(member.get("profile_path"), size="w185"),
            })

    # Extract director
    director = ""
    if "credits" in detail:
        for member in detail["credits"].get("crew", []):
            if member["job"] == "Director":
                director = member["name"]
                break

    return {
        "tmdb_id":       detail["id"],
        "title":         detail["title"],
        "tagline":       detail.get("tagline", ""),
        "overview":      detail.get("overview", ""),
        "release_date":  detail.get("release_date", ""),
        "runtime":       detail.get("runtime", 0),
        "budget":        detail.get("budget", 0),
        "revenue":       detail.get("revenue", 0),
        "genres":        [g["name"] for g in detail.get("genres", [])],
        "poster_url":    poster_url(detail.get("poster_path"), size="w342"),
        "backdrop_url":  poster_url(detail.get("backdrop_path"), size="w1280"),
        "director":      director,
        "cast":          cast,
        "trailer_key":   trailer_key,
        "imdb_id":       detail.get("imdb_id", ""),
        "vote_average":  detail.get("vote_average", 0),
        "vote_count":    detail.get("vote_count", 0),
    }


def fetch_now_playing() -> list[dict]:
    """
    Fetch currently playing movies — useful for populating Derby Game dropdown.
    Returns movies currently in wide release.
    """
    print("\n[Now Playing] Fetching current wide releases...")
    movies = []

    for page in range(1, 3):  # 2 pages = ~40 movies, plenty for Derby
        data = tmdb_get("/movie/now_playing", {"page": page, "region": "US"})
        if not data or "results" not in data:
            break
        for m in data["results"]:
            movies.append({
                "tmdb_id":      m["id"],
                "title":        m["title"],
                "release_date": m.get("release_date", ""),
                "poster_url":   poster_url(m.get("poster_path")),
            })

    # Sort alphabetically for Derby dropdown
    movies.sort(key=lambda x: x["title"])
    print(f"  Found {len(movies)} now-playing movies")
    return movies


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    now = datetime.now()
    print(f"Box Office Jedi TMDB Sync — {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if TMDB_API_KEY == "YOUR_API_KEY_HERE":
        print("\n⚠️  No API key found!")
        print("Get your free key at: https://www.themoviedb.org/settings/api")
        print("Then run: export TMDB_API_KEY='your_key' && python3 tmdb_api.py")
        return

    # All-time chart
    alltime = fetch_alltime_chart(pages=5)
    save_json("alltime.json", {
        "updated": now.isoformat(),
        "note": "Revenue data from TMDB — represents worldwide gross. Use for relative ranking.",
        "chart": alltime
    })

    # Movie detail pages for each all-time entry
    print("\n[Movie Pages] Fetching details for top 100...")
    os.makedirs(os.path.join(DATA_DIR, "movies"), exist_ok=True)
    for movie in alltime[:100]:
        detail = fetch_movie_detail(movie["tmdb_id"])
        if detail:
            save_json(f"movies/{movie['tmdb_id']}.json", detail)

    # Now-playing (for Derby dropdowns)
    now_playing = fetch_now_playing()
    save_json("now_playing.json", {
        "updated": now.isoformat(),
        "movies": now_playing
    })

    print("\n" + "=" * 60)
    print("TMDB sync complete!")


if __name__ == "__main__":
    main()
