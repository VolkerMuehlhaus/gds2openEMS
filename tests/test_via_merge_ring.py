"""Via array merging keeps the whole merged via: a ring of vias around an opening (a guard ring) is merged into a ring
with its hole, not cut open. The shrink back after merging worked polygon by polygon, so the slit of the keyhole
polygon and the fracture lines widened and cut strips out of the via (gds2openEMS up to 0.7).

    python -m pytest tests/test_via_merge_ring.py
"""
import os
import sys

import numpy as np
import pytest
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "workflow"))
from gds2openEMS import util_gds_reader as reader  # noqa: E402


def via_ring(n, size=0.5, pitch=1.0):
    return [np.array([(i * pitch, j * pitch), (i * pitch + size, j * pitch),
                      (i * pitch + size, j * pitch + size), (i * pitch, j * pitch + size)])
            for i in range(n) for j in range(n) if i in (0, n - 1) or j in (0, n - 1)]


@pytest.mark.parametrize('n', [10, 120])     # 120: a ring of more than 199 vertices after merging, fractured
def test_ring_of_vias_merges_into_a_closed_ring(n):
    merged = unary_union([Polygon(p).buffer(0) for p in reader.merge_via_array(via_ring(n), 0.6)])
    side = (n - 1) + 0.5
    expected = box(0, 0, side, side) - box(0.5, 0.5, side - 0.5, side - 0.5)
    assert merged.symmetric_difference(expected).area < 1e-6
    assert merged.geom_type == 'Polygon' and len(merged.interiors) == 1


class _Derived:
    def __init__(self, layernum, operation, operands, oversize):
        self.layernum, self.operation, self.operands, self.oversize = layernum, operation, operands, oversize


class _DerivedList:
    def __init__(self, *derived):
        self.derived_layers = list(derived)

    def get_ordered(self):
        return self.derived_layers


def test_shrunk_derived_layer_keeps_its_hole():
    """a derived layer with a negative Oversize: a plate with a hole stays a plate with a larger hole"""
    plate = reader._fracture(reader.gdstk.boolean([box(0, 0, 10, 10).exterior.coords[:-1]],
                                                  [box(4, 4, 6, 6).exterior.coords[:-1]], 'not'))
    all_polygons = reader.all_polygons_list()
    reader.resolve_derived_layers({(8, 0): plate}, _DerivedList(_Derived(900, 'SIZE', [8], -1.0)), [900], [0], {},
                                  0, all_polygons)
    shape = unary_union([Polygon(zip(p.pts_x, p.pts_y)).buffer(0) for p in all_polygons.polygons])
    assert shape.area == pytest.approx(8 * 8 - 4 * 4)
    assert len(shape.interiors) == 1
