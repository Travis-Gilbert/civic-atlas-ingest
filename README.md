# civic-atlas-ingest

Multi-city building corpus ingestion, Phase 6 building head training,
and Scene Foundry rendering for the Our Civic Atlas project. One repo
because the toolchain is shared (Python + Ray on RunPod + Blender) and
the modules co-evolve.

## What lives here

| Subtree            | Purpose                                                          |
|--------------------|------------------------------------------------------------------|
| `civic_atlas_ingest/ingest_*` | Phase 5: pull OSM / Sanborn / assessor data into typed corpus batches |
| `civic_atlas_ingest/building_head_*` | Phase 6: train + serve the civic Pairformer building head |
| `civic_atlas_ingest/scene_foundry.py` | Phase 3: render ReconstructionSpec -> glTF + IFC via Blender |
| `civic_atlas_ingest/zoning_sources.py` | Phase C: snapshot official zoning sources and parcel/zoning joins |
| `civic_atlas_ingest/zoning_ingest.py` | Phase C: transcribe current Flint zoning district rules |
| `civic_atlas_ingest/zoning_schema.py` | Phase C: typed zoning rule, boundary, and envelope seed records |
| `civic_atlas_ingest/envelope_edge_classifier.py` | Phase C: parcel edge classification from road-line snapshots |
| `civic_atlas_ingest/road_network_sources.py` | Phase C: snapshot OSM road lines through OSMnx for setback classification |
| `civic_atlas_ingest/envelope_compute.py` | Phase C: deterministic single-parcel envelope math |
| `civic_atlas_ingest/envelope_batch.py` | Phase C: batch current-scenario envelope rows and edge spot-checks |
| `primitives/`      | 8 Blender/procedural archetypes plus OpenBIM sidecar export      |
| `crates/civic-atlas-validate/` | Rust CLI checking corpus records vs ReconstructionSpec |

## Scope and non-goals

**In scope:**
- Bursty, reproducible ingestion of building morphology for 10 Rust-Belt
  cities, prioritized as listed in `civic_atlas_ingest/city_targets.py`.
- Field provenance and a per-field `coverage_quality` score (0-1)
  used by Phase 6's training job for loss weighting.
- Reproducibility: anyone running an Atlas instance can re-run.

**Out of scope:**
- Live-edit corpus surfaces. The corpus tenant is read-only from
  the public side.
- Mutation of any non-corpus tenant. The corpus tenant must not
  accidentally read or write into Flint, etc.
- Long-running Railway services. Ingestion, model training, inference, and
  Scene Foundry rendering run as Ray jobs or Ray Serve deployments on RunPod.

## Architecture

```
Ray task (ingest_overpass | ingest_sanborn | ingest_assessor)
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
├── civic_atlas_ingest/          # Python Ray tasks and Serve deployments
│   ├── city_targets.py          # 10 cities + bboxes, ordered priority
│   ├── coverage_quality.py      # per-record/per-field scoring
│   ├── ingest_overpass.py       # Phase 5
│   ├── ingest_sanborn.py        # Phase 5
│   ├── ingest_assessor.py       # Phase 5
│   ├── building_head_pairformer.py # Phase 6 model module
│   ├── building_head_train.py   # Phase 6 training app
│   ├── building_head_infer.py   # Phase 6 inference app
│   ├── model_promote.py         # Phase 6 promotion CLI
│   └── scene_foundry.py         # Phase 3 render service
├── ray_cluster/
│   └── runpod.yaml              # RunPod-targeted Ray cluster shape
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

The Phase 6 model code is local to this repo on purpose.
`building_head_pairformer.py` ports the reusable Theseus Pairformer
shape into a civic block-coherence model, while keeping Atlas
training, model promotion, and tenant isolation independent from
Theseus's epistemic graph runtime.

## Dev setup

```bash
# Python (Ray)
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Rust (validator CLI)
cargo build -p civic-atlas-validate

# Provision the corpus tenant once (against an Atlas backend you can write to)
./scripts/provision_corpus_tenant.sh
```

## Invariants

- Ray tasks **only** write to `tenant_id = 'corpus'`. Cross-tenant
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

## Ray / RunPod entrypoints

Batch lanes are Ray tasks:

```bash
ray job submit --working-dir . -- python -m civic_atlas_ingest.ingest_overpass detroit
ray job submit --working-dir . -- python -m civic_atlas_ingest.ingest_sanborn 12345
ray job submit --working-dir . -- python -m civic_atlas_ingest.ingest_assessor detroit
ray job submit --working-dir . -- python -m civic_atlas_ingest.building_head_train pretraining-2026-05-18 pretrain
```

Local smoke runs can use the built-in Ray fallback when Ray is not installed:

```bash
python3 -m civic_atlas_ingest.ingest_overpass flint --limit 25
python3 -m civic_atlas_ingest.ingest_assessor flint --limit 25
python3 -m civic_atlas_ingest.zoning_sources --output city_packs/flint/zoning/source-manifest.json
python3 -m civic_atlas_ingest.zoning_ingest --output city_packs/flint/zoning/rules-current.json
python3 -m civic_atlas_ingest.road_network_sources --output city_packs/flint/zoning/road-network-current.json
python3 -m civic_atlas_ingest.envelope_batch --limit 20 --no-assets
python3 -m primitives.scripts.cli export-ifc commercial-brick-two-story spec.json out.ifc
```

Inference is Ray Serve:

```bash
serve run civic_atlas_ingest.building_head_infer:building_head_app
```

RunPod node shape and setup commands live in `ray_cluster/runpod.yaml`.
