"""Tests for gds2openEMS.convert2settings (command convert2settings).

Run: python -m pytest tests/test_convert2settings.py
Needs numpy and pytest. Each test converts a loose-variable model (fixtures/convert_loose) and runs
the original and the converted model against stand-in workflow modules that record what
setupSimulation / runSimulation / openEMS receive: both runs must record the same. The original
imports the stand-in modules folder, the converted model a stand-in gds2openEMS package made from
the same files (passed with --package-dir).

Ported from EMStudio tests/python/test_convert_loose.py.
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
FIXTURE = os.path.join(FIXTURES, "convert_loose")
FAKE_OPENEMS = os.path.join(FIXTURE, "fake_openems")
MODULE = "gds2openEMS.convert2settings"

pytest.importorskip("numpy")


def make_case(tmp_path, edit=None, old_modules=False, name="model.py"):
    """Copies the fixture model (optionally edited), its modules folder and a stand-in
    gds2openEMS package (tmp_path/pkg/gds2openEMS) into tmp_path."""
    if not (tmp_path / "modules").exists():
        shutil.copytree(os.path.join(FIXTURE, "modules"), tmp_path / "modules")
        if old_modules:
            # A 2024 modules copy: no settings= parameter in the workflow functions.
            p = tmp_path / "modules" / "util_simulation_setup.py"
            p.write_text(p.read_text().replace("settings", "options"))
        shutil.copytree(os.path.join(FIXTURE, "modules"), tmp_path / "pkg" / "gds2openEMS")
    with open(os.path.join(FIXTURE, "model_loose.py")) as f:
        text = f.read()
    if edit:
        text = edit(text)
    model = tmp_path / name
    model.write_text(text)
    return model


def pkg(tmp_path):
    return tmp_path / "pkg" / "gds2openEMS"


def convert(*args, package_dir):
    """Runs the converter with --json: (exit code, report or list of reports)."""
    cmd = [sys.executable, "-m", MODULE, *args, "--json", "--package-dir", str(package_dir)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode in (0, 1), r.stderr
    return r.returncode, json.loads(r.stdout)


def report(model, *extra, package_dir=None):
    _, r = convert(str(model), "--dry-run", *extra, package_dir=package_dir or pkg(model.parent))
    return r


def write(model, *extra, package_dir=None):
    out = model.with_name(model.stem + "_settings.py")
    _, r = convert(str(model), *extra, package_dir=package_dir or pkg(model.parent))
    return r, out


def run_model(model):
    record = model.parent / ("record_%s.jsonl" % model.stem)
    if record.exists():
        record.unlink()
    env = dict(os.environ, CONVERT_RECORD=str(record))
    # fixtures/ so fake_openems can import workflow_standins.api; pkg/ for the converted model
    env["PYTHONPATH"] = os.pathsep.join([FAKE_OPENEMS, FIXTURES, str(model.parent / "pkg")])
    r = subprocess.run([sys.executable, model.name], cwd=model.parent, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    rows = []
    for line in record.read_text().splitlines():
        row = json.loads(line)
        row.pop("fdtd", None)     # object ids differ between runs
        row.pop("ports", None)
        rows.append(row)
    return rows, r.stdout


def run_converted(model, converted):
    """Runs the converted text as the model file, so __file__-derived paths match."""
    original_text = model.read_text()
    model.write_text(converted.read_text())
    try:
        return run_model(model)
    finally:
        model.write_text(original_text)


def assert_same_behaviour(model, converted):
    orig_rows, orig_out = run_model(model)
    conv_rows, conv_out = run_converted(model, converted)
    assert orig_rows and conv_rows == orig_rows
    assert conv_out == orig_out


def by_name(entries):
    return {e["name"]: e for e in entries}


def test_plain_model_converts_like_recent_settings_models(tmp_path):
    model = make_case(tmp_path)
    before = model.read_bytes()
    r = report(model)
    assert r["ok"], r
    assert r["needs_import_switch"]
    assert r["removed_syspath_lines"] == [5]
    keys = {e["name"]: e["key"] for e in r["converted"]}
    assert keys == {
        "preview_only": "preview_only", "postprocess_only": "postprocess_only",
        "preprocess_gds": "preprocess_gds", "merge_polygon_size": "merge_polygon_size",
        "unit": "unit", "margin": "margin", "fstart": "fstart", "fstop": "fstop",
        "numfreq": "numfreq", "refined_cellsize": "refined_cellsize", "Boundaries": "Boundaries",
        "cells_per_wavelength": "cells_per_wavelength", "energy_limit": "energy_limit",
    }
    loose = by_name(r["loose"])
    assert set(loose) == {"gds_filename", "XML_filename"}
    assert "no settings key" in loose["gds_filename"]["reason"]
    assert r["dropped_formula_lines"]
    assert not (tmp_path / "model_settings.py").exists()      # dry run writes nothing

    # Side-by-side rows: every line of each side once, in order; 0 = filler row.
    rows = r["rows"]
    assert [x["l"] for x in rows if x["l"]] == list(range(1, len(r["original_lines"]) + 1))
    assert [x["r"] for x in rows if x["r"]] == list(range(1, len(r["converted_lines"]) + 1))
    margin = next(x for x in rows if x["r"] and
                  r["converted_lines"][x["r"] - 1].startswith("settings['margin']"))
    assert r["original_lines"][margin["l"] - 1].startswith("margin")
    assert margin["rs"] == [[0, 10], [16, 18]] and margin["ls"] == []   # settings[' and ']

    r, out = write(model)
    assert r["ok"], r
    assert r["written"] == str(out)
    assert model.read_bytes() == before
    text = out.read_text()
    assert "from gds2openEMS import util_simulation_setup as simulation_setup" in text
    assert "import modules." not in text
    assert "sys.path" not in text
    assert "simulation_setup.setupSimulation(FDTD=FDTD, settings=settings)" in text
    assert "simulation_setup.runSimulation(FDTD=FDTD, settings=settings)" in text
    assert "settings['cells_per_wavelength'] = 20" in text
    assert "settings['max_cellsize']" not in text
    assert "max_cellsize = " not in text
    assert "settings['excite_portnumbers'] = [port.portnumber]" in text
    assert "settings['engine']" not in text
    assert "# from the formula above" in text   # comment of a dropped argument line is kept
    assert "f'margin {settings[\"margin\"]} um, {settings[\"numfreq\"]} points'" in text
    assert "gds_reader.read_gds(gds_filename" in text
    assert_same_behaviour(model, out)


def test_existing_output_is_not_overwritten(tmp_path):
    model = make_case(tmp_path)
    out = tmp_path / "model_settings.py"
    out.write_text("keep me\n")
    code, r = convert(str(model), package_dir=pkg(tmp_path))
    assert code == 1
    assert not r["ok"] and "already exists" in r["reason"]
    assert out.read_text() == "keep me\n"


def test_other_syspath_lines_stay(tmp_path):
    model = make_case(tmp_path, lambda t: t.replace(
        "import modules.util_stackup_reader", "sys.path.append('/opt/other')\n"
        "import modules.util_stackup_reader", 1))
    r, out = write(model)
    assert r["ok"], r
    text = out.read_text()
    assert "sys.path.append('/opt/other')" in text
    assert "'modules'" not in text
    assert_same_behaviour(model, out)


def test_engine_gpu(tmp_path):
    model = make_case(tmp_path)
    p = pkg(tmp_path) / "util_simulation_setup.py"
    t = p.read_text()
    t = t.replace("numThreads=None,\n                   settings=None):",
                  "numThreads=None,\n                   engine=None,\n                   settings=None):")
    t = t.replace("numThreads         = settings.get('numThreads', 0)",
                  "numThreads         = settings.get('numThreads', 0)\n"
                  "            engine             = settings.get('engine', None)")
    t = t.replace("no_gui=no_gui,\n            numThreads=numThreads)",
                  "no_gui=no_gui,\n            numThreads=numThreads, engine=engine)")
    assert "engine=None," in t and "settings.get('engine', None)" in t and "engine=engine)" in t
    p.write_text(t)

    r, out = write(model, "--engine", "gpu")
    assert r["ok"], r
    assert r["engine"] == "gpu"
    lines = out.read_text().splitlines()
    i = next(n for n, l in enumerate(lines) if "settings['engine'] = 'gpu'" in l)
    assert lines[i].startswith("    ")                      # inside the loop, before runSimulation
    assert any("runSimulation(FDTD=FDTD, settings=settings)" in l for l in lines[i:i + 6])
    rows, _ = run_converted(model, out)
    runs = [row for row in rows if row["kind"] == "run"]
    assert runs and all(row["engine"] == "gpu" for row in runs)


def test_engine_needs_workflow_support(tmp_path):
    model = make_case(tmp_path)
    r = report(model, "--engine", "gpu")
    assert not r["ok"]
    assert "settings['engine']" in r["reason"]


def test_folder_input(tmp_path):
    make_case(tmp_path, name="a.py")
    make_case(tmp_path, name="b.py")
    (tmp_path / "c_settings.py").write_text("print('already converted')\n")
    code, reports = convert(str(tmp_path), package_dir=pkg(tmp_path))
    assert code == 0
    assert [os.path.basename(r["model"]) for r in reports] == ["a.py", "b.py"]
    assert all(r["ok"] for r in reports)
    assert (tmp_path / "a_settings.py").exists() and (tmp_path / "b_settings.py").exists()


def test_formula_form_b_is_dropped(tmp_path):
    model = make_case(tmp_path, lambda t: t.replace(
        "wavelength_air = 3e8/fstop / unit\nmax_cellsize = (wavelength_air)/(",
        "wavelength_air = 3e8/fstop\nmax_cellsize = wavelength_air / unit/("))
    r, out = write(model)
    assert r["ok"], r
    assert r["dropped_formula_lines"]
    assert_same_behaviour(model, out)


def test_formula_used_elsewhere_is_kept(tmp_path):
    model = make_case(tmp_path, lambda t: t.replace(
        "FDTD = openEMS(", "print('cell', max_cellsize)\nFDTD = openEMS("))
    r, out = write(model)
    assert r["ok"], r
    assert not r["dropped_formula_lines"]
    assert "cells_per_wavelength" in {e["name"] for e in r["converted"]}
    text = out.read_text()
    assert "wavelength_air = 3e8/settings['fstop'] / settings['unit']" in text
    assert "settings['max_cellsize']" not in text      # setupSimulation computes the same
    assert_same_behaviour(model, out)


def test_custom_formula_keeps_max_cellsize(tmp_path):
    model = make_case(tmp_path, lambda t: t.replace(
        "*cells_per_wavelength)", "*cells_per_wavelength*2)"))
    r, out = write(model)
    assert r["ok"], r
    assert "cells_per_wavelength" in by_name(r["loose"])
    text = out.read_text()
    assert "settings['max_cellsize'] = max_cellsize" in text
    assert "cells_per_wavelength = 20" in text
    assert_same_behaviour(model, out)


def test_num_freq_is_bound_by_linspace(tmp_path):
    model = make_case(tmp_path, lambda t: t.replace("numfreq", "num_freq"))
    r, out = write(model)
    assert r["ok"], r
    assert by_name(r["converted"])["num_freq"]["key"] == "numfreq"
    assert "settings['numfreq'] = 401" in out.read_text()
    assert_same_behaviour(model, out)


def test_variable_bound_in_function_stays_loose(tmp_path):
    model = make_case(tmp_path, lambda t: t.replace(
        "print(describe())", "def shift(margin):\n    return margin + 1\n\n\nprint(describe())"))
    r, out = write(model)
    assert r["ok"], r
    assert "more than once" in by_name(r["loose"])["margin"]["reason"]
    assert "settings['margin'] = margin" in out.read_text()
    assert_same_behaviour(model, out)


def test_reassigned_variable_stays_loose(tmp_path):
    model = make_case(tmp_path, lambda t: t + "numfreq = 201\n")
    r, out = write(model)
    assert r["ok"], r
    assert "numfreq" in by_name(r["loose"])
    assert_same_behaviour(model, out)


def test_existing_settings_name_is_refused(tmp_path):
    model = make_case(tmp_path, lambda t: t.replace("preview_only = True",
                                                    "settings = {}\npreview_only = True"))
    r = report(model)
    assert not r["ok"]
    assert "settings" in r["reason"]


def test_dynamic_name_access_is_refused(tmp_path):
    model = make_case(tmp_path, lambda t: t + "print(sorted(globals()))\n")
    r = report(model)
    assert not r["ok"]
    assert "globals" in r["reason"]


def test_append_of_run_simulation(tmp_path):
    model = make_case(tmp_path, lambda t: t.replace(
        "    simulation_setup.runSimulation  (", "    data_paths.append(simulation_setup.runSimulation  (")
        .replace("                                        postprocess_only)",
                 "                                        postprocess_only))")
        .replace("for port in simulation_ports.ports:", "data_paths = []\nfor port in simulation_ports.ports:")
        + "print(data_paths)\n")
    r, out = write(model)
    assert r["ok"], r
    assert "data_paths.append(simulation_setup.runSimulation(FDTD=FDTD, settings=settings))" \
        in out.read_text()
    assert_same_behaviour(model, out)


def test_old_modules_are_switched(tmp_path):
    model = make_case(tmp_path, old_modules=True)
    r, out = write(model)
    assert r["ok"], r
    assert r["needs_import_switch"]
    text = out.read_text()
    assert "from gds2openEMS import util_simulation_setup as simulation_setup" in text
    assert "import modules." not in text
    assert_same_behaviour(model, out)


def test_direct_util_imports_are_switched(tmp_path):
    model = make_case(tmp_path, lambda t: t.replace(
        "import modules.util_simulation_setup as simulation_setup",
        "import util_simulation_setup as simulation_setup").replace(
        "import modules.util_meshlines as util_meshlines", "import util_meshlines"),
        old_modules=True)
    r, out = write(model)
    assert r["ok"], r
    text = out.read_text()
    assert "from gds2openEMS import util_simulation_setup as simulation_setup" in text
    assert "from gds2openEMS import util_meshlines\n" in text
    assert_same_behaviour(model, out)


def test_missing_package_is_refused(tmp_path):
    model = make_case(tmp_path, old_modules=True)
    r = report(model, package_dir=tmp_path / "missing")
    assert not r["ok"]
    assert "not installed" in r["reason"]


def test_gui_preview_and_convert(tmp_path, monkeypatch):
    """The window shows the conversion, Convert writes <name>_settings.py once."""
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox
    from gds2openEMS import convert2settings_gui as gui

    model = make_case(tmp_path)
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    w = gui.ConvertWindow([str(model)], package_dir=str(pkg(tmp_path)))
    assert w.table.rowCount() == 15                    # 13 converted + 2 kept
    assert w.diff.change_starts and w.diff.position.text().startswith("Change 1 of")
    assert w.convert_button.isEnabled()

    w.gpu.setChecked(True)                             # stand-in workflow reads no engine key
    assert w.result is None and "can't be converted" in w.intro.text()
    w.gpu.setChecked(False)

    w._convert()
    out = tmp_path / "model_settings.py"
    assert out.exists() and not w.convert_button.isEnabled()
    w.load()                                           # existing output: Convert stays off
    assert not w.convert_button.isEnabled() and "already exists" in w.message.text()
    w.close()
    app.processEvents()
