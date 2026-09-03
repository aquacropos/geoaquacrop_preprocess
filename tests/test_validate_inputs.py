"""
Tests for geoaquacrop_preprocess.validate_inputs.

Covers input validation logic without any network access.
"""

import os
import pytest

from geoaquacrop_preprocess.validate_inputs import validate_inputs


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


# ---------------------------------------------------------------------------
# CRS validation (lines 49 and 53 in validate_inputs)
# ---------------------------------------------------------------------------

def test_wrong_crs_raises(tmp_path):
    """A vector file in a projected CRS (not EPSG:4326) should raise ValueError."""
    import geopandas as gpd
    from shapely.geometry import box

    gdf = gpd.GeoDataFrame(
        geometry=[box(500000, 5000000, 600000, 5100000)],
        crs="EPSG:32632",   # UTM Zone 32N — not WGS84
    )
    path = tmp_path / "wrong_crs.gpkg"
    gdf.to_file(str(path), driver="GPKG")

    with pytest.raises(ValueError, match="WGS84|EPSG:4326|CRS"):
        validate_inputs(str(path), 2030, 2031, "dummy")


def test_null_crs_raises(tmp_path):
    """A file whose CRS is None should raise ValueError."""
    import geopandas as gpd
    from shapely.geometry import box
    from unittest.mock import patch

    # Create a real file so os.path.exists passes
    dummy = tmp_path / "polygon.geojson"
    dummy.write_text('{"type":"FeatureCollection","features":[]}')

    gdf_no_crs = gpd.GeoDataFrame(geometry=[box(5, 5, 10, 10)])
    # CRS is None by default when not set

    with patch("geoaquacrop_preprocess.validate_inputs.gpd.read_file", return_value=gdf_no_crs):
        with pytest.raises(ValueError, match="CRS"):
            validate_inputs(str(dummy), 2030, 2031, "dummy")


# ---------------------------------------------------------------------------
# Small AOI warning (lines 66-68)
# ---------------------------------------------------------------------------

def test_small_aoi_triggers_warning(tmp_path, capsys):
    """A polygon < 0.25° in any direction should print a warning."""
    import geopandas as gpd
    from shapely.geometry import box

    # 0.1° × 0.1° — below the 0.25° threshold in both dimensions
    gdf = gpd.GeoDataFrame(geometry=[box(10.0, 50.0, 10.1, 50.1)], crs="EPSG:4326")
    path = tmp_path / "small.geojson"
    gdf.to_file(str(path), driver="GeoJSON")

    validate_inputs(str(path), 2030, 2031, "dummy")

    captured = capsys.readouterr()
    assert "Warning" in captured.out or "small" in captured.out.lower()


# ---------------------------------------------------------------------------
# NASA NEX path — pre-1979 start year (line 99)
# ---------------------------------------------------------------------------

def test_pre_1979_start_year_nasa_nex_message(test_polygon_path, capsys):
    """start_year before 1979 should select NASA NEX and print the pre-1979 reason."""
    validate_inputs(test_polygon_path, start_year=1960, end_year=1970, api_token="dummy")
    out = capsys.readouterr().out
    assert "NASA NEX" in out or "NEX" in out
    assert "1979" in out   # mentions the AgERA5 start boundary


# ---------------------------------------------------------------------------
# NASA NEX path — period spanning historical and future (lines 103, 113-118)
# ---------------------------------------------------------------------------

def test_historical_and_future_spanning_prints_scenario_split(test_polygon_path, capsys):
    """A period crossing present prints info about the historical/SSP year split."""
    import datetime

    current_year = datetime.datetime.now().year
    # start_year in past, end_year in future → NASA NEX, spans historical+SSP
    validate_inputs(test_polygon_path,
                    start_year=2010, end_year=current_year + 5,
                    api_token="dummy")
    out = capsys.readouterr().out
    # Should mention both historical and SSP
    assert "historical" in out.lower() or "ssp" in out.lower()

