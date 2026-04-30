#!/usr/bin/env python3
"""
Box Office Jedi — Consolidate per-film data into letter-sharded JSON
======================================================================
Cloudflare Pages caps each deployment at 20,000 files. Our per-film data
directories blew past that:

    data/movies/          ~14,800 files (TMDB cache — redundant w/ meta)
    data/movies_meta/     ~15,100 files (one per slug)
    data/movie_weekends/  ~19,900 files (one per slug + legacy aliases)

This one-shot script consolidates them into 26 letter-sharded JSON files
each (one shard per first letter of the slug, plus an `index.json`):

    data/movies_meta_shards/{a..z}.json     ─ {slug: meta_obj, ...}
    data/movie_weekends_shards/{a..z}.json  ─ {slug: weekend_obj, ...}

It also deletes the deprecated per-film files (so the deployment shrinks)
and removes data/movies/ entirely (the relevant fields are mirrored in
data/movies_meta/* anyway). The TMDB enricher will be updated to write
directly to the shards going forward.

Run:
    python3 scripts/consolidate_movie_data.py            # consolidate + delete
    python3 scripts/consolidate_movie_data.py --dry-run  # report only
    python3 scripts/consolidate_movie_data.py --keep-originals
                                                          # consolidate but
                                                          # don't delete the
                                                          # per-file folders
"""
import argparse
import glob
import json
import os
import re
import shutil
from datetime import datetime


DATA_DIR = "data"


def shard_letter(key: str) -> str:
    """Return the shard letter for a slug. Anything not [a-z] goes to '_'."""
    if not key:
        return "_"
    c = key[0].lower()
    if "a" <= c <= "z":
        return c
    return "_"


def consolidate_dir(src_dir: str, out_dir: str, dry_run: bool = False) -> dict:
    """Walk src_dir for *.json files (skip index.json) and write letter-sharded
    consolidations to out_dir. Returns counts."""
    files = sorted(p for p in glob.glob(os.path.join(src_dir, "*.json"))
                   if os.path.basename(p) != "index.json")
    if not files:
        print(f"  (no files in {src_dir})")
        return {"input": 0, "shards": 0}

    shards: dict[str, dict] = {}    # letter → {slug: data}
    for path in files:
        slug = os.path.basename(path).replace(".json", "")
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception as e:
            print(f"  ⚠ skip {path}: {e}")
            continue
        letter = shard_letter(slug)
        shards.setdefault(letter, {})[slug] = data

    if dry_run:
        for letter, entries in sorted(shards.items()):
            print(f"  would write {out_dir}/{letter}.json with {len(entries)} entries")
        return {"input": len(files), "shards": len(shards)}

    os.makedirs(out_dir, exist_ok=True)
    for letter, entries in shards.items():
        path = os.path.join(out_dir, f"{letter}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "updated": datetime.now().isoformat(timespec="seconds"),
                "letter":  letter,
                "count":   len(entries),
                "entries": entries,
            }, f, ensure_ascii=False)
    # Tiny index file so the front-end can verify which shards exist
    with open(os.path.join(out_dir, "index.json"), "w", encoding="utf-8") as f:
        json.dump({
            "updated": datetime.now().isoformat(timespec="seconds"),
            "letters": sorted(shards.keys()),
            "total":   sum(len(v) for v in shards.values()),
        }, f, ensure_ascii=False)
    print(f"  wrote {len(shards)} shard files to {out_dir}/  "
          f"(total {sum(len(v) for v in shards.values())} entries)")
    return {"input": len(files), "shards": len(shards)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Don't write or delete anything; just report.")
    ap.add_argument("--keep-originals", action="store_true",
                    help="Consolidate but keep the per-file source folders "
                         "(useful for testing — does NOT shrink deployment).")
    args = ap.parse_args()

    print("Consolidating data/movies_meta/ → data/movies_meta_shards/")
    meta_stats = consolidate_dir(
        os.path.join(DATA_DIR, "movies_meta"),
        os.path.join(DATA_DIR, "movies_meta_shards"),
        dry_run=args.dry_run,
    )

    print()
    print("Consolidating data/movie_weekends/ → data/movie_weekends_shards/")
    wkn_stats = consolidate_dir(
        os.path.join(DATA_DIR, "movie_weekends"),
        os.path.join(DATA_DIR, "movie_weekends_shards"),
        dry_run=args.dry_run,
    )

    if args.dry_run:
        print()
        print("(dry run — no files removed or written)")
        return

    if not args.keep_originals:
        # Delete the per-file source directories. Cloudflare Pages can now
        # deploy without bumping into the 20k-file cap.
        for path in (
            os.path.join(DATA_DIR, "movies_meta"),
            os.path.join(DATA_DIR, "movie_weekends"),
            os.path.join(DATA_DIR, "movies"),    # redundant TMDB cache
        ):
            if os.path.isdir(path):
                count = len(glob.glob(os.path.join(path, "*.json")))
                shutil.rmtree(path)
                print(f"  removed {path}/  ({count} files freed)")

    print()
    print("Done.")
    print(f"  movies_meta:     {meta_stats['input']} files → {meta_stats['shards']} shards")
    print(f"  movie_weekends:  {wkn_stats['input']} files → {wkn_stats['shards']} shards")


if __name__ == "__main__":
    main()
