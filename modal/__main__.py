"""civic-atlas-ingest CLI entrypoint (discovery helper).

Modal apps are deployed via:

  modal deploy modal/ingest_overpass.py
  modal deploy modal/ingest_sanborn.py
  modal deploy modal/ingest_assessor.py

This CLI is a thin discovery layer that prints the deployed targets
and city queue. It is not the primary execution path.
"""

from __future__ import annotations

import sys

import click

from . import __version__
from .city_targets import CITY_TARGETS


@click.group()
@click.version_option(__version__)
def cli() -> None:
    """civic-atlas-ingest discovery CLI."""


@cli.command()
def cities() -> None:
    """List target cities in priority order."""
    for i, target in enumerate(CITY_TARGETS, start=1):
        click.echo(f"{i:2d}. {target.slug:12s}  {target.display_name:20s}  bbox={target.bbox}")


@cli.command()
def apps() -> None:
    """List Modal apps in this repo."""
    click.echo("modal/ingest_overpass.py  -- OSM building footprints + tags")
    click.echo("modal/ingest_sanborn.py   -- Mapwarper Sanborn sheets")
    click.echo("modal/ingest_assessor.py  -- per-city assessor records")


if __name__ == "__main__":
    sys.exit(cli())
