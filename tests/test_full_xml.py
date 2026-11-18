"""Tests for the model file of each excitation: the complete openEMS model, ready for the openEMS binary.

Run: python -m pytest tests/test_full_xml.py
Needs the openEMS / CSXCAD Python bindings, numpy and pytest. No openEMS run: the via port line of workflow/ is
set up with preview_only (the AppCSXCAD preview stubbed), and sub-1/<model>.xml is checked. If the openEMS binary is
next to AppCSXCAD, it also reads the file (--no-simulation).
"""

import hashlib
import locale
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
WORKFLOW = os.path.join(HERE, "..", "workflow")
pytest.importorskip("openEMS")
sys.path.insert(0, WORKFLOW)

from CSXCAD import AppCSXCAD_BIN  # noqa: E402
from openEMS import openEMS  # noqa: E402

from gds2openEMS import gds_reader, simulation_setup, stackup_reader  # noqa: E402

pytestmark = pytest.mark.skipif(not hasattr(openEMS, "Write2XML"), reason="openEMS before v0.37.0, no Write2XML")

ENERGY_LIMIT = -40
FSTOP = 110e9


def set_up_line(sim_path, monkeypatch, settings_extra=None):
    """the via port line of workflow/run_line_viaport.py, excitation 1, with preview_only; returns the
    model file and the FDTD object"""
    monkeypatch.setattr(simulation_setup.os, "system", lambda command: 0)   # no AppCSXCAD window
    settings = {'preview_only': True, 'unit': 1e-6, 'margin': 50, 'fstart': 0, 'fstop': FSTOP, 'numfreq': 401,
                'refined_cellsize': 1, 'cells_per_wavelength': 20, 'energy_limit': ENERGY_LIMIT,
                'Boundaries': ['PEC', 'PEC', 'PEC', 'PEC', 'PMC', 'MUR']}
    settings.update(settings_extra or {})
    ports = simulation_setup.all_simulation_ports()
    for n, layer in ((1, 201), (2, 202)):
        ports.add_port(simulation_setup.simulation_port(portnumber=n, voltage=1, port_Z0=50, source_layernum=layer,
                                                        from_layername='Metal1', to_layername='TopMetal2',
                                                        direction='z'))
    materials, dielectrics, metals = stackup_reader.read_substrate(
        os.path.join(WORKFLOW, "..", "XML_stackup", "legacy", "SG13G2_nosub.xml"))
    layers = metals.getlayernumbers() + ports.portlayers
    polygons = gds_reader.read_gds(os.path.join(WORKFLOW, "line_simple_viaport.gds"), layers, purposelist=[0],
                                   metals_list=metals)
    FDTD = openEMS(EndCriteria=np.exp(ENERGY_LIMIT / 10 * np.log(10)))
    FDTD.SetGaussExcite(FSTOP / 2, FSTOP / 2)
    FDTD.SetBoundaryCond(settings['Boundaries'])
    settings.update({'simulation_ports': ports, 'materials_list': materials, 'dielectrics_list': dielectrics,
                     'metals_list': metals, 'layernumbers': layers, 'allpolygons': polygons,
                     'sim_path': str(sim_path), 'model_basename': 'line', 'excite_portnumbers': [1]})
    simulation_setup.setupSimulation(FDTD=FDTD, settings=settings)
    excitation_path = simulation_setup.runSimulation(FDTD=FDTD, settings=settings)
    return os.path.join(excitation_path, 'line.xml'), FDTD


def test_model_file_is_the_complete_openems_model(tmp_path, monkeypatch, capsys):
    model_file, _ = set_up_line(tmp_path, monkeypatch, {'engine': 'cpu', 'numThreads': 4})
    root = ET.parse(model_file).getroot()
    assert root.tag == 'openEMS'
    fdtd = root.find('FDTD')
    assert float(fdtd.get('endCriteria')) == pytest.approx(10 ** (ENERGY_LIMIT / 10))
    excitation = fdtd.find('Excitation')
    assert float(excitation.get('f0')) == pytest.approx(FSTOP / 2) and float(excitation.get('fc')) == pytest.approx(FSTOP / 2)
    bc = fdtd.find('BoundaryCond')
    assert [bc.get(side) for side in ('xmin', 'xmax', 'ymin', 'ymax', 'zmin', 'zmax')] == \
        ['PEC', 'PEC', 'PEC', 'PEC', 'PMC', 'MUR']
    assert root.find('ContinuousStructure') is not None
    # the openEMS Python API reads it back
    assert openEMS().ReadFromXML(model_file)
    # the command line for this excitation, with the options that are not in the file
    out = capsys.readouterr().out
    assert 'openEMS command line: cd "' + os.path.dirname(model_file) + '" && openEMS line.xml --engine=cpu --numThreads=4 --verbose=1' in out


def test_command_line_without_engine_and_threads(tmp_path, monkeypatch, capsys):
    set_up_line(tmp_path, monkeypatch)
    line = [l for l in capsys.readouterr().out.splitlines() if l.startswith('openEMS command line:')]
    assert len(line) == 1 and line[0].endswith("&& openEMS line.xml --verbose=1")


def test_hash_is_the_hash_of_the_csx_alone(tmp_path, monkeypatch):
    # results of earlier versions (model file = CSX only) keep their hash, and are not simulated again
    model_file, FDTD = set_up_line(tmp_path, monkeypatch)
    excitation_path = os.path.dirname(model_file)
    csx_file = os.path.join(str(tmp_path), 'csx_only.xml')
    previous = locale.setlocale(locale.LC_NUMERIC)       # with decimal points, as without a locale set by Qt
    locale.setlocale(locale.LC_NUMERIC, 'C')
    try:
        FDTD.GetCSX().Write2XML(csx_file)
    finally:
        locale.setlocale(locale.LC_NUMERIC, previous)
    with open(csx_file, 'rb') as f:
        expected = hashlib.sha256(f.read()).hexdigest()
    assert simulation_setup._hash_of_CSX(FDTD.GetCSX(), excitation_path) == expected
    assert sorted(os.listdir(excitation_path)) == ['line.xml']   # the temporary file is removed


def test_openems_binary_reads_the_model_file(tmp_path, monkeypatch):
    binary = os.path.join(os.path.dirname(AppCSXCAD_BIN), 'openEMS' + ('.exe' if os.name == 'nt' else ''))
    if not os.path.isfile(binary):
        pytest.skip('no openEMS binary next to AppCSXCAD')
    model_file, _ = set_up_line(tmp_path, monkeypatch)
    result = subprocess.run([binary, os.path.basename(model_file), '--no-simulation'], cwd=os.path.dirname(model_file),
                            capture_output=True, text=True, timeout=300)
    # with --no-simulation openEMS returns 1 also after a complete setup: check its messages instead
    assert 'ParseFDTDSetup failed' not in result.stdout + result.stderr
    assert 'FDTD simulation size' in result.stdout and 'Excitation signal length' in result.stdout, \
        result.stdout + result.stderr
