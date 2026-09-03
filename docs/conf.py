"""Sphinx configuration for geoaquacrop-preprocess documentation."""
import importlib.metadata
import os
import sys

# Make the package importable when building docs without an editable install.
sys.path.insert(0, os.path.abspath("../src"))

# ---------------------------------------------------------------------------
# Project information
# ---------------------------------------------------------------------------
project = "geoaquacrop-preprocess"
author = "Josias Ritter"
copyright = "2026, Josias Ritter"

# Version is read from the installed package metadata, which is kept in sync
# with pyproject.toml.  When the package is not installed, fall back to the
# current development version.
#
# Versioned documentation
# -----------------------
# To publish per-release docs, tag commits with 'vX.Y.Z' in git and either:
#   - Use sphinx-multiversion (pip install sphinx-multiversion) to build
#     one HTML tree per tag/branch, or
#   - Host on Read the Docs, which handles versioning automatically via the
#     .readthedocs.yaml file at the repository root.
try:
    release = importlib.metadata.version("geoaquacrop-preprocess-dev")
except importlib.metadata.PackageNotFoundError:
    release = "0.1.0"
version = ".".join(release.split(".")[:2])  # short X.Y version shown in sidebar

# ---------------------------------------------------------------------------
# General configuration
# ---------------------------------------------------------------------------
extensions = [
    "sphinx.ext.autodoc",       # generate docs from docstrings
    "sphinx.ext.napoleon",      # parse Google-style docstrings
    "sphinx.ext.viewcode",      # add [source] links next to each member
    "sphinx.ext.intersphinx",   # cross-reference other projects' docs
    "sphinx.ext.autosummary",   # auto-generate summary tables
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# ---------------------------------------------------------------------------
# Autodoc
# ---------------------------------------------------------------------------
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
    "member-order": "bysource",
}
# Show type hints in the parameter description rather than in the signature
autodoc_typehints = "description"
autosummary_generate = True

# ---------------------------------------------------------------------------
# Napoleon (Google-style docstring support)
# ---------------------------------------------------------------------------
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = False
napoleon_include_private_with_doc = False
napoleon_use_rtype = True
napoleon_use_param = True

# ---------------------------------------------------------------------------
# Intersphinx: link to upstream API docs
# ---------------------------------------------------------------------------
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable", None),
    "xarray": ("https://docs.xarray.dev/en/stable", None),
    "pandas": ("https://pandas.pydata.org/docs", None),
    "geopandas": ("https://geopandas.org/en/stable", None),
}

# ---------------------------------------------------------------------------
# HTML output
# ---------------------------------------------------------------------------
html_theme = "furo"
html_static_path = ["_static"]
html_title = f"{project} {version}"
