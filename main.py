#!/usr/bin/env python3
"""
Music Library Organizer for Plex
Organizes music files into Artist/Album/Track structure using macOS metadata.
"""

import os
import subprocess
import re
from pathlib import Path
import shutil

MUSIC_ROOT = Path("/Users/sebastianydemadsen/MyMusic")
SUPPORTED_EXTENSIONS = {".mp3", ".flac"}
IGNORE_DIRS = {".venv", "__pycache__", ".git"}


def get_metadata(file_path: Path) -> dict:
    """Get metadata using mdls with only the fields we need."""
    try:
        result = subprocess.run(
            ["mdls", "-name", "kMDItemAuthors", "-name", "kMDItemAlbum",
             "-name", "kMDItemTitle", "-name", "kMDItemAudioTrackNumber",
             str(file_path)],
            capture_output=True, text=True, timeout=5
        )

        data = {"artist": None, "album": None, "title": None, "track": None}
        lines = result.stdout.strip().split("\n")

        i = 0
        while i < len(lines):
            line = lines[i]

            if "kMDItemAuthors" in line:
                if "(null)" not in line and "(" in line:
                    # Multi-line array, get next line
                    if i + 1 < len(lines):
                        next_line = lines[i + 1].strip()
                        # Try quoted format first: "Artist Name"
                        match = re.search(r'"(.+)"', next_line)
                        if match:
                            data["artist"] = match.group(1)
                        else:
                            # Unquoted format (common in FLAC): just the name
                            # Remove trailing comma if present
                            artist = next_line.rstrip(',').strip()
                            if artist and artist != ")":
                                data["artist"] = artist
                        i += 1
            elif "kMDItemAlbum" in line:
                match = re.search(r'=\s*"(.+)"', line)
                if match:
                    data["album"] = match.group(1)
            elif "kMDItemTitle" in line:
                match = re.search(r'=\s*"(.+)"', line)
                if match:
                    data["title"] = match.group(1)
            elif "kMDItemAudioTrackNumber" in line:
                match = re.search(r'=\s*(\d+)', line)
                if match:
                    data["track"] = int(match.group(1))
            i += 1

        return data
    except Exception:
        return {"artist": None, "album": None, "title": None, "track": None}


def find_music_files() -> list[Path]:
    """Find all music files."""
    files = []
    for dirpath, dirnames, filenames in os.walk(MUSIC_ROOT):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for f in filenames:
            if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS:
                files.append(Path(dirpath) / f)
    return files


def decode_unicode_escapes(s: str) -> str:
    """Decode unicode escapes like \\U00f8 to actual characters (ø)."""
    # Handle \UXXXX format (4 hex digits) - mdls uses this format
    def replace_u(match):
        code = int(match.group(1), 16)
        return chr(code)

    # Replace \U followed by 4 hex digits
    s = re.sub(r'\\U([0-9a-fA-F]{4})', replace_u, s)
    # Also handle standard \uXXXX format just in case
    s = re.sub(r'\\u([0-9a-fA-F]{4})', replace_u, s)
    return s


def sanitize(name: str) -> str:
    """Clean filename - decode unicode escapes and remove unsafe characters."""
    # Decode unicode escapes like \U00f8 -> ø
    name = decode_unicode_escapes(name)

    # Only remove characters that are truly problematic for filesystems
    for c in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
        name = name.replace(c, '-' if c in '/\\:|' else '')
    return name.strip().strip('.')


def get_main_artist(artist: str) -> str:
    """Extract main artist, removing featuring artists."""
    # Split on common featuring patterns (case insensitive)
    # Patterns: ft., feat., feat, ft, &, featuring, with, x, ,
    patterns = [
        r'\s+ft\.?\s+',
        r'\s+feat\.?\s+',
        r'\s+featuring\s+',
        r'\s+with\s+',
        r'\s+x\s+',
        r'\s*&\s*',
        r'\s*,\s*',
    ]

    result = artist
    for pattern in patterns:
        parts = re.split(pattern, result, flags=re.IGNORECASE)
        if parts:
            result = parts[0]

    return result.strip()


def remove_empty_folders(root: Path):
    """Remove folders that have no music files (may contain .DS_Store, etc)."""
    removed = 0
    # Walk bottom-up so we can remove nested empty folders
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if dirpath == str(root):
            continue
        path = Path(dirpath)

        # Check if directory has any music files
        has_music = False
        for item in path.rglob('*'):
            if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS:
                has_music = True
                break

        if not has_music:
            # Delete all contents (DS_Store, cover art, etc) and the folder
            try:
                shutil.rmtree(path)
                removed += 1
            except OSError:
                pass
    return removed


def main():
    print("=" * 50)
    print("MUSIC LIBRARY ORGANIZER")
    print("=" * 50)

    print("\n[1/3] Finding music files...")
    files = find_music_files()
    print(f"      Found {len(files)} files")

    print("\n[2/3] Reading metadata...")
    moves = []
    skipped = 0

    for i, f in enumerate(files):
        if (i + 1) % 100 == 0:
            print(f"      {i + 1}/{len(files)}...")

        meta = get_metadata(f)

        # Skip if incomplete metadata
        if not (meta["artist"] and meta["album"] and meta["title"]):
            skipped += 1
            continue

        # Build target path (use main artist only, not featuring artists)
        main_artist = get_main_artist(meta["artist"])
        artist = sanitize(main_artist)
        album = sanitize(meta["album"])
        title = sanitize(meta["title"])
        ext = f.suffix

        if meta["track"]:
            filename = f"{meta['track']:02d} - {title}{ext}"
        else:
            filename = f"{title}{ext}"

        target = MUSIC_ROOT / artist / album / filename

        # Skip if same location or target exists
        if f == target or target.exists():
            continue

        moves.append((f, target))

    print(f"\n      ✓ {len(moves)} files to move")
    print(f"      ✗ {skipped} files skipped (incomplete metadata)")

    if not moves:
        print("\nNo files to move.")
    else:
        # Preview
        print("\n[3/3] Preview (first 15):")
        print("-" * 50)
        for src, dst in moves[:15]:
            print(f"\n  {src.relative_to(MUSIC_ROOT)}")
            print(f"  → {dst.relative_to(MUSIC_ROOT)}")

        if len(moves) > 15:
            print(f"\n  ... and {len(moves) - 15} more")

        print("\n" + "-" * 50)
        response = input(f"Move {len(moves)} files? (yes/no): ").strip().lower()

        if response == "yes":
            print("\nMoving...")
            for src, dst in moves:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
            print(f"✓ Moved {len(moves)} files.")
        else:
            print("Cancelled.")
            return

    print("\nCleaning up empty folders...")
    removed = remove_empty_folders(MUSIC_ROOT)
    print(f"✓ Removed {removed} empty folders.")
    print("\n✓ Done!")

if __name__ == "__main__":
    main()
