"""Hash every archetype's authored asset or procedural manifest.

The Scene Foundry pins each rendered asset to a specific archetype
hash. When an archetype changes, every spec rendered against the old
version needs an explicit re-render; this script emits the hashes
the worker checks against.

Output: `archetypes/_hashes.json`.

  { "frame-house-with-porch": "sha256-abc123...", ... }
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARCHETYPES_DIR = REPO_ROOT / "archetypes"
RENDER_SCRIPT = REPO_ROOT / "scripts" / "render_spec.py"
OUT_PATH = ARCHETYPES_DIR / "_hashes.json"


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_paths(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for path in paths:
        h.update(str(path.relative_to(REPO_ROOT)).encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def main() -> int:
    hashes: dict[str, str | None] = {}
    for child in sorted(ARCHETYPES_DIR.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("_") or child.name.startswith("."):
            continue
        slug = child.name.replace("_", "-")
        blend = child / "archetype.blend"
        manifest = child / "__init__.py"
        if blend.exists():
            hashes[slug] = "sha256-" + hash_file(blend)
        elif manifest.exists():
            hashes[slug] = "sha256-" + hash_paths([manifest, RENDER_SCRIPT])
        else:
            hashes[slug] = None
            print(f"missing: {blend} or {manifest}", file=sys.stderr)
            continue
        print(f"hashed: {slug} -> {hashes[slug]}")

    OUT_PATH.write_text(json.dumps(hashes, indent=2), encoding="utf-8")
    print(f"wrote {OUT_PATH}")

    # Non-zero if any archetype is missing both binary and procedural assets.
    return 0 if all(hashes.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
