"""Model promotion CLI.

`civic-atlas model promote <version> --to production --confirm`

Per Phase 6 spec: there is no automatic promotion. A trained model
sits in S3 at `models/building_head/<version>/`, eval report
included. To promote, a human runs this CLI with `--confirm`.

This module is intentionally NOT a Modal app. Promotion is a local
operation that flips an S3 pointer; no compute needed. Wrapping it
in Modal would only add latency.

Run:
    python -m modal.model_promote promote v0.3.1 --to production --confirm
    python -m modal.model_promote list
    python -m modal.model_promote diff v0.3.0 v0.3.1
"""

from __future__ import annotations

import os
import sys
from typing import Literal

import click

ModelSlot = Literal["staging", "production"]


@click.group()
def cli() -> None:
    """civic-atlas model promotion CLI."""


@cli.command()
@click.argument("version")
@click.option("--to", "slot", type=click.Choice(["staging", "production"]), required=True)
@click.option("--confirm", is_flag=True, help="Required for production promotion.")
def promote(version: str, slot: str, confirm: bool) -> None:
    """Promote a model version to a slot.

    Promotion to `production` requires `--confirm`. Promotion to
    `staging` does not (staging is intended to be ephemeral).
    """
    if slot == "production" and not confirm:
        click.echo("refusing to promote to production without --confirm", err=True)
        sys.exit(2)

    bucket = os.environ.get("S3_BUCKET", "civic-atlas")
    src = f"s3://{bucket}/models/building_head/{version}/"
    dst = f"s3://{bucket}/models/building_head/_slots/{slot}/"

    click.echo(f"==> Promote {version} -> {slot}")
    click.echo(f"    src: {src}")
    click.echo(f"    dst: {dst}")

    # Phase 6 stub: implementation copies the artifact manifest from
    # src/manifest.json to dst/manifest.json + writes a promotion
    # audit record to dst/_audit/<timestamp>.json with the operator's
    # AWS principal, the prior pointer, and the new pointer.
    click.echo("stub: real promotion CLI lands once the training app produces")
    click.echo("      a model artifact + manifest.")
    sys.exit(0)


@cli.command(name="list")
def list_models() -> None:
    """List trained model versions in S3."""
    bucket = os.environ.get("S3_BUCKET", "civic-atlas")
    click.echo(f"==> s3://{bucket}/models/building_head/")
    click.echo("stub: aws s3 ls equivalent. Phase 6.")


@cli.command()
@click.argument("version_a")
@click.argument("version_b")
def diff(version_a: str, version_b: str) -> None:
    """Compare two model versions on the evaluation report dimensions.

    Prints per-part-type accuracy delta. If `version_b` is worse on
    any part type, prints a warning. The promote command does not
    block on this; the operator is expected to read the diff before
    confirming.
    """
    bucket = os.environ.get("S3_BUCKET", "civic-atlas")
    click.echo(f"==> diff {version_a} -> {version_b}")
    click.echo(f"    s3://{bucket}/models/building_head/{version_a}/report.json")
    click.echo(f"    s3://{bucket}/models/building_head/{version_b}/report.json")
    click.echo("stub: real diff lands once evaluate() emits report.json.")


if __name__ == "__main__":
    cli()
