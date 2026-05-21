# Multi-tenancy Invariant — `corpus` Tenant

The `corpus` tenant in `our-civic-atlas-backend` is a special tenant
that exists to feed Phase 6's building head training. It is **not**
a public-facing atlas tenant. The invariants below define exactly
how it differs from the Flint tenant (and any future per-city tenant).

## Hard rules

1. **`corpus` is read-only from the public side.**
   The public subdomain `corpus.ourcivicatlas.org` may exist for
   review/inspection, but no public route mutates it.

2. **`corpus` is writable only by the three Ray ingest tasks.**
   - `ingest_overpass`
   - `ingest_sanborn`
   - `ingest_assessor`

   Each carries a bearer token scoped to `tenant_id='corpus'` only.
   No other tenant's tokens can write here.

3. **Other tenants cannot read corpus data through public endpoints.**
   A Flint-tenant call to `ListPlaces` must never return a corpus
   row. PostGIS RLS enforces this. The training job is the **only**
   surface that reads across both — and it reads, not joins.

4. **Phase 6 training reads corpus + tenant data, but never joins them.**
   The training job calls:
   - `GetBatchSpacetimeEmbeddings(node_ids[])` against Theseus for
     all node IDs across all tenants, then
   - per-tenant data fetches separately,
   - assembles the training tensor in memory.

   At no point does a SQL query JOIN across `tenant_id` boundaries.

5. **Cross-tenant inference travels through the model, not the database.**
   The building head produces priors. Those priors are written into
   the **calling tenant's** spec. They are never written into the
   corpus tenant. The corpus tenant is upstream of training only.

## Why this matters

The corpus exists to give the building head morphology variance.
Detroit's brick four-flats, Buffalo's stoop two-flats, Cleveland's
double-deckers — these morphologies improve Flint priors when the
model sees them at training time. But Flint residents must not see
"a Detroit building rendered in Flint" as a visible artifact in
their atlas. The model's output is always re-grounded against
**Flint's** local evidence before it lands in Flint's spec.

## Probe to verify

Phase 5 gate includes a cross-tenant query probe. Implementation
target:

```bash
# Phase 5 gate: this MUST return 0 rows
psql "$FLINT_DSN" -c "
  SELECT COUNT(*) FROM building_presence
  WHERE tenant_id = 'flint'
    AND id IN (SELECT id FROM building_presence WHERE tenant_id = 'corpus');
"

# And this MUST return Unauthenticated:
grpcurl -d '{"tenant_context":{"tenant_id":"flint"}}' \
  -H 'authorization: Bearer $CORPUS_TOKEN' \
  atlas-backend:443 civic_atlas.v1.CivicAtlasService/ListPlaces
```

## Adding a new city

Each new city is its own tenant slug (e.g. `flint`, `detroit`).
The `corpus` tenant is provisioned **once** and accumulates
multi-city ingestion forever. Adding a city to the corpus does
**not** require adding it as a public tenant. The two are
orthogonal:

| Use case                  | New public tenant? | Add to corpus? |
|---------------------------|--------------------|----------------|
| Public Atlas for new city | yes                | yes            |
| Training data only        | no                 | yes            |
| Sister city of a public   | no                 | yes            |
| Demo city                 | yes                | no             |

## Cross-references

- `our-civic-atlas-backend/migrations/0001_tenants_rls.sql` — RLS policy
- `our-civic-atlas-backend/docs/orchestrate/phases-0-3-task-ledger.md` — Phase 0-3 plan
- `Open-Flint-Atlas-main-release/docs/notes/session-2026-05-18-codex-handoff-phases-0-3.open.md` — frontend's mirror
