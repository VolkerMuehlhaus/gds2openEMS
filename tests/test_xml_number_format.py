"""The model files are written with decimal points also when the program has set a locale with decimal commas.

openEMS and CSXCAD write the numbers of their XML files in the C library's number format. Qt sets it from LANG when
a QApplication is created (in the test run: tests/test_convert2settings.py), and with LANG=de_DE the model file had
endCriteria="0,0001", which the openEMS binary does not read as the number; test_full_xml failed after that test.

Run: python -m pytest tests/test_xml_number_format.py
"""

import locale
import xml.etree.ElementTree as ET

import pytest

pytest.importorskip("openEMS")
from test_full_xml import ENERGY_LIMIT, set_up_line  # noqa: E402

COMMA_LOCALES = ("de_DE.UTF-8", "de_DE.utf8", "fr_FR.UTF-8", "fr_FR.utf8", "nl_NL.UTF-8")


@pytest.fixture
def comma_locale():
    previous = locale.setlocale(locale.LC_NUMERIC)
    for name in COMMA_LOCALES:
        try:
            locale.setlocale(locale.LC_NUMERIC, name)
            break
        except locale.Error:
            continue
    else:
        pytest.skip("no locale with a decimal comma installed")
    assert locale.localeconv()["decimal_point"] == ","
    yield name
    locale.setlocale(locale.LC_NUMERIC, previous)


def test_model_file_has_decimal_points_with_a_comma_locale(tmp_path, monkeypatch, comma_locale):
    model_file, _ = set_up_line(tmp_path, monkeypatch, {'engine': 'cpu'})
    fdtd = ET.parse(model_file).getroot().find('FDTD')
    assert float(fdtd.get('endCriteria')) == pytest.approx(10 ** (ENERGY_LIMIT / 10))
    assert locale.setlocale(locale.LC_NUMERIC) == comma_locale, "the program's locale is set again after writing"
