"""Tests for port meshing and for S-parameters of ports with different reference impedances.

Run: python -m pytest tests/test_port_meshing.py
Needs the openEMS / CSXCAD Python bindings, numpy and pytest. No openEMS run.
- A lumped port acts only on the mesh edges inside its box. A zero-width via port whose plane is not a mesh line, or a
  port box between two mesh lines, excites nothing: its probes stay 0 and the run never reaches energy_limit.
  util_meshlines.add_port_mesh_lines() adds the missing line.
- With different port_Z0, S_ij is a ratio of power waves (utilities.power_wave_ratio) and the Touchstone file is
  version 2.0 with a [Reference] line.
"""

import os
import sys
import tempfile

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
pytest.importorskip("openEMS")
sys.path.insert(0, os.path.join(HERE, "..", "workflow"))

from CSXCAD import ContinuousStructure  # noqa: E402

from gds2openEMS import util_utilities as utilities  # noqa: E402
from gds2openEMS.util_gds_reader import gds_polygon  # noqa: E402
from gds2openEMS.util_meshlines import add_port_mesh_lines  # noqa: E402
from gds2openEMS.util_simulation_setup import all_simulation_ports, simulation_port  # noqa: E402


class Polygons:
    def __init__(self, polygons):
        self.polygons = polygons


def polygon(layernum, xs, ys, is_port=True):
    p = gds_polygon(layernum)
    for x, y in zip(xs, ys):
        p.add_vertex(x, y)
    p.process_pts()
    p.is_port = is_port
    return p


def line_y(layernum, y, x0, x1):
    """Zero-width via port: a horizontal line at y (zero extent in y)."""
    return polygon(layernum, [x0, x1], [y, y])


# ---------------------------------------------------------------- mesh line inside every port

def grid(x, y):
    mesh = ContinuousStructure().GetGrid()
    mesh.SetDeltaUnit(1e-6)
    mesh.AddLine('x', x)
    mesh.AddLine('y', y)
    mesh.AddLine('z', [0, 1])
    return mesh


def test_port_between_mesh_lines_gets_a_line_at_its_center():
    # the cascode's rsil port: 0.5 x 0.46, the nearest y lines 5.418 and 6.215 outside it
    mesh = grid([-25, -24.395, -23.895, -23], [5.418, 6.215])
    p = polygon(208, [-24.395, -23.895, -23.895, -24.395], [5.61, 5.61, 6.07, 6.07])
    mesh, added = add_port_mesh_lines(mesh, Polygons([p]))
    assert added == 1
    assert np.any(np.isclose(mesh.GetLines('y'), 5.84))


def test_zero_width_port_gets_a_line_in_its_plane():
    mesh = grid([0, 1, 2], [0, 1, 2])
    p = line_y(201, 1.55, 0.2, 1.8)
    mesh, added = add_port_mesh_lines(mesh, Polygons([p]))
    assert added == 1
    assert np.any(np.isclose(mesh.GetLines('y'), 1.55))


def test_ports_with_lines_and_other_polygons_are_left_alone():
    mesh = grid([0, 1, 2, 3], [0, 1, 2, 3])
    port = polygon(201, [0.5, 1.5, 1.5, 0.5], [0.5, 0.5, 1.5, 1.5])     # contains x=1 and y=1
    metal = polygon(8, [0.2, 0.3, 0.3, 0.2], [0.2, 0.2, 0.3, 0.3], is_port=False)
    before = (list(mesh.GetLines('x')), list(mesh.GetLines('y')))
    mesh, added = add_port_mesh_lines(mesh, Polygons([port, metal]))
    assert added == 0
    assert (list(mesh.GetLines('x')), list(mesh.GetLines('y'))) == before


# ---------------------------------------------------------------- ports with different reference impedances

def waves(u, i, z0):
    """Incident and reflected voltage wave as openEMS Port.CalcPort() computes them."""
    inc = 0.5 * (u + i * z0)
    return inc, u - inc


def thru(z_source, z_load):
    """Ideal connection between a driven port (z_source) and a terminated one (z_load), source voltage 1:
    (u, i) at the driven port and at the other port, currents flowing into the network."""
    current = 1.0 / (z_source + z_load)
    u = z_load * current
    return (u, current), (u, -current)


def test_mixed_impedance_s_parameters_are_power_wave_ratios():
    # ideal through connection between a 50 ohm and a 25 ohm port: S21 = S12 = 2*sqrt(50*25)/75 = 0.943
    (u1, i1), (u2, i2) = thru(50.0, 25.0)       # port 1 driven
    inc1, _ = waves(u1, i1, 50.0)
    _, ref2 = waves(u2, i2, 25.0)
    (v2, j2), (v1, j1) = thru(25.0, 50.0)       # port 2 driven
    inc2, _ = waves(v2, j2, 25.0)
    _, ref1 = waves(v1, j1, 50.0)
    s21 = utilities.power_wave_ratio(ref2, inc1, 25.0, 50.0)
    s12 = utilities.power_wave_ratio(ref1, inc2, 50.0, 25.0)
    expected = 2 * (50.0 * 25.0) ** 0.5 / 75.0
    assert abs(s21 - expected) < 1e-12 and abs(s12 - expected) < 1e-12
    assert abs(ref2 / inc1 - expected) > 0.2        # the plain voltage ratio is wrong here


def test_equal_impedances_give_the_plain_voltage_ratio():
    assert utilities.power_wave_ratio(0.3 + 0.1j, 0.5, 50.0, 50.0) == (0.3 + 0.1j) / 0.5


def ports(*impedances):
    p = all_simulation_ports()
    for n, z0 in enumerate(impedances, start=1):
        p.add_port(simulation_port(portnumber=n, voltage=1, port_Z0=z0, source_layernum=200 + n,
                                   from_layername='Metal1', to_layername='TopMetal2', direction='z'))
    return p


def test_reference_impedance_is_one_value_or_one_per_port():
    assert ports(50, 50, 50).get_reference_impedance() == 50
    assert ports(50, 25, 75).get_reference_impedance() == [50, 25, 75]


def snp(tmp, smatrix, z0):
    f = np.array([1e9, 2e9])
    path = tmp + ("/t.s%dp" % len(smatrix))
    utilities.write_snp(smatrix, f, path, z0=z0)
    return open(path).read(), path


def test_one_impedance_writes_touchstone_1():
    tmp = tempfile.mkdtemp()
    s = np.empty((2, 2, 2), dtype=object)
    for a in range(2):
        for b in range(2):
            for k in range(2):
                s[a, b, k] = complex(0.1 * (a + 1), 0.01 * (b + 1))
    text, _ = snp(tmp, s, 50)
    assert text.startswith('#   Hz   S  RI   R   50\n') and '[Version]' not in text
    text_list, _ = snp(tmp, s, [50, 50])                    # a list of equal values is the same file
    assert text_list == text


def test_different_impedances_write_touchstone_2_with_reference():
    tmp = tempfile.mkdtemp()
    s = np.empty((3, 3, 2), dtype=object)
    for a in range(3):
        for b in range(3):
            for k in range(2):
                s[a, b, k] = complex(0.1 * (a + 1) + 0.01 * k, 0.01 * (b + 1))
    text, path = snp(tmp, s, [50, 25, 75])
    assert text.startswith('[Version] 2.0\n')
    assert '[Number of Ports] 3\n' in text and '[Reference] 50 25 75\n' in text
    assert '[Number of Frequencies] 2\n' in text and text.rstrip().endswith('[End]')
    try:
        import skrf
    except ImportError:
        return
    net = skrf.Network(path)
    assert np.allclose(net.z0[0].real, [50, 25, 75])
    assert np.allclose(net.s[1], np.array([[s[a, b, 1] for b in range(3)] for a in range(3)], dtype=complex))
