#!/usr/bin/env python3
"""Extract inline base64 images from Markdown files into separate files.

Reads a Markdown file, finds all ![alt](data:image/...;base64,...) references,
decodes the base64 data, saves images to __assets/, and replaces inline
references with relative file paths.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import re
import shutil
import sys
from pathlib import Path

MIME_TO_EXT = {
    "png": ".png",
    "jpeg": ".jpg",
    "jpg": ".jpg",
    "gif": ".gif",
    "svg+xml": ".svg",
    "webp": ".webp",
}

# Match ![alt](data:image/MIME;base64,BASE64DATA)
# \r included for Windows CRLF line endings in base64 data
PATTERN = re.compile(
    r"!\[([^\]]*)\]\(data:image/(png|jpeg|jpg|gif|svg\+xml|webp);base64,([A-Za-z0-9+/=\r\n]+)\)"
)


def extract_images_from_md(
    md_path: Path,
    output_dir: Path | None = None,
    *,
    dry_run: bool = False,
    no_backup: bool = False,
    verbose: bool = False,
) -> list[dict]:
    """Extract base64 images from a Markdown file.

    Returns a list of dicts describing each extraction:
        {"match": original_text, "alt": alt_text, "filename": output_filename,
         "size": byte_count, "dedup": bool}
    """
    try:
        text = md_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        print(f"Error reading {md_path}: {e}", file=sys.stderr)
        return []

    stem = md_path.stem

    if output_dir is None:
        output_dir = md_path.parent / "__assets" / stem
    hash_to_filename: dict[str, str] = {}
    results: list[dict] = []
    seq = 0

    def replace_match(m: re.Match) -> str:
        nonlocal seq
        alt = m.group(1)
        mime = m.group(2)
        b64_data = m.group(3).replace("\r", "").replace("\n", "").replace(" ", "")

        if not b64_data.strip():
            print(f"  Warning: empty base64 data in {md_path.name}, skipping", file=sys.stderr)
            return m.group(0)

        try:
            img_bytes = base64.b64decode(b64_data)
        except Exception as e:
            print(f"  Warning: invalid base64 in {md_path.name}: {e}", file=sys.stderr)
            return m.group(0)

        content_hash = hashlib.sha256(img_bytes).hexdigest()

        # Dedup: reuse if same content already extracted
        if content_hash in hash_to_filename:
            filename = hash_to_filename[content_hash]
            results.append({
                "match": m.group(0),
                "alt": alt,
                "filename": filename,
                "size": len(img_bytes),
                "dedup": True,
            })
            return f"![{alt}](__assets/{stem}/{filename})"

        ext = MIME_TO_EXT.get(mime, ".bin")
        seq += 1
        filename = f"{seq:03d}{ext}"

        if not dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / filename).write_bytes(img_bytes)

        hash_to_filename[content_hash] = filename
        results.append({
            "match": m.group(0),
            "alt": alt,
            "filename": filename,
            "size": len(img_bytes),
            "dedup": False,
        })
        return f"![{alt}](__assets/{stem}/{filename})"

    new_text = PATTERN.sub(replace_match, text)

    if not dry_run and results:
        # Backup original (unless --no-backup)
        if not no_backup:
            backup = md_path.with_suffix(md_path.suffix + ".bak")
            shutil.copy2(md_path, backup)
        md_path.write_text(new_text, encoding="utf-8")

    return results


def process_path(
    path: Path,
    output_dir: Path | None,
    *,
    dry_run: bool,
    recursive: bool,
    no_backup: bool,
    verbose: bool,
) -> int:
    """Process a single file or directory. Returns count of images extracted."""
    if path.is_dir():
        if not recursive:
            # Process top-level .md files only
            md_files = sorted(path.glob("*.md"))
        else:
            md_files = sorted(path.rglob("*.md"))
        if not md_files:
            print(f"No .md files found in {path}")
            return 0
        total = 0
        for md_file in md_files:
            total += process_path(
                md_file, output_dir,
                dry_run=dry_run, recursive=recursive,
                no_backup=no_backup, verbose=verbose,
            )
        return total

    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        return 0

    if verbose or dry_run:
        mode = "[DRY-RUN] " if dry_run else ""
        print(f"{mode}Processing: {path}")

    results = extract_images_from_md(
        path, output_dir,
        dry_run=dry_run, no_backup=no_backup, verbose=verbose,
    )

    if not results:
        if verbose:
            print(f"  No base64 images found in {path.name}")
        return 0

    for r in results:
        tag = " (dedup)" if r["dedup"] else ""
        print(f"  {'[DRY-RUN] ' if dry_run else ''}{r['filename']} ({r['size']} bytes){tag}")

    return len(results)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="从 Markdown 文件中提取内嵌 base64 图片为独立文件",
    )
    parser.add_argument(
        "paths", nargs="+", type=Path,
        help="MD files or directories to process",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="Custom output directory (default: __assets/ next to each MD)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would change without writing",
    )
    parser.add_argument(
        "--no-backup", action="store_true",
        help="Don't create .bak files",
    )
    parser.add_argument(
        "-r", "--recursive", action="store_true",
        help="Process directories recursively",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show detailed output",
    )
    args = parser.parse_args(argv)

    total = 0
    for p in args.paths:
        total += process_path(
            p, args.output_dir,
            dry_run=args.dry_run, recursive=args.recursive,
            no_backup=args.no_backup, verbose=args.verbose,
        )

    if total == 0:
        print("No base64 images found.")
    elif args.dry_run:
        print(f"\nDry-run complete. Would extract {total} image(s).")
    else:
        print(f"\nDone. Extracted {total} image(s).")


if __name__ == "__main__":
    main()
