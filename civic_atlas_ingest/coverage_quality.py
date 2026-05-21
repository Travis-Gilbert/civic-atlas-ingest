"""Coverage quality scoring for ingested building records.

Phase 5 stamps every `BuildingPresence` and every `ArtifactAnchor`
with a `coverage_quality` score in [0, 1]. Phase 6 training
weights its loss by this score so that high-confidence fields
contribute more than guesses.

This module's output is written to
`PartProvenance.coverage_quality` (field number 5) in
our-civic-atlas-backend/proto/civic_atlas/v1/reconstruction.proto.
At ingest time the score is per-record (mean over populated
fields); when the corpus tenant is read by Phase 6 training, the
score is per-part because parts share one PartProvenance envelope
in Codex's design.

The scoring is intentionally simple and explainable. Per-record
quality is the unweighted mean of per-field quality across the
populated fields. Per-field quality is sourced from a small
provenance ladder (most-trustworthy at top):

  1.00  authoritative recent measurement (assessor in last 5y)
  0.95  authoritative historical measurement (assessor older)
  0.85  hand-digitized from a primary archival source (Sanborn,
        HABS, fire insurance map)
  0.70  derived from OSM tag set explicitly written by a mapper
  0.55  derived from OSM tag set inferred by an editor heuristic
  0.40  inferred from a co-located neighbor (spatial join with no
        direct match)
  0.20  default catch-all when only a footprint is known

When the same field appears in multiple sources, the highest-quality
source wins. Codex's per-part PartProvenance lives one level above
per-field provenance; this module sets the per-part score by taking
the mean over the part's contributing field lanes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum


class ProvenanceLane(Enum):
    AUTHORITATIVE_RECENT = "authoritative_recent"
    AUTHORITATIVE_HISTORICAL = "authoritative_historical"
    PRIMARY_ARCHIVAL = "primary_archival"
    OSM_TAGGED = "osm_tagged"
    OSM_INFERRED = "osm_inferred"
    NEIGHBOR_INFERRED = "neighbor_inferred"
    FOOTPRINT_ONLY = "footprint_only"


_LANE_SCORES: Mapping[ProvenanceLane, float] = {
    ProvenanceLane.AUTHORITATIVE_RECENT: 1.00,
    ProvenanceLane.AUTHORITATIVE_HISTORICAL: 0.95,
    ProvenanceLane.PRIMARY_ARCHIVAL: 0.85,
    ProvenanceLane.OSM_TAGGED: 0.70,
    ProvenanceLane.OSM_INFERRED: 0.55,
    ProvenanceLane.NEIGHBOR_INFERRED: 0.40,
    ProvenanceLane.FOOTPRINT_ONLY: 0.20,
}


@dataclass
class FieldEvidence:
    """One field's best-known source lane."""

    field_name: str
    lane: ProvenanceLane


@dataclass
class RecordCoverage:
    """Per-record coverage report: which fields, which lanes, mean quality."""

    fields: list[FieldEvidence] = field(default_factory=list)

    @property
    def quality(self) -> float:
        """Mean of per-field quality. 0.0 if no fields are populated."""
        if not self.fields:
            return 0.0
        return sum(_LANE_SCORES[fe.lane] for fe in self.fields) / len(self.fields)

    @property
    def field_count(self) -> int:
        return len(self.fields)

    def to_envelope(self) -> dict[str, object]:
        """Serialize for the gRPC payload. Shape is decoupled from the
        backend's FieldEnvelope and gets remapped at the boundary."""
        return {
            "coverage_quality": round(self.quality, 4),
            "field_count": self.field_count,
            "fields": [
                {"name": fe.field_name, "lane": fe.lane.value}
                for fe in self.fields
            ],
        }


def merge_strongest(per_field: Mapping[str, list[ProvenanceLane]]) -> RecordCoverage:
    """For each field, take the strongest (lowest enum order) lane available.

    Input is `{field_name: [lane, lane, ...]}`. Output is a `RecordCoverage`
    with one entry per field, lane = strongest of that field's list.
    """
    out = RecordCoverage()
    for field_name, lanes in per_field.items():
        if not lanes:
            continue
        strongest = min(lanes, key=lambda lane: list(ProvenanceLane).index(lane))
        out.fields.append(FieldEvidence(field_name=field_name, lane=strongest))
    return out
