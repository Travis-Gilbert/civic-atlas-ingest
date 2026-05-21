from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

PRIMITIVES_ROOT = Path(__file__).resolve().parents[1] / "primitives"
sys.path.insert(0, str(PRIMITIVES_ROOT))

ARCHETYPES = importlib.import_module("archetypes").ARCHETYPES
validate_manifest = importlib.import_module("archetypes._manifest_schema").validate
make_ifc_text = importlib.import_module("openbim").make_ifc_text


def test_all_archetype_manifests_validate() -> None:
    assert len(ARCHETYPES) == 8
    for manifest in ARCHETYPES.values():
        validate_manifest(manifest)


def test_openbim_sidecar_contains_ifc4_and_parts() -> None:
    spec = {
        "spec_id": "spec:carriage-town:sample",
        "display_name": "Sample Storefront",
        "mass": {"height": {"max": 28}, "width": {"max": 32}, "depth": {"max": 70}},
        "facades": [{"material": "brick"}],
        "roof": {"form": "flat", "material": "built-up"},
        "ground_floor": {"use_type": "retail"},
    }

    ifc = make_ifc_text(archetype="commercial-brick-two-story", spec=spec)

    assert "FILE_SCHEMA(('IFC4'))" in ifc
    assert "IFCBUILDINGELEMENTPROXY" in ifc
    assert "facade_0" in ifc
    assert json.dumps({"form": "flat", "material": "built-up"}, sort_keys=True) in ifc
