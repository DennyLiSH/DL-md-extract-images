# md-extract-images

Extract inline base64 images from Markdown files into separate files.

Finds all `![alt](data:image/...;base64,...)` references, decodes the base64 data, saves images to `__assets/`, and replaces inline references with relative file paths.

## Install

```bash
uv tool install .
# or
pip install .
```

## Usage

```bash
# Single file
md-extract-images report.md

# Directory (recursive)
md-extract-images -r docs/

# Dry-run (preview without writing)
md-extract-images report.md --dry-run

# Custom output directory
md-extract-images report.md --output-dir images/
```

## Features

- **Zero dependencies** — Python stdlib only
- **Automatic backup** — creates `.bak` before modification (disable with `--no-backup`)
- **Content dedup** — identical images share one file via SHA-256
- **Recursion** — process entire directory trees

## Supported formats

PNG, JPEG, GIF, SVG, WebP

## License

[MIT](LICENSE)
