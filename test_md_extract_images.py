"""Tests for md_extract_images module.

Uses unittest (stdlib) with tempfile for isolated test runs.
Covers: happy path, dedup, CRLF, empty data, non-UTF-8, special alt text,
filename collision, dry-run, no-backup, output-dir, recursive, CLI args.
"""

from __future__ import annotations

import base64
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from md_extract_images import (
    PATTERN,
    extract_images_from_md,
    main,
    process_path,
)

# Minimal 1x1 transparent PNG (67 bytes)
MINI_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVQI12NgAAIABQABNjN9GQAAAABJRUEFTkSuQmCC"
MINI_PNG_BYTES = base64.b64decode(MINI_PNG_B64)

# Minimal 1x1 red pixel GIF (35 bytes)
MINI_GIF_B64 = "R0lGODlhAQABAPAAAP8AAP///yH5BAAAAAAALAAAAAABAAEAAAIBRAA7"
MINI_GIF_BYTES = base64.b64decode(MINI_GIF_B64)


class TestRegexPattern(unittest.TestCase):
    """Test the regex pattern directly."""

    def test_match_png(self):
        m = PATTERN.search(f"![alt](data:image/png;base64,{MINI_PNG_B64})")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(2), "png")

    def test_match_jpeg(self):
        m = PATTERN.search(f"![alt](data:image/jpeg;base64,{MINI_PNG_B64})")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(2), "jpeg")

    def test_match_gif(self):
        m = PATTERN.search(f"![alt](data:image/gif;base64,{MINI_GIF_B64})")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(2), "gif")

    def test_match_svg(self):
        svg_b64 = base64.b64encode(b"<svg></svg>").decode()
        m = PATTERN.search(f"![alt](data:image/svg+xml;base64,{svg_b64})")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(2), "svg+xml")

    def test_match_webp(self):
        m = PATTERN.search(f"![alt](data:image/webp;base64,{MINI_PNG_B64})")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(2), "webp")

    def test_match_crlf(self):
        """Windows CRLF line endings in base64 data."""
        b64_with_crlf = MINI_PNG_B64[:20] + "\r\n" + MINI_PNG_B64[20:]
        m = PATTERN.search(f"![alt](data:image/png;base64,{b64_with_crlf})")
        self.assertIsNotNone(m)

    def test_match_lf(self):
        """LF line endings in base64 data."""
        b64_with_lf = MINI_PNG_B64[:20] + "\n" + MINI_PNG_B64[20:]
        m = PATTERN.search(f"![alt](data:image/png;base64,{b64_with_lf})")
        self.assertIsNotNone(m)

    def test_no_match_html_img(self):
        """Should NOT match HTML <img> tags."""
        html = f'<img src="data:image/png;base64,{MINI_PNG_B64}">'
        m = PATTERN.search(html)
        self.assertIsNone(m)

    def test_preserve_alt_text_special_chars(self):
        """Alt text with special characters preserved."""
        m = PATTERN.search(f"![a & b <c>](data:image/png;base64,{MINI_PNG_B64})")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "a & b <c>")


class TestExtractImages(unittest.TestCase):
    """Test extract_images_from_md with real files."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.tmpdir_p = Path(self.tmpdir)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_md(self, name: str, content: str) -> Path:
        p = self.tmpdir_p / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_happy_path_one_image(self):
        """Extract one image from a Markdown file."""
        md = self._write_md("test.md", f"# Title\n\n![img](data:image/png;base64,{MINI_PNG_B64})\n")
        results = extract_images_from_md(md)

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["dedup"])
        self.assertTrue(results[0]["filename"].endswith(".png"))
        self.assertEqual(results[0]["size"], len(MINI_PNG_BYTES))

        # Check image file exists in __assets/test/ subdirectory
        assets_dir = self.tmpdir_p / "__assets" / "test"
        img_file = assets_dir / results[0]["filename"]
        self.assertTrue(img_file.exists())
        self.assertEqual(img_file.read_bytes(), MINI_PNG_BYTES)

        # Check MD reference replaced
        new_text = md.read_text(encoding="utf-8")
        self.assertIn("__assets/", new_text)
        self.assertNotIn("base64,", new_text)

        # Check backup
        self.assertTrue(md.with_suffix(".md.bak").exists())

    def test_multiple_images(self):
        """Extract multiple images from one file."""
        content = (
            f"![a](data:image/png;base64,{MINI_PNG_B64})\n"
            f"![b](data:image/gif;base64,{MINI_GIF_B64})\n"
        )
        md = self._write_md("report.md", content)
        results = extract_images_from_md(md)

        self.assertEqual(len(results), 2)
        filenames = [r["filename"] for r in results]
        self.assertTrue(filenames[0].startswith("001"))
        self.assertTrue(filenames[1].startswith("002"))

    def test_dedup_same_image(self):
        """Same image appearing twice should produce one file."""
        content = (
            f"![a](data:image/png;base64,{MINI_PNG_B64})\n"
            f"![b](data:image/png;base64,{MINI_PNG_B64})\n"
        )
        md = self._write_md("test.md", content)
        results = extract_images_from_md(md)

        self.assertEqual(len(results), 2)
        self.assertTrue(results[0]["dedup"] is False)
        self.assertTrue(results[1]["dedup"] is True)
        # Same filename reused
        self.assertEqual(results[0]["filename"], results[1]["filename"])

        # Only one image file on disk
        assets_dir = self.tmpdir_p / "__assets" / "test"
        self.assertEqual(len(list(assets_dir.iterdir())), 1)

    def test_different_mime_types(self):
        """Each MIME type maps to correct extension."""
        for mime, ext in [("png", ".png"), ("jpeg", ".jpg"), ("gif", ".gif"), ("webp", ".webp")]:
            with self.subTest(mime=mime):
                md = self._write_md(
                    f"t_{mime}.md",
                    f"![x](data:image/{mime};base64,{MINI_PNG_B64})",
                )
                results = extract_images_from_md(md)
                self.assertEqual(len(results), 1)
                self.assertTrue(results[0]["filename"].endswith(ext))

    def test_crlf_in_base64(self):
        """Base64 data with CRLF line breaks is correctly decoded."""
        b64_with_crlf = MINI_PNG_B64[:20] + "\r\n" + MINI_PNG_B64[20:]
        md = self._write_md("test.md", f"![img](data:image/png;base64,{b64_with_crlf})")
        results = extract_images_from_md(md)

        self.assertEqual(len(results), 1)
        assets_dir = self.tmpdir_p / "__assets" / "test"
        img_file = assets_dir / results[0]["filename"]
        self.assertEqual(img_file.read_bytes(), MINI_PNG_BYTES)

    def test_empty_base64_skipped(self):
        """Empty base64 data should be skipped with warning."""
        md = self._write_md("test.md", "![alt](data:image/png;base64,)\n")
        results = extract_images_from_md(md)
        self.assertEqual(len(results), 0)

    def test_non_utf8_file_skipped(self):
        """Non-UTF-8 file should be skipped with error."""
        md = self.tmpdir_p / "bad.md"
        md.write_bytes(b"\xff\xfe Invalid UTF-8 \x80 content")
        results = extract_images_from_md(md)
        self.assertEqual(len(results), 0)

    def test_dry_run_no_files_written(self):
        """Dry-run should not write any files."""
        md = self._write_md("test.md", f"![img](data:image/png;base64,{MINI_PNG_B64})")
        results = extract_images_from_md(md, dry_run=True)

        self.assertEqual(len(results), 1)
        # No assets dir created
        self.assertFalse((self.tmpdir_p / "__assets").exists())
        # No backup
        self.assertFalse(md.with_suffix(".md.bak").exists())
        # Original unchanged
        self.assertIn("base64,", md.read_text())

    def test_no_backup(self):
        """--no-backup should not create .bak file."""
        md = self._write_md("test.md", f"![img](data:image/png;base64,{MINI_PNG_B64})")
        extract_images_from_md(md, no_backup=True)

        self.assertFalse(md.with_suffix(".md.bak").exists())
        # But image should still be extracted
        self.assertTrue((self.tmpdir_p / "__assets" / "test").exists())

    def test_custom_output_dir(self):
        """Custom output directory."""
        custom_dir = self.tmpdir_p / "custom_output"
        md = self._write_md("test.md", f"![img](data:image/png;base64,{MINI_PNG_B64})")
        extract_images_from_md(md, output_dir=custom_dir)

        self.assertTrue(custom_dir.exists())
        self.assertEqual(len(list(custom_dir.iterdir())), 1)

    def test_file_not_found(self):
        """Non-existent file should return empty."""
        results = extract_images_from_md(Path("/nonexistent/file.md"))
        self.assertEqual(len(results), 0)

    def test_alt_text_special_chars_preserved(self):
        """Alt text with special characters is preserved in replacement."""
        md = self._write_md("test.md", f"![a & b <c>](data:image/png;base64,{MINI_PNG_B64})")
        extract_images_from_md(md)
        new_text = md.read_text(encoding="utf-8")
        self.assertIn("![a & b <c>](__assets/test/", new_text)


class TestProcessPath(unittest.TestCase):
    """Test directory processing and recursive mode."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.tmpdir_p = Path(self.tmpdir)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_md(self, rel_path: str, content: str) -> Path:
        p = self.tmpdir_p / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def test_recursive_directory(self):
        """Recursive mode finds MD files in subdirectories."""
        self._write_md("a.md", f"![x](data:image/png;base64,{MINI_PNG_B64})")
        self._write_md("sub/b.md", f"![x](data:image/png;base64,{MINI_PNG_B64})")

        total = process_path(self.tmpdir_p, None, dry_run=False, recursive=True,
                             no_backup=True, verbose=False)
        self.assertEqual(total, 2)

    def test_non_recursive_directory(self):
        """Non-recursive mode only processes top-level MD files."""
        self._write_md("a.md", f"![x](data:image/png;base64,{MINI_PNG_B64})")
        self._write_md("sub/b.md", f"![x](data:image/png;base64,{MINI_PNG_B64})")

        total = process_path(self.tmpdir_p, None, dry_run=False, recursive=False,
                             no_backup=True, verbose=False)
        self.assertEqual(total, 1)

    def test_non_md_file_skipped(self):
        """Non-MD files should be skipped."""
        txt_file = self.tmpdir_p / "readme.txt"
        txt_file.write_text("hello")
        total = process_path(txt_file, None, dry_run=False, recursive=False,
                             no_backup=True, verbose=False)
        self.assertEqual(total, 0)


class TestCLI(unittest.TestCase):
    """Test argparse CLI."""

    def test_valid_args(self):
        """CLI parses valid args."""
        with tempfile.TemporaryDirectory() as tmpdir:
            md = Path(tmpdir) / "test.md"
            md.write_text("hello", encoding="utf-8")
            # Should not raise
            main([str(md), "--dry-run", "-v"])

    def test_missing_positional(self):
        """Missing positional arg should exit with error."""
        with self.assertRaises(SystemExit):
            main([])

    def test_main_with_test_file(self):
        """End-to-end test via main()."""
        with tempfile.TemporaryDirectory() as tmpdir:
            md = Path(tmpdir) / "test.md"
            md.write_text(f"![img](data:image/png;base64,{MINI_PNG_B64})", encoding="utf-8")

            main([str(md), "--no-backup"])

            new_text = md.read_text(encoding="utf-8")
            self.assertNotIn("base64,", new_text)
            self.assertIn("__assets/", new_text)

            assets = Path(tmpdir) / "__assets" / "test"
            self.assertTrue(assets.exists())
            self.assertEqual(len(list(assets.iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
