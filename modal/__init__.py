"""civic-atlas-ingest: Modal app package.

The three Modal apps in this package each pull from one source lane:
- ingest_overpass: OpenStreetMap building tags via Overpass API
- ingest_sanborn:  Mapwarper-georeferenced Sanborn fire insurance sheets
- ingest_assessor: per-city assessor parcel records

All three write only to tenant_id='corpus' in the Atlas backend's
PostGIS via gRPC. Tenant isolation is enforced server-side; this
package does not require any other tenant's credentials.
"""

__version__ = "0.1.0"
