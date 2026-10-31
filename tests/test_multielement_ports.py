"""Tests for multielement ports: several polygons on one port layer are the elements of one port.

Run: python -m pytest tests/test_multielement_ports.py
Needs the openEMS / CSXCAD Python bindings (util_simulation_setup imports them), numpy and pytest. No openEMS run:
the grouping of polygons into elements, the port combination (MultiElementPort), and how resonance estimation names,
reads and combines the element probe signals. The openEMS runs that check the physics (a line with its ports drawn
as one polygon or as two elements, same S-parameters) are described in the user's guide.
"""

import json
import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
pytest.importorskip("openEMS")
sys.path.insert(0, os.path.join(HERE, "..", "workflow"))

from gds2openEMS import util_resonance_estimation as resonance  # noqa: E402
from gds2openEMS.util_simulation_setup import MultiElementPort, port_element_groups  # noqa: E402


# ---------------------------------------------------------------- polygons -> elements

def test_separate_polygons_are_separate_elements():
    boxes = [(0, 1, 0, 7), (0, 1, 8, 15), (0, 1, 20, 25)]
    assert port_element_groups(boxes) == [[0], [1], [2]]


def test_touching_and_overlapping_polygons_are_one_element():
    # 0 and 1 share an edge, 2 overlaps 1 (so 0, 1, 2 are one element), 3 is separate
    boxes = [(0, 1, 0, 7), (0, 1, 7, 15), (0.5, 2, 14, 20), (0, 1, 30, 35)]
    assert port_element_groups(boxes) == [[0, 1, 2], [3]]


def test_order_follows_the_first_polygon_of_each_element():
    boxes = [(0, 1, 30, 35), (0, 1, 0, 7), (0, 1, 7, 15)]
    assert port_element_groups(boxes) == [[0], [1, 2]]


# ---------------------------------------------------------------- port combination

class FakeElement:
    """An element (openEMS LumpedPort) with given frequency domain voltage and current."""

    def __init__(self, u, i):
        self.u, self.i = np.asarray(u, complex), np.asarray(i, complex)

    def ReadUIData(self, sim_path, freq, signal_type='pulse'):
        self.uf_tot, self.if_tot = self.u, self.i


def test_matched_multielement_port_reflects_nothing():
    # two elements of 2*Z0 each, driven with V: each carries V/(2*Z0), together V/Z0 -> matched to Z0
    z0, v = 50.0, np.array([1.0, 0.5 + 0.5j])
    port = MultiElementPort([FakeElement(v, v / (2 * z0)), FakeElement(v, v / (2 * z0))], z0)
    port.CalcPort("", None, z0)
    assert np.allclose(port.uf_tot, v) and np.allclose(port.if_tot, v / z0)
    assert np.allclose(port.uf_ref, 0) and np.allclose(port.uf_inc, v)


def test_port_voltage_is_the_mean_and_current_the_sum():
    port = MultiElementPort([FakeElement([1.0], [0.01]), FakeElement([3.0], [0.03])], 50.0)
    port.CalcPort("", None)                       # reference impedance defaults to the port's Z0
    assert np.allclose(port.uf_tot, 2.0) and np.allclose(port.if_tot, 0.04) and port.Z_ref == 50.0
    # incident and reflected waves as in openEMS' Port.CalcPort
    assert np.allclose(port.uf_inc, 0.5 * (2.0 + 0.04 * 50)) and np.allclose(port.uf_ref, 2.0 - port.uf_inc)


# ---------------------------------------------------------------- resonance estimation

def test_probe_names_of_elements():
    assert resonance._probe_name((3, 'u')) == 'port_ut_3'
    assert resonance._probe_name((3, 'i', 2)) == 'e2_port_it_3'
    files = [os.path.basename(f) for _, f in resonance._probe_files("x", [1, 2], {2: 2})]
    assert files == ['port_ut_1', 'port_it_1', 'e1_port_ut_2', 'e1_port_it_2', 'e2_port_ut_2', 'e2_port_it_2']


def test_port_elements_from_port_information(tmp_path):
    ports = [{"portnumber": 1, "Z0": 50}, {"portnumber": 2, "Z0": 50, "element": 1},
             {"portnumber": 2, "Z0": 50, "element": 2}, {"portnumber": 2, "Z0": 50, "element": 3}]
    (tmp_path / "port_information.json").write_text(json.dumps({"ports": ports}))
    assert resonance.read_port_information(str(tmp_path)) == {1: 50, 2: 50}
    assert resonance.read_port_elements(str(tmp_path)) == {2: 3}


def test_element_signals_combine_like_the_port():
    t = np.arange(50) * 1e-13
    u1, u2 = np.sin(t * 1e12), 0.5 * np.sin(t * 1e12)
    i1, i2 = 0.01 * np.cos(t * 1e12), 0.02 * np.cos(t * 1e12)
    sig = {(1, 'u'): (t, u1), (1, 'i'): (t, i1),
           (2, 'u', 1): (t, u1), (2, 'u', 2): (t, u2), (2, 'i', 1): (t, i1), (2, 'i', 2): (t[:-1], i2[:-1])}
    combined = resonance.combine_elements(sig)
    assert set(combined) == {(1, 'u'), (1, 'i'), (2, 'u'), (2, 'i')}
    assert np.allclose(combined[(2, 'u')][1], 0.5 * (u1 + u2))
    assert np.allclose(combined[(2, 'i')][1], (i1 + i2)[:-1])        # shortest record of the elements
    # the S-parameter column from the element signals equals the one from the combined signals
    z0, freqs = {1: 50.0, 2: 50.0}, np.linspace(1e9, 1e11, 7)
    band = np.ones(len(freqs), bool)
    trimmed = resonance.truncate(sig, 49)
    assert np.allclose(resonance._column(trimmed, 1, z0, freqs, band),
                       resonance._column(resonance.combine_elements(trimmed), 1, z0, freqs, band))
