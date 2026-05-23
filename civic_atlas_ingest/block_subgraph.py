"""Block-subgraph assembler for Pairformer training.

The CivicPairformerBuildingHead consumes a multi-building "block"
subgraph: N building nodes with the 10 civic relation types
(adjacent_to, fronts_street, same_block_as, anchored_by,
temporal_predecessor_of, temporal_successor_of, similar_to,
shares_party_wall, shares_setback_line, shares_cornice_line).

TrainingCorpusRecord rows are per-building; their stored
`training_graph` field is a STAR (focus + 5 part nodes, connected by
generic "has_part" edges). That's correct as a document but wrong
as a training input. This module bridges the two:

  1. Group records by spatial proximity / temporal lineage into blocks.
  2. For each block, derive inter-building relations from geometry:
       centroid distance < 30 m   → adjacent_to
       parcel sharing street       → fronts_street
       same block polygon          → same_block_as
       same parcel different epoch → temporal_predecessor / successor
       shared edge in OSM data     → shares_party_wall
  3. Produce the Pairformer's expected tensors:
       x:             (N, node_dim) node features (Theseus embeddings)
       edge_index:    (2, E) connectivity
       edge_type:     (E,) integer relation type
       edge_attr:     (E, edge_dim) edge features
       focus_node_idx (G,) one focus building per block
       batch:         (N,) block-membership index per node
  4. Produce label tensors aligned to the focus nodes:
       part_targets:        dict[field_name, (G,) categorical idx]
       part_value_targets:  dict[field_name, (G,) regression value]
       part_target_masks:   dict[field_name, (G,) bool — true when label present]

The synthetic path is essential: it builds shape-correct blocks
from random initialization so the training loop can be validated
before any real Sanborn corpus exists. Once the corpus lands, the
same assembler consumes it without modification.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

from .building_head_pairformer import (
    CIVIC_RELATION_TYPES,
    CivicPairformerConfig,
    DEFAULT_PART_CATEGORIES,
    DEFAULT_PART_REGRESSIONS,
)
from .training_corpus import TrainingCorpusRecord


# Distance thresholds (meters) for deriving inter-building relations
# from geometry. Tuned for Flint's parcel scale; would calibrate per
# city pack later.
ADJACENT_DISTANCE_M = 30.0
SAME_BLOCK_DISTANCE_M = 120.0
STREET_FRONTAGE_DISTANCE_M = 60.0

RELATION_INDEX: dict[str, int] = {name: idx for idx, name in enumerate(CIVIC_RELATION_TYPES)}


@dataclass
class BlockSubgraph:
    """Pairformer-ready tensor bundle for one or more building blocks.

    All fields are torch.Tensor when constructed via the
    assembler. The dataclass holds them as `Any` so the module
    doesn't crash to import when torch isn't installed (mirrors
    the defensive-import pattern in building_head_pairformer.py).
    """

    x: Any  # (N, node_dim)
    edge_index: Any  # (2, E)
    edge_type: Any  # (E,) int64
    edge_attr: Any  # (E, edge_dim)
    focus_node_idx: Any  # (G,) int64
    batch: Any  # (N,) int64
    part_targets: dict[str, Any]  # field → (G,) int64
    part_value_targets: dict[str, Any]  # field → (G,) float32
    part_target_masks: dict[str, Any]  # field → (G,) bool


# ── Categorical vocab mapping ───────────────────────────────────────


def _category_index(field: str, value: Any, categories: dict[str, tuple[str, ...]]) -> int | None:
    """Map a TrainingCorpusRecord raw value to the Pairformer's
    categorical index for that field. Returns None when the value
    doesn't match any vocabulary entry (the loss masks these out)."""
    if value is None:
        return None
    vocab = categories.get(field)
    if vocab is None:
        return None
    normalized = str(value).strip().lower().replace(" ", "_")
    if normalized in vocab:
        return vocab.index(normalized)
    return None


def _story_count_bucket(stories: Any) -> str | None:
    """Map an integer story count to the Pairformer's 4-bucket vocab."""
    if stories is None:
        return None
    try:
        n = int(stories)
    except (TypeError, ValueError):
        return None
    if n <= 1:
        return "one"
    if n == 2:
        return "two"
    if n == 3:
        return "three"
    return "four_plus"


def _mass_form_from_archetype(archetype_label: str | None) -> str | None:
    """Map archetype slugs to the mass_form vocab. Sanborn-derived
    records have an archetype_label but no explicit mass_form;
    derive a reasonable default."""
    if not archetype_label:
        return None
    # All the Phase B archetypes map cleanly to rectangular massing
    # at this resolution. L-shaped + U-shaped require footprint
    # analysis the corpus loader doesn't run yet.
    return "rectangular"


# ── Centroid utilities ──────────────────────────────────────────────


def _centroid_lng_lat(geometry: dict[str, Any]) -> tuple[float, float] | None:
    """Approximate centroid of a Polygon / MultiPolygon GeoJSON."""
    coords = geometry.get("coordinates")
    if not coords:
        return None
    # For Polygon, coords is [[[lng, lat], ...], [hole], ...]; first ring.
    # For MultiPolygon, coords is [[[[lng, lat], ...]], ...]; first ring of first poly.
    try:
        if geometry.get("type") == "Polygon":
            ring = coords[0]
        elif geometry.get("type") == "MultiPolygon":
            ring = coords[0][0]
        else:
            return None
    except (IndexError, TypeError):
        return None
    if not ring:
        return None
    lngs = [p[0] for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
    lats = [p[1] for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
    if not lngs:
        return None
    return (sum(lngs) / len(lngs), sum(lats) / len(lats))


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in meters between (lng, lat) pairs."""
    lng_a, lat_a = a
    lng_b, lat_b = b
    radius = 6_371_000.0
    phi_a = math.radians(lat_a)
    phi_b = math.radians(lat_b)
    d_phi = math.radians(lat_b - lat_a)
    d_lambda = math.radians(lng_b - lng_a)
    s = math.sin(d_phi / 2) ** 2 + math.cos(phi_a) * math.cos(phi_b) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(s)))


def _derive_pair_relation(
    a: TrainingCorpusRecord,
    b: TrainingCorpusRecord,
) -> str | None:
    """Decide which of the 10 civic relations (if any) connects two
    buildings, based on their geometry + provenance metadata."""
    if a.source_id == b.source_id and a.source == b.source:
        return None  # same record; no self-edge
    centroid_a = _centroid_lng_lat(a.geometry)
    centroid_b = _centroid_lng_lat(b.geometry)
    if centroid_a is None or centroid_b is None:
        return None
    dist = _haversine_m(centroid_a, centroid_b)

    # Temporal: same source_id stem (e.g. same parcel ID) across
    # different sheet years. Encoded in source_id structure
    # (e.g. "sanborn:flint-1899:parcel-42" vs "sanborn:flint-1925:parcel-42").
    parcel_a = _parcel_token(a)
    parcel_b = _parcel_token(b)
    year_a = _year_token(a)
    year_b = _year_token(b)
    if parcel_a and parcel_a == parcel_b and year_a and year_b and year_a != year_b:
        return "temporal_predecessor_of" if year_a < year_b else "temporal_successor_of"

    if dist <= ADJACENT_DISTANCE_M:
        return "adjacent_to"
    if dist <= STREET_FRONTAGE_DISTANCE_M:
        return "fronts_street"
    if dist <= SAME_BLOCK_DISTANCE_M:
        return "same_block_as"
    return None


def _parcel_token(record: TrainingCorpusRecord) -> str | None:
    """Extract the parcel identifier from a record's source_id, if any.
    Sanborn ingests emit source_ids like
    `flint-1925-03:polygon:7` — no parcel token. When real parcel
    joins land, source_ids will be `sanborn:parcel-12345:1925`. The
    extractor is permissive."""
    extra_parcel = record.extra.get("parcel_id") if isinstance(record.extra, dict) else None
    if isinstance(extra_parcel, str):
        return extra_parcel
    parts = record.source_id.split(":")
    for part in parts:
        if part.startswith("parcel-") or part.startswith("parcel_"):
            return part
    return None


def _year_token(record: TrainingCorpusRecord) -> int | None:
    """Extract an integer year from observed_at or extra metadata."""
    extra_year = record.extra.get("sheet_year") if isinstance(record.extra, dict) else None
    if isinstance(extra_year, int):
        return extra_year
    if isinstance(record.observed_at, str) and len(record.observed_at) >= 4:
        try:
            return int(record.observed_at[:4])
        except ValueError:
            return None
    return None


# ── Block subgraph construction ─────────────────────────────────────


def build_block_subgraph(
    records: list[TrainingCorpusRecord],
    config: CivicPairformerConfig | None = None,
    *,
    embeddings: dict[str, Any] | None = None,
) -> BlockSubgraph:
    """Assemble a Pairformer-ready block subgraph from N building records.

    `embeddings` maps record_id → (node_dim,) tensor or list. Records
    without an entry get a zero vector (the `missing_embedding` path).
    When `embeddings` is None, all nodes use zero features — useful
    for unit tests; the model still trains shapes correctly but
    cannot learn anything meaningful.
    """
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError(
            "build_block_subgraph requires torch; install the .[ml] extras."
        ) from exc

    config = config or CivicPairformerConfig()
    n = len(records)
    if n == 0:
        raise ValueError("cannot build block subgraph from zero records")

    # Node features.
    x_rows = []
    for record in records:
        emb = (embeddings or {}).get(record.record_id)
        if emb is None:
            x_rows.append(torch.zeros(config.node_dim, dtype=torch.float32))
        else:
            tensor = torch.as_tensor(emb, dtype=torch.float32).flatten()
            if tensor.numel() < config.node_dim:
                tensor = torch.nn.functional.pad(tensor, (0, config.node_dim - tensor.numel()))
            elif tensor.numel() > config.node_dim:
                tensor = tensor[: config.node_dim]
            x_rows.append(tensor)
    x = torch.stack(x_rows, dim=0)

    # Edges: pairwise relation derivation. O(n²) but n is per-block,
    # typically < 30 for Flint blocks.
    edges_src: list[int] = []
    edges_dst: list[int] = []
    edge_types: list[int] = []
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            relation = _derive_pair_relation(records[i], records[j])
            if relation is None:
                continue
            edges_src.append(i)
            edges_dst.append(j)
            edge_types.append(RELATION_INDEX[relation])
    if not edges_src:
        # Degenerate block (single building, or N buildings with no
        # derivable relations). Add a self-loop with relation 0 to
        # satisfy the RGCNConv shape requirement.
        edges_src = [0]
        edges_dst = [0]
        edge_types = [0]

    edge_index = torch.tensor([edges_src, edges_dst], dtype=torch.long)
    edge_type = torch.tensor(edge_types, dtype=torch.long)
    edge_attr = torch.zeros((edge_index.shape[1], config.edge_dim), dtype=torch.float32)

    # Focus + batch tensors. Single block → focus is the first node,
    # batch is all zeros.
    focus_node_idx = torch.tensor([0], dtype=torch.long)
    batch = torch.zeros(n, dtype=torch.long)

    # Per-part targets, computed from the focus record only (focus_idx=0).
    focus_record = records[0]
    part_targets, part_value_targets, part_target_masks = _targets_from_record(
        focus_record, config
    )

    return BlockSubgraph(
        x=x,
        edge_index=edge_index,
        edge_type=edge_type,
        edge_attr=edge_attr,
        focus_node_idx=focus_node_idx,
        batch=batch,
        part_targets=part_targets,
        part_value_targets=part_value_targets,
        part_target_masks=part_target_masks,
    )


def _targets_from_record(
    record: TrainingCorpusRecord,
    config: CivicPairformerConfig,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Build per-part categorical + regression target tensors for the
    focus record, plus a boolean mask per field marking whether the
    label is present (the loss zeroes out missing-label predictions
    so the model isn't penalized for our gaps)."""
    import torch

    categories = config.part_categories or DEFAULT_PART_CATEGORIES
    regressions = config.part_regressions or DEFAULT_PART_REGRESSIONS

    part_labels: dict[str, Any] = record.part_labels or {}
    mass_labels = part_labels.get("mass") or {}
    facade_labels = part_labels.get("facade") or {}
    roof_labels = part_labels.get("roof") or {}
    ground_labels = part_labels.get("ground_floor") or {}

    categorical_values: dict[str, str | None] = {
        "mass_form": _mass_form_from_archetype(record.archetype_label),
        "story_count": _story_count_bucket(mass_labels.get("story_count")),
        "facade_material": _normalize_categorical(facade_labels.get("material")),
        "roof_form": _normalize_categorical(roof_labels.get("form")),
        "ground_floor_use": _normalize_categorical(ground_labels.get("use_type")),
    }

    part_targets: dict[str, Any] = {}
    part_target_masks: dict[str, Any] = {}
    for field, value in categorical_values.items():
        idx = _category_index(field, value, categories)
        if idx is None:
            part_targets[field] = torch.zeros(1, dtype=torch.long)
            part_target_masks[field] = torch.zeros(1, dtype=torch.bool)
        else:
            part_targets[field] = torch.tensor([idx], dtype=torch.long)
            part_target_masks[field] = torch.ones(1, dtype=torch.bool)

    regression_values: dict[str, float | None] = {
        "height_meters": _to_float(mass_labels.get("height_m")),
        "bay_count": _to_float(facade_labels.get("bay_count")),
        "roof_pitch_degrees": _to_float(roof_labels.get("pitch_degrees")),
    }
    part_value_targets: dict[str, Any] = {}
    for field in regressions:
        value = regression_values.get(field)
        if value is None:
            part_value_targets[field] = torch.zeros(1, dtype=torch.float32)
            # Reuse the same mask key so the loss can zero out missing.
            part_target_masks[field] = torch.zeros(1, dtype=torch.bool)
        else:
            part_value_targets[field] = torch.tensor([value], dtype=torch.float32)
            part_target_masks[field] = torch.ones(1, dtype=torch.bool)

    return part_targets, part_value_targets, part_target_masks


def _normalize_categorical(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip().lower().replace(" ", "_")


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── Synthetic block generation (shape-test path) ────────────────────


def synthetic_block_subgraph(
    *,
    num_buildings: int = 5,
    config: CivicPairformerConfig | None = None,
    seed: int = 0,
) -> BlockSubgraph:
    """Generate a shape-correct random block subgraph for training-loop
    shape testing. Random initial features, random pair relations
    drawn from CIVIC_RELATION_TYPES, random per-part labels. The
    model can train on this without crashing; loss will hover near
    initial entropy since there's no real signal."""
    import torch

    config = config or CivicPairformerConfig()
    rng = random.Random(seed)
    torch_rng = torch.Generator()
    torch_rng.manual_seed(seed)

    x = torch.randn(num_buildings, config.node_dim, generator=torch_rng, dtype=torch.float32)

    edges_src = []
    edges_dst = []
    edge_types = []
    for i in range(num_buildings):
        for j in range(num_buildings):
            if i == j:
                continue
            # ~30% edge density across the block.
            if rng.random() < 0.3:
                edges_src.append(i)
                edges_dst.append(j)
                edge_types.append(rng.randrange(len(CIVIC_RELATION_TYPES)))
    if not edges_src:
        edges_src = [0]
        edges_dst = [0]
        edge_types = [0]
    edge_index = torch.tensor([edges_src, edges_dst], dtype=torch.long)
    edge_type = torch.tensor(edge_types, dtype=torch.long)
    edge_attr = torch.randn(
        edge_index.shape[1], config.edge_dim, generator=torch_rng, dtype=torch.float32
    )

    focus_node_idx = torch.tensor([0], dtype=torch.long)
    batch = torch.zeros(num_buildings, dtype=torch.long)

    part_targets: dict[str, Any] = {}
    part_value_targets: dict[str, Any] = {}
    part_target_masks: dict[str, Any] = {}
    for field, vocab in (config.part_categories or DEFAULT_PART_CATEGORIES).items():
        part_targets[field] = torch.tensor([rng.randrange(len(vocab))], dtype=torch.long)
        part_target_masks[field] = torch.ones(1, dtype=torch.bool)
    for field in config.part_regressions or DEFAULT_PART_REGRESSIONS:
        part_value_targets[field] = torch.tensor([rng.uniform(0.5, 30.0)], dtype=torch.float32)
        part_target_masks[field] = torch.ones(1, dtype=torch.bool)

    return BlockSubgraph(
        x=x,
        edge_index=edge_index,
        edge_type=edge_type,
        edge_attr=edge_attr,
        focus_node_idx=focus_node_idx,
        batch=batch,
        part_targets=part_targets,
        part_value_targets=part_value_targets,
        part_target_masks=part_target_masks,
    )
