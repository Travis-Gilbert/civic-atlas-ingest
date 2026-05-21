"""civic-atlas-ingest CLI entrypoint (discovery helper).

Ray jobs are submitted via:

  ray job submit --working-dir . -- python -m civic_atlas_ingest.ingest_overpass detroit
  ray job submit --working-dir . -- python -m civic_atlas_ingest.ingest_sanborn 12345
  ray job submit --working-dir . -- python -m civic_atlas_ingest.ingest_assessor detroit

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
    """List Ray jobs and Serve deployments in this repo."""
    click.echo("civic_atlas_ingest/ingest_overpass.py -- OSM building footprints + tags")
    click.echo("civic_atlas_ingest/ingest_sanborn.py -- Mapwarper Sanborn sheets")
    click.echo("civic_atlas_ingest/ingest_assessor.py -- per-city assessor records")
    click.echo("civic_atlas_ingest/building_head_train.py -- civic Pairformer training")
    click.echo("civic_atlas_ingest/building_head_infer.py -- Ray Serve Pairformer inference")
    click.echo("civic_atlas_ingest/scene_foundry.py -- ReconstructionSpec -> glTF rendering")


if __name__ == "__main__":
    sys.exit(cli())
