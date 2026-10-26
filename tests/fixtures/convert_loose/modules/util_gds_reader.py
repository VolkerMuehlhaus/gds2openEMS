# Test stand-in for gds2openEMS util_gds_reader.py.
# Signature matches workflow_standins.api.read_gds (shared with golden_standins).
import json
import os


def read_gds(filename, layerlist, purposelist, metals_list, preprocess=False, merge_polygon_size=0,
             mirror=False, offset_x=0, offset_y=0, gds_boundary_layers=None, layernumber_offset=0,
             cellname="", derived_layers=None):
    if gds_boundary_layers is None:
        gds_boundary_layers = []
    path = os.environ.get("CONVERT_RECORD")
    if path:
        with open(path, "a") as f:
            f.write(json.dumps({"kind": "read_gds", "file": filename, "layers": layerlist,
                                "purpose": purposelist, "preprocess": preprocess,
                                "merge": merge_polygon_size, "cellname": cellname}) + "\n")
    return object()
