# Training Corpus Ingestion

XRL-B-002 now has a local, typed corpus output contract before the backend
write path is switched on.

## Output Shape

Each source task writes:

- `records.jsonl`: one `civic-atlas-training-corpus/v1` record per source object.
- `manifest.json`: source, tenant, run date, content hash, and intended S3 URI.
- `records.parquet`: written when the optional `corpus` dependency group installs
  `pyarrow`.

Default intended URI:

```bash
s3://civic-atlas/training/flint/<source>/<date>/
```

Local smoke output defaults to `artifacts/training/flint/<source>/<date>/`.
Set `CIVIC_ATLAS_ENABLE_S3_UPLOAD=1` to upload the batch directory with `boto3`.

## Sources

- `ingest_overpass.py`: pulls real Overpass building footprints/tags or accepts a
  JSON fixture with `--fixture-json`.
- `ingest_assessor.py`: samples the public Flint Property Portal/Regrid tilejson
  source and emits parcel-backed training records with owner fields stripped from
  training labels and the persisted debug envelope.
- `ingest_sanborn.py`: fetches Mapwarper map metadata and writes review-required
  sheet anchors. Building polygon vectorization remains a follow-up because it
  depends on the Sanborn color/OCR decoder.

All records carry an archetype label, per-part labels, coverage lanes, and a
small training graph (`building_presence -> reconstruction_part`) that the
Pairformer training lane can batch later.
