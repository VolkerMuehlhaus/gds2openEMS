"""Tests for gds_reader.read_gds(): each GDS layer number is read once.

Run: python -m pytest tests/test_gds_reader_layers.py
Needs gdspy, numpy and pytest. The SG13G2 stackups use GDS layer 36 for two stackup layers (MIM and MIM_DK): one
drawn MIM shape makes the top plate and the dielectric below it. read_gds() read the layer once per stackup layer,
so every MIM polygon came out twice (and openEMS warned about unused duplicate primitives).
"""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
gdspy = pytest.importorskip("gdspy")
sys.path.insert(0, os.path.join(HERE, "..", "workflow"))

from gds2openEMS import util_gds_reader as gds_reader  # noqa: E402
from gds2openEMS import util_stackup_reader as stackup_reader  # noqa: E402

STACKUP = os.path.join(HERE, "..", "workflow", "SG13G2_nosub.xml")


@pytest.fixture
def layout(tmp_path):
    lib = gdspy.GdsLibrary()
    cell = lib.new_cell("TOP_" + tmp_path.name)       # gdspy keeps cell names globally: one per test
    cell.add(gdspy.Rectangle((0, 0), (10, 10), layer=36))      # two MIM shapes
    cell.add(gdspy.Rectangle((20, 0), (30, 10), layer=36))
    cell.add(gdspy.Rectangle((-5, -5), (35, 15), layer=8))     # Metal1 below
    path = str(tmp_path / "mim.gds")
    lib.write_gds(path)
    return path


def test_stackup_uses_layer_36_twice():
    _, _, metals_list = stackup_reader.read_substrate(STACKUP)
    assert metals_list.getlayernumbers().count(36) == 2
    assert {m.name for m in metals_list.getallbylayernumber(36)} == {"MIM", "MIM_DK"}


def test_each_layer_is_read_once(layout):
    _, _, metals_list = stackup_reader.read_substrate(STACKUP)
    layerlist = metals_list.getlayernumbers()
    before = list(layerlist)
    polygons = gds_reader.read_gds(layout, layerlist, purposelist=[0], metals_list=metals_list)
    assert sum(1 for p in polygons.polygons if p.layernum == 36) == 2
    assert sum(1 for p in polygons.polygons if p.layernum == 8) == 1
    assert layerlist == before                     # the caller's list is not changed


def test_boundary_layers_are_read_without_changing_the_list(layout):
    _, _, metals_list = stackup_reader.read_substrate(STACKUP)
    layerlist = [36, 36]
    polygons = gds_reader.read_gds(layout, layerlist, purposelist=[0], metals_list=metals_list,
                                   gds_boundary_layers=[8, 36])
    assert sum(1 for p in polygons.polygons if p.layernum == 36) == 2
    assert sum(1 for p in polygons.polygons if p.layernum == 8) == 1
    assert layerlist == [36, 36]
