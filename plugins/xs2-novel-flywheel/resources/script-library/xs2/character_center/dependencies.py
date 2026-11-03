"""Load sibling resources when this service is imported by the script runner."""
from functools import lru_cache
import importlib.util
from pathlib import Path


@lru_cache
def sibling(name):
    path = Path(__file__).resolve().parent.parent / name / (name + '.py')
    spec = importlib.util.spec_from_file_location('character_center_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
