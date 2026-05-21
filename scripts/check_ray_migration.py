from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    print(f"ray-migration check failed: {message}", file=sys.stderr)
    sys.exit(1)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> None:
    if (ROOT / "modal").exists():
        fail("legacy modal/ package still exists")
    if not (ROOT / "civic_atlas_ingest").is_dir():
        fail("civic_atlas_ingest/ package missing")
    if not (ROOT / "ray_cluster" / "runpod.yaml").is_file():
        fail("ray_cluster/runpod.yaml missing")

    pyproject = tomllib.loads(read("pyproject.toml"))
    dependencies = "\n".join(pyproject["project"]["dependencies"])
    if "modal" in dependencies.lower():
        fail("pyproject still depends on Modal")
    if "ray" not in dependencies.lower():
        fail("pyproject does not declare Ray")

    scripts = pyproject["project"]["scripts"]
    if scripts.get("civic-atlas-ingest") != "civic_atlas_ingest.__main__:cli":
        fail("console script still points at the legacy package")

    for path in (ROOT / "civic_atlas_ingest").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in ("import modal", "from modal", "@modal", "modal."):
            if needle in text:
                fail(f"{path.relative_to(ROOT)} still references {needle!r}")

    print("ray-migration check passed")


if __name__ == "__main__":
    main()
