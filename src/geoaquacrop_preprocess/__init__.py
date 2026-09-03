"""
geoaquacrop.preprocess: Automated data download and preprocessing pipeline
for running FAO AquaCrop over large regions in gridded format.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("geoaquacrop.preprocess")
except PackageNotFoundError:  # pragma: no cover - package not installed (e.g. running from source)
    __version__ = "0.0.0+unknown"

__all__ = ["run", "weather", "soil", "crop_calendar", "crop_area", "geoaquacrop_preprocess", "__version__"]

# Names re-exported lazily from .preprocess_main (PEP 562) so that `import
# geoaquacrop_preprocess` stays cheap and doesn't pull in the CDS/climate stack.
_LAZY_ATTRS = {"run", "weather", "soil", "crop_calendar", "crop_area", "geoaquacrop_preprocess"}


def __getattr__(name):
    if name in _LAZY_ATTRS:
        from . import preprocess_main
        return getattr(preprocess_main, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(__all__) | set(globals()))
