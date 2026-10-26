# Test stand-in for the openEMS Python package: same strict signature as workflow_standins.api.
import json
import os
import sys

_FIXTURES = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _FIXTURES not in sys.path:
    sys.path.insert(0, _FIXTURES)

from workflow_standins.api import openEMS as _OpenEMSBase  # noqa: E402


def _record(kind, **values):
    path = os.environ.get("CONVERT_RECORD")
    if path:
        with open(path, "a") as f:
            f.write(json.dumps({"kind": kind, **values}, sort_keys=True) + "\n")


class openEMS(_OpenEMSBase):
    def __init__(self, EndCriteria=None):
        super().__init__(EndCriteria=EndCriteria)
        _record("openEMS", end=EndCriteria)

    def SetGaussExcite(self, f0, fc):
        _record("gauss", f0=f0, fc=fc)

    def SetBoundaryCond(self, bc):
        _record("boundary", bc=list(bc))
