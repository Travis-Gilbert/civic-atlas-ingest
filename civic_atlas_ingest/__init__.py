"""civic-atlas-ingest: Ray task package.

The three ingest tasks in this package each pull from one source lane:
- ingest_overpass: OpenStreetMap building tags via Overpass API
- ingest_sanborn:  Mapwarper-georeferenced Sanborn fire insurance sheets
- ingest_assessor: per-city assessor parcel records

All three emit typed, content-hashed corpus batches for tenant_id='corpus'.
Backend writes and S3 upload are explicit follow-up switches rather than
implicit local side effects.
"""

__version__ = "0.1.0"
