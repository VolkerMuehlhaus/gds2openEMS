"""Tests for the openEMS engine options of runSimulation(): settings['engine'], settings['gpu_device']
and the environment variable OPENEMS_ENGINE.

Run: python -m pytest tests/test_engine_options.py
Needs the openEMS / CSXCAD Python bindings (util_simulation_setup imports them) and pytest. No openEMS run:
whether the installed openEMS has the GPU engine and the gpu_device option is replaced by a stand-in.
"""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
pytest.importorskip("openEMS")
sys.path.insert(0, os.path.join(HERE, "..", "workflow"))

from gds2openEMS import util_simulation_setup as setup  # noqa: E402


@pytest.fixture
def openems(monkeypatch):
    """Stand-in for the installed openEMS: set .gpu_engine and .gpu_device_option (True/False/None)."""
    class Installed:
        gpu_engine = True
        gpu_device_option = True
        engine_variable = True
    monkeypatch.setattr(setup, "_openEMS_has_gpu_engine", lambda: Installed.gpu_engine)
    monkeypatch.setattr(setup, "_openEMS_has_gpu_device_option", lambda: Installed.gpu_device_option)
    monkeypatch.setattr(setup, "_openEMS_reads_engine_variable", lambda: Installed.engine_variable)
    monkeypatch.delenv("OPENEMS_ENGINE", raising=False)
    monkeypatch.setattr(setup, "_printed_once", set())
    return Installed


def test_nothing_set(openems):
    assert setup._engine_options(None, None) == ({}, None)


@pytest.mark.parametrize("engine", ["cpu", "gpu", "multithreaded"])
def test_engine_passed_as_it_is(openems, engine):
    assert setup._engine_options(engine, None) == ({"engine": engine}, engine)


def test_gpu_without_gpu_engine_warns(openems, capsys):
    openems.gpu_engine = False
    options, used = setup._engine_options("gpu", None)
    assert options == {"engine": "gpu"}
    assert "settings['engine'] = 'gpu': the installed openEMS has no GPU engine" in capsys.readouterr().out


def test_engine_from_environment(openems, monkeypatch, capsys):
    monkeypatch.setenv("OPENEMS_ENGINE", "gpu")
    options, used = setup._engine_options(None, None)
    assert options == {}                      # openEMS reads the variable itself
    assert used == "gpu (from OPENEMS_ENGINE)"
    openems.gpu_engine = False
    setup._engine_options(None, None)
    assert "OPENEMS_ENGINE = 'gpu': the installed openEMS has no GPU engine" in capsys.readouterr().out


def test_environment_ignored_by_older_openems(openems, monkeypatch, capsys):
    # e.g. the Windows test package v0.37.0-38-gd686f1d: GPU engine, but no OPENEMS_ENGINE
    openems.engine_variable = False
    monkeypatch.setenv("OPENEMS_ENGINE", "gpu")
    assert setup._engine_options(None, None) == ({}, None)   # the log must not claim the GPU engine
    assert "doesn't read this environment variable" in capsys.readouterr().out


def test_settings_engine_wins_over_environment(openems, monkeypatch):
    monkeypatch.setenv("OPENEMS_ENGINE", "gpu")
    assert setup._engine_options("cpu", None) == ({"engine": "cpu"}, "cpu")


@pytest.mark.parametrize("device", [0, 1, "1"])
def test_gpu_device_passed_as_int(openems, device):
    options, used = setup._engine_options("gpu", device)
    assert options == {"engine": "gpu", "gpu_device": int(device)}
    assert type(options["gpu_device"]) is int  # openEMS turns a 0/1 that is not an integer option into False/True
    assert used == "gpu, gpu_device=%d" % int(device)


@pytest.mark.parametrize("has_option", [True, None])   # None: can't be told, passed anyway
def test_gpu_device_passed_if_openems_may_have_it(openems, has_option):
    openems.gpu_device_option = has_option
    assert setup._engine_options("gpu", 1)[0]["gpu_device"] == 1


def test_gpu_device_not_passed_without_the_option(openems, capsys):
    openems.gpu_device_option = False
    options, used = setup._engine_options("gpu", 1)
    assert options == {"engine": "gpu"}
    assert used == "gpu"
    assert "no gpu_device option, the setting is ignored" in capsys.readouterr().out


def test_installed_openems_checks_run():
    # the real checks on the installed openEMS: True, False or None, never an exception
    assert setup._openEMS_has_gpu_engine() in (True, False, None)
    assert setup._openEMS_has_gpu_device_option() in (True, False, None)
    assert setup._openEMS_reads_engine_variable() in (True, False, None)
