"""
Tests for geoaquacrop_preproc.validate_inputs.

Covers input validation logic without any network access.
"""

import os
import pytest

from geoaquacrop_preproc.validate_inputs import validate_inputs


# ---------------------------------------------------------------------------
# Valid inputs
# ---------------------------------------------------------------------------

def test_valid_polygon_passes(test_polygon_path):
    """A valid GeoJSON in EPSG:4326 with a future period should pass (NASA NEX path)."""
    # Use a future year range so the AgERA5 API token is not checked.
    validate_inputs(test_polygon_path, start_year=2030, end_year=2031, api_token="dummy")


def test_valid_polygon_agera5_path(test_polygon_path):
    """A valid GeoJSON with a past period (AgERA5 path) requires a token > 30 chars."""
    long_token = "a" * 40
    validate_inputs(test_polygon_path, start_year=2000, end_year=2008, api_token=long_token)


# ---------------------------------------------------------------------------
# File errors
# ---------------------------------------------------------------------------

def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        validate_inputs("/nonexistent/path/to/domain.geojson", 2030, 2031, "dummy")


def test_unreadable_file_raises(tmp_path):
    """A non-GeoDataFrame file should raise ValueError."""
    bad_file = tmp_path / "bad.geojson"
    bad_file.write_text("this is not valid geojson at all !!!")
    with pytest.raises((ValueError, Exception)):
        validate_inputs(str(bad_file), 2030, 2031, "dummy")


def test_non_polygon_geometry_raises(tmp_path):
    """A GeoJSON with Point geometry should raise ValueError."""
    point_geojson = tmp_path / "points.geojson"
    point_geojson.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature",'
        '"geometry":{"type":"Point","coordinates":[10.0,50.0]},'
        '"properties":{}}]}'
    )
    with pytest.raises(ValueError, match="Polygon"):
        validate_inputs(str(point_geojson), 2030, 2031, "dummy")


# ---------------------------------------------------------------------------
# Year validation
# ---------------------------------------------------------------------------

def test_start_year_greater_than_end_year_raises(test_polygon_path):
    with pytest.raises(ValueError, match="start_year"):
        validate_inputs(test_polygon_path, start_year=2025, end_year=2020, api_token="dummy")


def test_year_below_minimum_raises(test_polygon_path):
    with pytest.raises(ValueError):
        validate_inputs(test_polygon_path, start_year=1900, end_year=2000, api_token="dummy")


def test_year_above_maximum_raises(test_polygon_path):
    with pytest.raises(ValueError):
        validate_inputs(test_polygon_path, start_year=2050, end_year=2200, api_token="dummy")


def test_non_numeric_year_raises(test_polygon_path):
    with pytest.raises(TypeError):
        validate_inputs(test_polygon_path, start_year="2030", end_year=2031, api_token="dummy")


# ---------------------------------------------------------------------------
# API token validation (AgERA5 path only)
# ---------------------------------------------------------------------------

def test_short_api_token_raises_for_agera5(test_polygon_path):
    """Short token should raise ValueError when AgERA5 is selected."""
    with pytest.raises(ValueError, match="API token"):
        validate_inputs(test_polygon_path, start_year=2000, end_year=2008, api_token="short")


def test_non_string_api_token_raises_for_agera5(test_polygon_path):
    with pytest.raises(TypeError, match="API token"):
        validate_inputs(test_polygon_path, start_year=2000, end_year=2008, api_token=12345)
