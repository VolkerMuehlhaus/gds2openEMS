# Test stand-in for gds2openEMS util_stackup_reader.py.
import json
import os


class _Materials:
    eps_max = 11.9


def read_substrate(XML_filename, variable_overrides=None):
    path = os.environ.get("CONVERT_RECORD")
    if path:
        with open(path, "a") as f:
            f.write(json.dumps({"kind": "read_substrate", "file": XML_filename,
                                "overrides": variable_overrides}) + "\n")
    return _Materials(), object(), _Metals()


class _Metals:
    def getlayernumbers(self):
        return [8, 10, 126, 134]
