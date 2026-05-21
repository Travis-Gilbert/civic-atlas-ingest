from __future__ import annotations

import json
from datetime import date

from civic_atlas_ingest import training_corpus
from civic_atlas_ingest.coverage_quality import ProvenanceLane
from civic_atlas_ingest.training_corpus import make_training_record, write_training_batch


def test_training_record_contains_part_graph_and_archetype() -> None:
    record = make_training_record(
        source="overpass",
        source_id="way:1",
        city="flint",
        geometry={
            "type": "Polygon",
            "coordinates": [[[-83.1, 43.1], [-83.0, 43.1], [-83.0, 43.2], [-83.1, 43.1]]],
        },
        fields={
            "building": "commercial",
            "stories": 2,
            "primary_material": "brick",
            "roof_type": "flat",
        },
        lanes={
            "building": ProvenanceLane.OSM_TAGGED,
            "stories": ProvenanceLane.OSM_TAGGED,
            "primary_material": ProvenanceLane.OSM_TAGGED,
            "roof_type": ProvenanceLane.OSM_TAGGED,
        },
    )

    payload = record.to_json()

    assert payload["archetype_label"] == "commercial-brick-two-story"
    assert payload["coverage"]["coverage_quality"] == 0.7
    assert payload["part_labels"]["mass"]["story_count"] == 2
    assert any(node["kind"] == "reconstruction_part" for node in payload["training_graph"]["nodes"])


def test_write_training_batch_writes_content_hashed_manifest(tmp_path) -> None:
    record = make_training_record(
        source="assessor",
        source_id="parcel:1",
        city="flint",
        geometry={
            "type": "Polygon",
            "coordinates": [[[-83.1, 43.1], [-83.0, 43.1], [-83.0, 43.2], [-83.1, 43.1]]],
        },
        fields={"building": "parcel", "address": "500 S Saginaw St"},
        lanes={"building": ProvenanceLane.AUTHORITATIVE_RECENT},
    )

    result = write_training_batch(
        [record],
        source="assessor",
        output_uri=str(tmp_path),
        run_date=date(2026, 5, 21),
    )
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert result.record_count == 1
    assert result.jsonl_path.exists()
    assert manifest["content_hash"].startswith("sha256-")
    assert manifest["intended_uri"].endswith("/flint/assessor/2026-05-21")


def test_write_training_batch_uploads_manifest_after_writing(monkeypatch, tmp_path) -> None:
    record = make_training_record(
        source="overpass",
        source_id="way:2",
        city="flint",
        geometry={
            "type": "Polygon",
            "coordinates": [[[-83.1, 43.1], [-83.0, 43.1], [-83.0, 43.2], [-83.1, 43.1]]],
        },
        fields={"building": "commercial"},
        lanes={"building": ProvenanceLane.OSM_TAGGED},
    )
    seen_files: list[str] = []

    def fake_upload(local_dir, intended_uri):
        if intended_uri == "s3://civic-atlas/training/flint/overpass/2026-05-21":
            seen_files.extend(sorted(path.name for path in local_dir.iterdir() if path.is_file()))
            return intended_uri
        raise AssertionError(f"unexpected upload URI: {intended_uri}")

    monkeypatch.setenv("CIVIC_ATLAS_CORPUS_LOCAL_OUT", str(tmp_path))
    monkeypatch.setattr(training_corpus, "_upload_if_requested", fake_upload)

    result = write_training_batch(
        [record],
        source="overpass",
        run_date=date(2026, 5, 21),
    )
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert "manifest.json" in seen_files
    assert result.uploaded_uri == "s3://civic-atlas/training/flint/overpass/2026-05-21"
    assert manifest["uploaded_uri"] == result.uploaded_uri
