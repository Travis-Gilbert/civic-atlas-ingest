# civic-atlas-ingest

Multi-city building corpus ingestion for the Our Civic Atlas project.

Three Modal apps pull from public sources and write
`BuildingPresence` + `ArtifactAnchor` records into the
`corpus` tenant in `our-civic-atlas-backend`'s PostGIS:

- `modal/ingest_overpass.py` — OpenStreetMap building footprints + tags
- `modal/ingest_sanborn.py` — Mapwarper-georeferenced Sanborn sheets
- `modal/ingest_assessor.py` — per-city assessor parcel records

A `civic-atlas-validate` Rust CLI checks ingested records against
`ReconstructionSpec` validators in the backend repo.

## Scope and non-goals

**In scope:**
- Bursty, reproducible ingestion of building morphology for 10 Rust-Belt
  cities, prioritized as listed in `modal/city_targets.py`.
- Field provenance and a per-field `coverage_quality` score (0-1)
  used by Phase 6's training job for loss weighting.
- Reproducibility: anyone running an Atlas instance can re-run.

**Out of scope:**
- Live-edit corpus surfaces. The corpus tenant is read-only from
  the public side.
- Mutation of any non-corpus tenant. The corpus tenant must not
  accidentally read or write into Flint, etc.
- Long-running Railway services. Ingestion is bursty Modal only.

## Architecture

```
Modal app (ingest_overpass | ingest_sanborn | ingest_assessor)
   |
   v  gRPC (over tonic-web)
our-civic-atlas-backend (Axum)  <-- writes only to tenant_id='corpus'
   |
   v  SQL
PostGIS (corpus schema, RLS-enforced)
```

## Repo layout

```
civic-atlas-ingest/
├── modal/                  # Python Modal apps
│   ├── city_targets.py     # 10 cities + bboxes, ordered priority
│   ├── coverage_quality.py # per-record/per-field scoring
│   ├── ingest_overpass.py
│   ├── ingest_sanborn.py
│   └── ingest_assessor.py
├── crates/
│   └── civic-atlas-validate/  # Rust validation CLI
├── scripts/
│   └── provision_corpus_tenant.sh
└── docs/
    └── multi-tenancy-invariant.md
```

Python and Rust live in the same repo because the Rust validator
reads the same `BuildingPresence` records the Python ingesters
write. Cargo workspace + pyproject.toml coexist.

## Dev setup

```bash
# Python (Modal)
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Rust (validator CLI)
cargo build -p civic-atlas-validate

# Provision the corpus tenant once (against an Atlas backend you can write to)
./scripts/provision_corpus_tenant.sh
```

## Invariants

- Modal apps **only** write to `tenant_id = 'corpus'`. Cross-tenant
  writes return `Unauthenticated`.
- Every record carries `coverage_quality` (0-1) reflecting which
  fields came from which source.
- Mapwarper is the default Sanborn imagery source. ProQuest is not
  required for reproducibility.
- Cross-references between corpus and tenant-private data (Flint,
  etc.) go through the building head inference path only, never
  direct joins.

See `docs/multi-tenancy-invariant.md` for the tenant isolation
invariant in full.

## Phase gate (before Phase 6 training)

- Each of the 10 target cities has ≥ 5,000 `BuildingPresence` nodes.
- Average populated-fields-per-record across the corpus ≥ 3.
- `civic-atlas validate corpus --city detroit` passes clean.
- Cross-tenant query probe: a Flint-tenant call to
  `ListPlaces` never returns corpus rows.
