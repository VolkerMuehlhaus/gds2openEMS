# Test stand-in for gds2openEMS util_utilities.py.
import os


def get_script_path(filename):
    return os.path.dirname(os.path.abspath(filename))


def get_basename(filename):
    return os.path.splitext(os.path.basename(filename))[0]


def create_sim_path(script_path, model_basename, dirname="output"):
    return os.path.join(script_path, dirname, model_basename + "_data")
