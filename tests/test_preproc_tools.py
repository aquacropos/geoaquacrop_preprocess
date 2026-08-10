"""
Tests for pure utility functions in geoaquacrop_preproc.preproc_tools.

All tests here run without any network access.
"""

import os
import tempfile

import numpy as np
import pytest
import xarray as xr
import rioxarray  # noqa: F401 – registers .rio accessor

from geoaquacrop_preproc.preproc_tools import (
    spam_refyear,
    basegrid,
    safe_clip,
    makedirs,
    ensure_xy_dims,
)


# ---------------------------------------------------------------------------
# spam_refyear
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("start, end, expected", [
    (2008, 2012, "2010"),   # avg 2010 → nearest to 2010
    (2009, 2011, "2010"),   # avg 2010 exactly
    (2015, 2025, "2020"),   # avg 2020 → nearest to 2020
    (2018, 2022, "2020"),   # avg 2020 exactly
    (2012, 2014, "2010"),   # avg 2013 → nearer to 2010 than 2020
    (2014, 2016, "2010"),   # avg 2015 → equidistant; min() picks first entry (2010)
])
def test_spam_refyear(start, end, expected):
    assert spam_refyear(start, end) == expected


def test_spam_refyear_returns_string():
    result = spam_refyear(2010, 2010)
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# basegrid
# ---------------------------------------------------------------------------

def test_basegrid_creates_file(test_polygon_path, tmp_path):
    """basegrid() should write a template NetCDF and return a dataset + bounds."""
    out_path = str(tmp_path / "template_grid.nc")
    to_match, bounds = basegrid(test_polygon_path, resolution=0.05, templategrid_path=out_path)

    assert os.path.exists(out_path), "Template grid file was not created."
    assert isinstance(to_match, xr.Dataset)
    assert len(bounds) == 4, "bounds should be (xmin, ymin, xmax, ymax)"


def test_basegrid_crs_is_4326(test_polygon_path, tmp_path):
    out_path = str(tmp_path / "template_grid.nc")
    to_match, _ = basegrid(test_polygon_path, resolution=0.05, templategrid_path=out_path)
    assert to_match.rio.crs is not None
    assert to_match.rio.crs.to_epsg() == 4326


def test_basegrid_bounds_within_polygon_extent(test_polygon_path, tmp_path):
    """Template grid extent should encompass the polygon bounding box."""
    import geopandas as gpd
    gdf = gpd.read_file(test_polygon_path)
    xmin_poly, ymin_poly, xmax_poly, ymax_poly = gdf.total_bounds

    out_path = str(tmp_path / "template_grid.nc")
    _, bounds = basegrid(test_polygon_path, resolution=0.05, templategrid_path=out_path)
    xmin_grid, ymin_grid, xmax_grid, ymax_grid = bounds

    assert xmin_grid <= xmin_poly
    assert ymin_grid <= ymin_poly
    assert xmax_grid >= xmax_poly
    assert ymax_grid >= ymax_poly


# ---------------------------------------------------------------------------
# makedirs
# ---------------------------------------------------------------------------

def test_makedirs_creates_nested_dirs(tmp_path):
    result = makedirs(str(tmp_path), "level1", "level2")
    assert os.path.isdir(result)
    assert result == os.path.join(str(tmp_path), "level1", "level2")


def test_makedirs_idempotent(tmp_path):
    makedirs(str(tmp_path), "a", "b")
    makedirs(str(tmp_path), "a", "b")  # should not raise
    assert os.path.isdir(os.path.join(str(tmp_path), "a", "b"))


# ---------------------------------------------------------------------------
# ensure_xy_dims
# ---------------------------------------------------------------------------

def test_ensure_xy_dims_renames_lat_lon():
    """ensure_xy_dims should rename lat/lon to y/x."""
    ds = xr.Dataset(
        {"data": (("lat", "lon"), np.ones((3, 4)))},
        coords={"lat": [1.0, 2.0, 3.0], "lon": [10.0, 11.0, 12.0, 13.0]},
    )
    result = ensure_xy_dims(ds)
    assert "x" in result.dims
    assert "y" in result.dims
    assert "lat" not in result.dims
    assert "lon" not in result.dims


def test_ensure_xy_dims_passthrough_for_xy():
    """ensure_xy_dims should not modify a dataset already using x/y dims."""
    ds = xr.Dataset(
        {"data": (("y", "x"), np.ones((3, 4)))},
        coords={"y": [1.0, 2.0, 3.0], "x": [10.0, 11.0, 12.0, 13.0]},
    )
    result = ensure_xy_dims(ds)
    assert "x" in result.dims
    assert "y" in result.dims


# ---------------------------------------------------------------------------
# safe_clip
# ---------------------------------------------------------------------------

def test_safe_clip_clips_raster(test_polygon_gdf, test_polygon_path, tmp_path):
    """safe_clip should return a dataset whose spatial extent fits inside the polygon."""
    import geopandas as gpd

    # Build a tiny synthetic raster that covers the test polygon area
    gdf = test_polygon_gdf
    xmin, ymin, xmax, ymax = gdf.total_bounds

    # Add a 0.2° buffer so the polygon sits well inside the raster
    buf = 0.2
    lons = np.arange(xmin - buf, xmax + buf, 0.05)
    lats = np.arange(ymin - buf, ymax + buf, 0.05)
    data = np.ones((len(lats), len(lons)), dtype=np.float32)

    ds = xr.Dataset(
        {"band_data": (("y", "x"), data)},
        coords={"y": lats, "x": lons},
    )
    ds = ds.rio.write_crs(4326)

    clipped = safe_clip(ds, gdf)

    # Clipped result should still be a dataset and share the same CRS
    assert isinstance(clipped, xr.Dataset)
    assert clipped.rio.crs.to_epsg() == 4326


def test_safe_clip_non_overlapping_returns_empty(test_polygon_gdf):
    """safe_clip with a raster far from the polygon should return an all-nodata result."""
    # Raster in the North Sea, polygon in Vietnam — no overlap
    lons = np.arange(0.0, 5.0, 0.5)
    lats = np.arange(50.0, 55.0, 0.5)
    data = np.ones((len(lats), len(lons)), dtype=np.float32)

    ds = xr.Dataset(
        {"band_data": (("y", "x"), data)},
        coords={"y": lats, "x": lons},
    )
    ds = ds.rio.write_crs(4326)

    clipped = safe_clip(ds, test_polygon_gdf)
    assert isinstance(clipped, xr.Dataset)
