import os
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

if __package__ != "backend":
    package_directory = Path(__file__).resolve().parent
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

from backend import create_app

app = create_app()


def run():
    app.run(
        debug=os.environ.get("FLASK_DEBUG", "true").lower() in {"1", "true", "yes", "on"},
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
    )


if __name__ == "__main__":
    run()
