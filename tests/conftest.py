from importlib.util import find_spec, module_from_spec, spec_from_file_location
from pathlib import Path
import sys


if find_spec("backend") is None:
    package_directory = Path(__file__).resolve().parents[1]
    package_spec = spec_from_file_location(
        "backend",
        package_directory / "__init__.py",
        submodule_search_locations=[str(package_directory)],
    )
    if package_spec is None or package_spec.loader is None:
        raise ImportError(f"Could not load backend package from {package_directory}")
    package = module_from_spec(package_spec)
    sys.modules["backend"] = package
    package_spec.loader.exec_module(package)
