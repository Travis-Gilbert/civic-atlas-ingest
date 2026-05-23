# Sanborn Color Key

Reference for `civic_atlas_ingest.sanborn_color_decoder.DEFAULT_BANDS`.

Sanborn Fire Insurance maps use a standardized color key to encode
each building's construction material. The colors are reasonably
stable across the company's century-long production run, but paper
aging, scanner gamma, and digitization noise mean the codec can't
work in RGB — HSV thresholds with hand-tuned bands per material are
the robust path.

## Material codes

| Sanborn color   | Material               | MaterialCode value |
|-----------------|------------------------|--------------------|
| Yellow          | Wood frame (combustible) | `WOOD_FRAME = 1` |
| Pink / red      | Brick                  | `BRICK = 2`        |
| Blue            | Stone                  | `STONE = 3`        |
| Gray            | Iron / steel           | `IRON = 4`         |
| Brown           | Adobe / mud            | `ADOBE = 5`        |
| Olive (rare)    | Special combustible    | `SPECIAL_COMBUSTIBLE = 6` |
| Black           | Labels, lot lines, story digits | `LABEL = 7` |
| White / cream   | Paper background       | `BACKGROUND = 0`   |

The pink-vs-red distinction is a print-run artifact, not a semantic
one. Both map to `BRICK`. Older Sanborn sheets (pre-1900) tend
toward saturated red; later sheets shift toward pink as ink quality
improved.

## Story counts

Story counts are printed as small digits *inside* each building
polygon — "1", "2", "1½", "2½", "3", etc. The vectorizer reads them
via `sanborn_vectorize.extract_story_count`, which uses Tesseract by
default. Half-stories are coerced down to the integer floor for v0.1;
v0.2 can carry the fractional value through to `mass.story_count`
when the corpus is rich enough to train against the distinction.

## Ground-floor use notations

Beyond color, Sanborn sheets carry letter abbreviations inside
polygons indicating ground-floor use:

- `D` = dwelling (residential)
- `S` = store (commercial retail)
- `W` = warehouse
- `F` = factory
- `O` = office
- `Tenement`, `Boarding`, `Stable` (spelled out)

These are not yet decoded in v0.1 — they live in the LABEL pixels
that `extract_polygons` deliberately drops. v0.2 work: a separate
OCR pass over LABEL-classified regions to extract these letters
and merge them into `fields["use_type"]`.

## Cross-hatching for special materials

A small minority of Sanborn polygons carry diagonal cross-hatching
to indicate concrete or reinforced construction. v0.1 misclassifies
these as IRON (the underlying gray of the hatch lines) or
BACKGROUND (the paper between the hatches). v0.2: detect the regular
periodicity of the hatching via Fourier analysis or a Hough
transform.

## Sheet preparation for ingest

Each sheet needs a georef JSON (see `sanborn_georef.py`). Two
formats are supported:

### bbox

For sheets that are already axis-aligned (north up, no rotation),
a four-coordinate bounding box is enough:

```json
{
  "image_path": "sanborn_flint_1925_sheet_03.tif",
  "sheet_id": "flint-1925-03",
  "year": 1925,
  "source": "library_of_congress",
  "source_uri": "https://www.loc.gov/item/...",
  "format": "bbox",
  "bbox": {
    "north": 43.0148, "south": 43.0102,
    "east": -83.6911, "west": -83.6982
  }
}
```

### control_points

For sheets with rotation or skew, register 4+ ground control points
(spread across the sheet, not clustered in one corner):

```json
{
  "image_path": "sanborn_flint_1899_sheet_12.tif",
  "sheet_id": "flint-1899-12",
  "year": 1899,
  "source": "umich_flint_gis_center",
  "format": "control_points",
  "control_points": [
    [120, 80, -83.6982, 43.0148],
    [4830, 80, -83.6911, 43.0148],
    [120, 6240, -83.6982, 43.0102],
    [4830, 6240, -83.6911, 43.0102]
  ]
}
```

Each control point is `[pixel_x, pixel_y, lng, lat]`. The fit is
least-squares affine; 4 well-spread points yield sub-meter accuracy
on a 1:600 Sanborn scale.

## Provenance ceiling

Every field decoded from a Sanborn sheet is tagged
`ProvenanceLane.PRIMARY_ARCHIVAL`. This is the highest provenance
lane available in the corpus — Sanborn maps are *the* canonical
source for pre-1950 Rust Belt building inventory. The atlas's
confidence-quality system caps Sanborn-derived fields at this
ceiling; no later inference can boost them above PRIMARY_ARCHIVAL,
only weaken them with conflicting evidence.

## Calibration

`DEFAULT_BANDS` is tuned against Library of Congress Flint sheets
from 1899, 1925, 1929. Other cities or other Sanborn print runs
may need calibration. Pattern: capture the actual color of a
known-material polygon (e.g. a downtown brick commercial that
you can verify from a contemporary photo), then bump the
matching band's thresholds. Per-sheet overrides can move into
the sheet's georeferencing JSON in a future revision.
