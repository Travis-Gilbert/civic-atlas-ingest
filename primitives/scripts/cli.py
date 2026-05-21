"""civic-atlas-primitives CLI.

Local-only tool for inspecting archetypes and validating their
manifests. The actual render path lives in `scripts/render_spec.py`
and is invoked by Blender, not directly by users.

Usage:

  civic-atlas-primitives list
  civic-atlas-primitives validate
  civic-atlas-primitives describe frame-house-with-porch
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

# Add parent so `archetypes` package resolves when the CLI is invoked
# via `python -m scripts.cli`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from archetypes import ARCHETYPES
from archetypes._manifest_schema import validate as validate_manifest
from openbim import write_ifc


@click.group()
def cli() -> None:
    """civic-atlas-primitives operator CLI."""


@cli.command()
def list_archetypes() -> None:
    """List archetype slugs."""
    for slug in sorted(ARCHETYPES.keys()):
        click.echo(slug)


cli.add_command(list_archetypes, name="list")


@cli.command()
def validate() -> None:
    """Validate every archetype manifest."""
    failures = []
    for slug, manifest in sorted(ARCHETYPES.items()):
        try:
            validate_manifest(manifest)
        except ValueError as e:
            failures.append((slug, str(e)))
        else:
            click.echo(f"ok: {slug}")
    if failures:
        click.echo(f"\n{len(failures)} failures:", err=True)
        for slug, msg in failures:
            click.echo(f"  {slug}: {msg}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("slug")
def describe(slug: str) -> None:
    """Print the manifest for one archetype as JSON."""
    if slug not in ARCHETYPES:
        click.echo(f"unknown archetype: {slug}", err=True)
        click.echo(f"valid: {', '.join(sorted(ARCHETYPES.keys()))}", err=True)
        sys.exit(2)
    click.echo(json.dumps(ARCHETYPES[slug], indent=2))


@cli.command("export-ifc")
@click.argument("slug")
@click.argument("spec_json", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("out_path", type=click.Path(dir_okay=False, path_type=Path))
def export_ifc(slug: str, spec_json: Path, out_path: Path) -> None:
    """Write an OpenBIM IFC sidecar for one archetype/spec pair."""
    if slug not in ARCHETYPES:
        click.echo(f"unknown archetype: {slug}", err=True)
        sys.exit(2)
    spec = json.loads(spec_json.read_text(encoding="utf-8"))
    write_ifc(out_path, archetype=slug, spec=spec)
    click.echo(str(out_path))


if __name__ == "__main__":
    cli()
