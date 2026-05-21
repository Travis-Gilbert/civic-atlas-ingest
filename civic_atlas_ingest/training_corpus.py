"""Typed training-corpus records for Civic Atlas building-head training."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .coverage_quality import ProvenanceLane, RecordCoverage, merge_strongest

SCHEMA_VERSION = "civic-atlas-training-corpus/v1"
DEFAULT_TENANT_SLUG = "flint"
DEFAULT_OUTPUT_URI = "s3://civic-atlas/training"

JsonDict = dict[str, Any]


@dataclass(frozen=True)
class TrainingCorpusRecord:
    """One source-backed building record plus its part-training graph."""

    record_id: str
    tenant_slug: str
    corpus_tenant_id: str
    city: str
    source: str
    source_id: str
    source_uri: str | None
    observed_at: str
    geometry: JsonDict
    fields: JsonDict
    field_lanes: dict[str, str]
    coverage: RecordCoverage
    archetype_label: str
    part_labels: JsonDict
    training_graph: JsonDict
    extra: JsonDict

    def to_json(self) -> JsonDict:
        return {
            "schema_version": SCHEMA_VERSION,
            "record_id": self.record_id,
            "tenant_slug": self.tenant_slug,
            "corpus_tenant_id": self.corpus_tenant_id,
            "city": self.city,
            "source": self.source,
            "source_id": self.source_id,
            "source_uri": self.source_uri,
            "observed_at": self.observed_at,
            "geometry": self.geometry,
            "bbox": geometry_bbox(self.geometry),
            "fields": self.fields,
            "field_lanes": self.field_lanes,
            "coverage": self.coverage.to_envelope(),
            "archetype_label": self.archetype_label,
            "part_labels": self.part_labels,
            "training_graph": self.training_graph,
            "extra": self.extra,
        }


@dataclass(frozen=True)
class TrainingBatchResult:
    """Write result for a content-hashed corpus batch."""

    tenant_slug: str
    source: str
    run_date: str
    record_count: int
    content_hash: str
    local_dir: Path
    jsonl_path: Path
    manifest_path: Path
    parquet_path: Path | None
    intended_uri: str
    uploaded_uri: str | None

    def to_json(self) -> JsonDict:
        return {
            "tenant_slug": self.tenant_slug,
            "source": self.source,
            "run_date": self.run_date,
            "record_count": self.record_count,
            "content_hash": self.content_hash,
            "local_dir": str(self.local_dir),
            "jsonl_path": str(self.jsonl_path),
            "manifest_path": str(self.manifest_path),
            "parquet_path": str(self.parquet_path) if self.parquet_path else None,
            "intended_uri": self.intended_uri,
            "uploaded_uri": self.uploaded_uri,
        }


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: Any) -> str:
    return "sha256-" + hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def geometry_bbox(geometry: JsonDict) -> list[float] | None:
    coords: list[tuple[float, float]] = []

    def visit(value: Any) -> None:
        if not isinstance(value, list):
            return
        if len(value) >= 2 and all(isinstance(v, int | float) for v in value[:2]):
            coords.append((float(value[0]), float(value[1])))
            return
        for item in value:
            visit(item)

    visit(geometry.get("coordinates"))
    if not coords:
        return None
    xs = [coord[0] for coord in coords]
    ys = [coord[1] for coord in coords]
    return [min(xs), min(ys), max(xs), max(ys)]


def bbox_polygon(min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> JsonDict:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [min_lon, min_lat],
                [max_lon, min_lat],
                [max_lon, max_lat],
                [min_lon, max_lat],
                [min_lon, min_lat],
            ]
        ],
    }


def make_training_record(
    *,
    source: str,
    source_id: str,
    city: str,
    geometry: JsonDict,
    fields: JsonDict,
    lanes: dict[str, ProvenanceLane | list[ProvenanceLane]],
    tenant_slug: str = DEFAULT_TENANT_SLUG,
    corpus_tenant_id: str = "corpus",
    source_uri: str | None = None,
    observed_at: str | None = None,
    extra: JsonDict | None = None,
) -> TrainingCorpusRecord:
    coverage = _coverage_from_lanes(lanes)
    field_lanes = {field.field_name: field.lane.value for field in coverage.fields}
    archetype_label = classify_archetype(fields)
    part_labels = build_part_labels(fields, archetype_label)
    seed = {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "source_id": source_id,
        "city": city,
        "geometry": geometry,
    }
    record_id = f"{source}:{city}:{hashlib.sha256(stable_json(seed).encode()).hexdigest()[:16]}"
    training_graph = build_training_graph(
        record_id=record_id,
        archetype_label=archetype_label,
        part_labels=part_labels,
        coverage=coverage,
    )
    return TrainingCorpusRecord(
        record_id=record_id,
        tenant_slug=tenant_slug,
        corpus_tenant_id=corpus_tenant_id,
        city=city,
        source=source,
        source_id=source_id,
        source_uri=source_uri,
        observed_at=observed_at or datetime.now(UTC).isoformat(),
        geometry=geometry,
        fields=fields,
        field_lanes=field_lanes,
        coverage=coverage,
        archetype_label=archetype_label,
        part_labels=part_labels,
        training_graph=training_graph,
        extra=extra or {},
    )


def classify_archetype(fields: JsonDict) -> str:
    building = _lower(fields.get("building") or fields.get("building_type"))
    amenity = _lower(fields.get("amenity"))
    landuse = _lower(fields.get("landuse"))
    use_type = _lower(fields.get("use_type") or fields.get("ground_floor_use"))
    stories = _int_value(fields.get("stories") or fields.get("story_count")) or 1

    if amenity in {"place_of_worship"} or building in {"church", "cathedral", "chapel"}:
        return "church"
    if amenity == "school" or building in {"school", "college", "university"}:
        return "school"
    if amenity == "fuel" or building in {"service", "gas_station"}:
        return "gas-station"
    if building in {"warehouse", "storage_tank"} or "warehouse" in use_type:
        return "warehouse"
    if building in {"industrial", "manufacture"} or landuse == "industrial":
        return "factory-bay"
    if building in {"retail", "commercial"} or use_type in {"retail", "storefront"}:
        if stories >= 3 or use_type == "mixed_use":
            return "mixed-use-storefront"
        return "commercial-brick-two-story"
    if building in {"apartments", "mixed_use"} and stories >= 3:
        return "mixed-use-storefront"
    return "frame-house-with-porch"


def build_part_labels(fields: JsonDict, archetype_label: str) -> JsonDict:
    stories = _int_value(fields.get("stories") or fields.get("story_count"))
    height_m = _float_value(fields.get("height_m") or fields.get("height"))
    if height_m is None and stories:
        height_m = round(stories * 3.25, 2)

    facade_material = fields.get("primary_material") or fields.get("building_material")
    roof_form = fields.get("roof_type") or fields.get("roof_shape")
    use_type = fields.get("use_type") or fields.get("building") or fields.get("amenity")

    labels: JsonDict = {
        "mass": {
            "story_count": stories,
            "height_m": height_m,
            "footprint_area_m2": _float_value(fields.get("footprint_area_m2")),
        },
        "facade": {
            "material": facade_material,
            "color": fields.get("facade_color"),
            "opening_type": fields.get("opening_type"),
        },
        "roof": {
            "form": roof_form,
            "material": fields.get("roof_material"),
            "pitch_degrees": _float_value(fields.get("roof_pitch_degrees")),
        },
        "ground_floor": {
            "use_type": use_type,
            "storefront_type": fields.get("storefront_type"),
            "entry_location": fields.get("entry_location"),
            "has_awning": fields.get("has_awning"),
        },
        "ornaments": {
            "archetype": archetype_label,
            "kind": fields.get("ornament_kind"),
        },
    }
    return {key: _drop_none(value) for key, value in labels.items()}


def build_training_graph(
    *,
    record_id: str,
    archetype_label: str,
    part_labels: JsonDict,
    coverage: RecordCoverage,
) -> JsonDict:
    nodes: list[JsonDict] = [
        {
            "id": record_id,
            "kind": "building_presence",
            "archetype_label": archetype_label,
            "coverage_quality": round(coverage.quality, 4),
        }
    ]
    edges: list[JsonDict] = []
    for part_type, labels in sorted(part_labels.items()):
        part_id = f"{record_id}:{part_type}"
        nodes.append(
            {
                "id": part_id,
                "kind": "reconstruction_part",
                "part_type": part_type,
                "labels": labels,
            }
        )
        edges.append({"source": record_id, "target": part_id, "relation": "has_part"})
    return {"nodes": nodes, "edges": edges}


def write_training_batch(
    records: list[TrainingCorpusRecord],
    *,
    source: str,
    tenant_slug: str = DEFAULT_TENANT_SLUG,
    output_uri: str | None = None,
    run_date: date | str | None = None,
) -> TrainingBatchResult:
    output_uri = output_uri or os.environ.get("CIVIC_ATLAS_CORPUS_OUTPUT_URI", DEFAULT_OUTPUT_URI)
    run_date_text = _run_date_text(run_date)
    local_root = _local_output_root(output_uri)
    local_dir = local_root / tenant_slug / source / run_date_text
    local_dir.mkdir(parents=True, exist_ok=True)

    json_records = [record.to_json() for record in records]
    jsonl_path = local_dir / "records.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for record in json_records:
            f.write(json.dumps(record, sort_keys=True) + "\n")

    content_hash = "sha256-" + hashlib.sha256(jsonl_path.read_bytes()).hexdigest()
    parquet_path = _write_parquet_if_available(json_records, local_dir / "records.parquet")
    intended_uri = _join_uri(output_uri, tenant_slug, source, run_date_text)

    manifest_path = local_dir / "manifest.json"
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "tenant_slug": tenant_slug,
        "corpus_tenant_id": "corpus",
        "source": source,
        "run_date": run_date_text,
        "record_count": len(records),
        "content_hash": content_hash,
        "jsonl": jsonl_path.name,
        "parquet": parquet_path.name if parquet_path else None,
        "parquet_status": "written" if parquet_path else "pyarrow-not-installed",
        "intended_uri": intended_uri,
        "uploaded_uri": None,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    uploaded_uri = _upload_if_requested(local_dir, intended_uri)
    if uploaded_uri:
        manifest["uploaded_uri"] = uploaded_uri
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    return TrainingBatchResult(
        tenant_slug=tenant_slug,
        source=source,
        run_date=run_date_text,
        record_count=len(records),
        content_hash=content_hash,
        local_dir=local_dir,
        jsonl_path=jsonl_path,
        manifest_path=manifest_path,
        parquet_path=parquet_path,
        intended_uri=intended_uri,
        uploaded_uri=uploaded_uri,
    )


def _coverage_from_lanes(
    lanes: dict[str, ProvenanceLane | list[ProvenanceLane]],
) -> RecordCoverage:
    normalized: dict[str, list[ProvenanceLane]] = {}
    for field_name, lane_or_lanes in lanes.items():
        if isinstance(lane_or_lanes, ProvenanceLane):
            normalized[field_name] = [lane_or_lanes]
        else:
            normalized[field_name] = list(lane_or_lanes)
    return merge_strongest(normalized)


def _write_parquet_if_available(records: list[JsonDict], path: Path) -> Path | None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ModuleNotFoundError:
        return None

    rows = [{"record_json": json.dumps(record, sort_keys=True)} for record in records]
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path)
    return path


def _upload_if_requested(local_dir: Path, intended_uri: str) -> str | None:
    if not intended_uri.startswith("s3://"):
        return None
    if os.environ.get("CIVIC_ATLAS_ENABLE_S3_UPLOAD") != "1":
        return None
    try:
        import boto3
    except ModuleNotFoundError as exc:
        raise RuntimeError("CIVIC_ATLAS_ENABLE_S3_UPLOAD=1 requires boto3") from exc

    bucket, prefix = _split_s3_uri(intended_uri)
    client = boto3.client("s3")
    for path in local_dir.iterdir():
        if not path.is_file():
            continue
        key = f"{prefix}/{path.name}" if prefix else path.name
        client.upload_file(str(path), bucket, key)
    return intended_uri


def _split_s3_uri(uri: str) -> tuple[str, str]:
    without_scheme = uri.removeprefix("s3://")
    bucket, _, prefix = without_scheme.partition("/")
    return bucket, prefix.rstrip("/")


def _join_uri(uri: str, *parts: str) -> str:
    return "/".join([uri.rstrip("/"), *(part.strip("/") for part in parts if part)])


def _local_output_root(output_uri: str) -> Path:
    if output_uri.startswith("s3://"):
        return Path(os.environ.get("CIVIC_ATLAS_CORPUS_LOCAL_OUT", "artifacts/training"))
    if output_uri.startswith("file://"):
        return Path(output_uri.removeprefix("file://"))
    return Path(output_uri)


def _run_date_text(run_date: date | str | None) -> str:
    if isinstance(run_date, str):
        return run_date
    if isinstance(run_date, date):
        return run_date.isoformat()
    return datetime.now(UTC).date().isoformat()


def _drop_none(value: JsonDict) -> JsonDict:
    return {key: item for key, item in value.items() if item is not None}


def _lower(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _int_value(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return None


def _float_value(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        text = str(value).lower().replace("meters", "").replace("meter", "").rstrip(" m")
        return float(text)
    except ValueError:
        return None
