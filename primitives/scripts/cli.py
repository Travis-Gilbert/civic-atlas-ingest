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


if __name__ == "__main__":
    cli()
