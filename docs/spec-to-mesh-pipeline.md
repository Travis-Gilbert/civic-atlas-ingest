# Spec → Mesh Pipeline

How a `ReconstructionSpec` row in PostGIS becomes a rendered glTF
asset that the public atlas loads.

## Steps

1. **Spec approved.** `civic-atlas-server::reconstruction::approve_spec`
   writes the new `reconstruction_specs` row (status=approved) and
   enqueues a `reconstruction_projection_outbox` row with
   `projection_kind='BuildingPresence'`.

2. **Outbox drained.** `civic-atlas-outbox-worker` picks up the row,
   logs the projection, and (when wired) calls the Theseus bridge to
   project to RustyRed. Worker also (Phase 3+) calls into the Scene
   Foundry Ray task.

3. **Scene Foundry Ray task** (`civic_atlas_ingest/scene_foundry.py`):
   - Looks up the archetype slug for this spec (from
     `spec.metadata.archetype_slug`)
   - Reads the archetype's `.blend` file from the synced `primitives/`
     directory on the RunPod Ray worker.
   - Runs Blender headless via:
     ```
     blender primitives/archetypes/<slug>/archetype.blend \
       --background \
       --python primitives/scripts/render_spec.py -- \
       --archetype <slug> \
       --spec spec.json \
       --out spec.glb
     ```
   - Uploads the result to S3 under
     `s3://civic-atlas/<tenant>/assets/<spec_id>/v<version>/<hash>.glb`
   - Writes a `generated_assets` row pointing at the S3 URI

   Because `primitives/` lives in this same repo, archetype changes ship with
   the Ray job working directory or with the RunPod image/mount used by the
   cluster config.

4. **Frontend fetch.** The atlas frontend's `/lost-flint/carriage-town`
   route lists 20 specs via GraphQL, reads each spec's
   `generated_assets[0].uri`, and feeds the URL to a `<ScenegraphLayer>`
   in deck.gl (or per-part R3F overlay) for rendering.

5. **Per-part confidence visualization.** The frontend shader reads
   `PartProvenance.confidence` from each part of the spec and mixes
   the GLB's mesh between "documented" (full opacity) and "porcelain
   inferred" (scattered noise). The math is in
   `Open-Flint-Atlas-main-release/src/components/atlas/AtlasLostFlintDeckLayer.ts`
   for the deck.gl path; the per-part R3F port lives in the
   `/lost-flint/carriage-town` route.

## Determinism

Two specs with identical field values produce identical GLB files
(modulo the GLB metadata's timestamp). The archetype's geometry-nodes
group is the only authored geometry; spec fields drive every
parameter. The hash check in `primitives/scripts/hash_archetypes.py`
makes mismatched archetype versions explicit.

## Why not generative AI mesh?

Because the goal is **inspectable, citable history**, not visual
plausibility. A spec with `mass.story_count=2` always produces a
two-story building. A generative model that sometimes produces 2,
sometimes 3 is failure: the public sees data the spec doesn't claim.

The building head from Phase 6 produces **prior fields**, which feed
into a spec, which produces a GLB through the same deterministic
archetype pipeline. The model never produces mesh directly.
