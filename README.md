# civic-atlas-ingest

Multi-city building corpus ingestion, Phase 6 building head training,
and Scene Foundry rendering for the Our Civic Atlas project. One repo
because the toolchain is shared (Python + Modal + Blender) and the
modules co-evolve.

## What lives here

| Subtree            | Purpose                                                          |
|--------------------|------------------------------------------------------------------|
| `modal/ingest_*`   | Phase 5: pull OSM / Sanborn / assessor data into corpus tenant   |
| `modal/building_head_*` | Phase 6: train + serve the building head GNN                |
| `modal/scene_foundry.py` | Phase 3: render ReconstructionSpec -> glTF via Blender     |
| `primitives/`      | 8 Blender geometry-nodes archetypes consumed by Scene Foundry    |
| `crates/civic-atlas-validate/` | Rust CLI checking corpus records vs ReconstructionSpec |

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
├── modal/                       # Python Modal apps
│   ├── city_targets.py          # 10 cities + bboxes, ordered priority
│   ├── coverage_quality.py      # per-record/per-field scoring
│   ├── ingest_overpass.py       # Phase 5
│   ├── ingest_sanborn.py        # Phase 5
│   ├── ingest_assessor.py       # Phase 5
│   ├── building_head_train.py   # Phase 6
│   ├── building_head_infer.py   # Phase 6
│   ├── model_promote.py         # Phase 6 promotion CLI
│   └── scene_foundry.py         # Phase 3 render service
├── primitives/                  # Blender geometry-nodes archetypes
│   ├── archetypes/
│   │   ├── commercial_brick_two_story/
│   │   ├── frame_house_with_porch/
│   │   ├── factory_bay/
│   │   ├── warehouse/
│   │   ├── church/
│   │   ├── school/
│   │   ├── gas_station/
│   │   └── mixed_use_storefront/
│   ├── scripts/                 # render_spec.py, hash_archetypes.py, cli.py
│   └── blender_addon/           # local-dev Blender addon
├── crates/
│   └── civic-atlas-validate/    # Rust validation CLI
├── scripts/
│   └── provision_corpus_tenant.sh
└── docs/
    ├── multi-tenancy-invariant.md
    └── spec-to-mesh-pipeline.md  # spec -> archetype -> Blender -> glTF
```

Python, Rust, and Blender Python live in the same repo because the
modules consume each other: scene_foundry reads `primitives/`, the
Rust validator reads the same BuildingPresence records ingesters
write, building_head_train consumes the corpus from ingesters.
Co-location prevents drift; toolchain coexists via pyproject.toml,
Cargo workspace, and Blender-addon discovery.

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
