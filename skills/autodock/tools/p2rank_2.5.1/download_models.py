#!/usr/bin/env python3
"""Download and extract P2Rank model files (excluded from git due to size > 50 MB).

The P2Rank 2.5.1 release distributes models as part of the full tar.gz archive.
This script downloads the archive, extracts only the model files, and places them
in the correct directory structure.

Usage:
    python download_models.py        # Download and extract all models
    python download_models.py --list # List available models
"""
import os
import sys
import argparse
import urllib.request
import tarfile
from pathlib import Path

RELEASE_URL = "https://github.com/rdk/p2rank/releases/download/2.5.1/p2rank_2.5.1.tar.gz"
MODEL_NAMES = [
    "default",
    "alphafold",
    "rescore_conservation",
    "rescore_2024",
    "conservation_hmm",
    "alphafold_conservation_hmm",
    "default_rescore",
]


def download_archive(url: str, dest: Path) -> None:
    """Download tar.gz archive with progress."""
    if dest.exists():
        print(f"  ✓ Archive already exists: {dest}")
        return

    print(f"  → Downloading {dest.name} ...", end=" ", flush=True)
    try:
        urllib.request.urlretrieve(url, str(dest))
        size_mb = dest.stat().st_size / (1024 * 1024)
        print(f"done ({size_mb:.1f} MB)")
    except Exception as e:
        print(f"FAILED: {e}")
        raise


def extract_models(archive: Path, models_dir: Path) -> None:
    """Extract model .zst files from tar.gz archive."""
    print(f"  → Extracting models to {models_dir} ...")
    models_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            # Match paths like: p2rank_2.5.1/models/default/model.zst
            parts = Path(member.name).parts
            if len(parts) >= 3 and parts[1] == "models" and parts[-1] == "model.zst":
                model_name = parts[2]
                if model_name in MODEL_NAMES:
                    dest_path = models_dir / model_name / "model.zst"
                    if dest_path.exists():
                        print(f"    ✓ {model_name}/model.zst already exists")
                        continue
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    member_file = tar.extractfile(member)
                    if member_file:
                        with open(dest_path, "wb") as f:
                            f.write(member_file.read())
                        size_mb = dest_path.stat().st_size / (1024 * 1024)
                        print(f"    ✓ {model_name}/model.zst ({size_mb:.1f} MB)")


def main():
    parser = argparse.ArgumentParser(description="Download P2Rank model files")
    parser.add_argument("--list", action="store_true", help="List available models")
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    models_dir = script_dir / "models"
    cache_dir = script_dir / ".download_cache"
    cache_dir.mkdir(exist_ok=True)
    archive_path = cache_dir / "p2rank_2.5.1.tar.gz"

    if args.list:
        print("Available P2Rank models:")
        for name in MODEL_NAMES:
            dest = models_dir / name / "model.zst"
            status = "✓ downloaded" if dest.exists() else "✗ missing"
            print(f"  {name:30s} {status}")
        return

    print("Downloading P2Rank models ...")
    print(f"Release: {RELEASE_URL}")
    print()

    download_archive(RELEASE_URL, archive_path)
    extract_models(archive_path, models_dir)

    print()
    print("All models ready.")
    print(f"Location: {models_dir}")


if __name__ == "__main__":
    main()
