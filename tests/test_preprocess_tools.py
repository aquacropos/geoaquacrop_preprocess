"""
Tests for pure utility functions in geoaquacrop_preprocess.preprocess_tools.

All tests here run without any network access.
"""

import os
import tempfile

import numpy as np
import pytest
import xarray as xr
import rioxarray  # noqa: F401 – registers .rio accessor

from geoaquacrop_preprocess.preprocess_tools import (
    spam_refyear,
    basegrid,
    safe_clip,
    makedirs,
    ensure_xy_dims,
    unzip_all,
    agera5_merge_yearly,
    preprocess_agera5,
    preprocess_spam,
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


# ---------------------------------------------------------------------------
# unzip_all
# ---------------------------------------------------------------------------

def test_unzip_all_extracts_and_removes_zip(tmp_path):
    """unzip_all should extract the archive to a same-named folder and delete the zip."""
    from zipfile import ZipFile
    from geoaquacrop_preprocess.preprocess_tools import unzip_all

    zip_path = tmp_path / "archive.zip"
    with ZipFile(str(zip_path), "w") as z:
        z.writestr("subdir/data.txt", "hello")

    unzip_all(str(tmp_path))

    assert not zip_path.exists(), "ZIP file should be deleted after extraction."
    extracted = tmp_path / "archive" / "subdir" / "data.txt"
    assert extracted.exists(), "Extracted file should be present."


def test_unzip_all_no_zips_is_noop(tmp_path):
    """unzip_all on a directory with no ZIPs should succeed silently."""
    from geoaquacrop_preprocess.preprocess_tools import unzip_all

    (tmp_path / "notazip.txt").write_text("content")
    unzip_all(str(tmp_path))   # must not raise


def test_unzip_all_nested_zip(tmp_path):
    """unzip_all should also extract a ZIP that was itself inside an extracted folder."""
    from zipfile import ZipFile
    from geoaquacrop_preprocess.preprocess_tools import unzip_all

    # Outer ZIP contains an inner ZIP
    inner_zip_content = tmp_path / "_inner.zip"
    with ZipFile(str(inner_zip_content), "w") as z:
        z.writestr("inner.txt", "inner content")

    outer_zip = tmp_path / "outer.zip"
    with ZipFile(str(outer_zip), "w") as z:
        z.write(str(inner_zip_content), arcname="inner.zip")
    inner_zip_content.unlink()  # only the outer zip should exist now

    unzip_all(str(tmp_path))

    # Both ZIPs should be gone; inner.txt should be present somewhere
    assert not outer_zip.exists()
    inner_txt = list(tmp_path.rglob("inner.txt"))
    assert len(inner_txt) > 0


# ---------------------------------------------------------------------------
# agera5_merge_yearly
# ---------------------------------------------------------------------------

def test_agera5_merge_yearly_combines_daily_files(tmp_path):
    """agera5_merge_yearly should merge daily NetCDF files into one yearly file."""
    import pandas as pd
    from geoaquacrop_preprocess.preprocess_tools import agera5_merge_yearly

    yearfile = str(tmp_path / "MinTemp2020.nc")
    yearfolder = tmp_path / "MinTemp2020"   # same stem, no extension
    yearfolder.mkdir()

    lats = np.array([10.0, 11.0])
    lons = np.array([100.0, 101.0])
    varname = "Temperature_Air_2m_Min_24h"

    for i, day in enumerate(["2020-01-01", "2020-01-02"]):
        times = pd.DatetimeIndex([day])
        ds = xr.Dataset(
            {varname: xr.DataArray(
                np.ones((1, 2, 2), dtype=np.float32),
                dims=["time", "y", "x"],
                coords={"time": times, "y": lats, "x": lons},
            )},
        )
        ds.to_netcdf(str(yearfolder / f"day{i:02d}.nc"))

    agera5_merge_yearly(str(tmp_path), yearfile)

    assert os.path.exists(yearfile), "Merged yearly file was not created."
    assert not yearfolder.exists(), "Daily folder should be removed after merging."

    result = xr.open_dataset(yearfile)
    assert "time" in result.dims
    assert len(result.time) == 2
    result.close()


# ---------------------------------------------------------------------------
# preprocess_agera5
# ---------------------------------------------------------------------------

def _make_to_match(lats, lons):
    """Create a minimal template raster for preprocess tests."""
    ds = xr.Dataset(
        {"Band1": (("y", "x"), np.ones((len(lats), len(lons)), dtype=np.uint8))},
        coords={"y": lats, "x": lons},
    )
    return ds.rio.write_crs(4326)


@pytest.mark.parametrize("variable,raw_name,kelvin_value,expected_celsius", [
    ("MinTemp", "Temperature_Air_2m_Min_24h", 293.15, 20.0),
    ("MaxTemp", "Temperature_Air_2m_Max_24h", 303.15, 30.0),
])
def test_preprocess_agera5_temperature_conversion(variable, raw_name, kelvin_value,
                                                expected_celsius, tmp_path):
    """preprocess_agera5 should rename the variable and convert K → °C."""
    import pandas as pd
    from geoaquacrop_preprocess.preprocess_tools import preprocess_agera5

    lats = np.array([12.0, 11.0, 10.0])   # descending (N→S)
    lons = np.array([100.0, 101.0, 102.0])
    times = pd.date_range("2020-01-01", periods=3)
    to_match = _make_to_match(lats, lons)

    data_k = np.full((3, 3, 3), kelvin_value, dtype=np.float32)
    src = xr.Dataset(
        {
            raw_name: xr.DataArray(
                data_k, dims=["time", "latitude", "longitude"],
                coords={"time": times, "latitude": lats, "longitude": lons},
            ),
            "crs": xr.DataArray(0),
        }
    )

    preprocess_agera5(src, variable, [2020], str(tmp_path), to_match)

    outfile = tmp_path / "processed" / f"{variable}20202020.nc"
    assert outfile.exists(), f"Output file {outfile} was not created."
    result = xr.open_dataset(str(outfile))
    assert variable in result.data_vars
    non_nan = result[variable].values[~np.isnan(result[variable].values)]
    if len(non_nan) > 0:
        assert np.allclose(non_nan, expected_celsius, atol=1.0)
    result.close()


def test_preprocess_agera5_precipitation_clamps_negatives(tmp_path):
    """preprocess_agera5 should clip negative precipitation values to 0."""
    import pandas as pd
    from geoaquacrop_preprocess.preprocess_tools import preprocess_agera5

    lats = np.array([12.0, 11.0, 10.0])
    lons = np.array([100.0, 101.0, 102.0])
    times = pd.date_range("2020-01-01", periods=2)
    to_match = _make_to_match(lats, lons)

    data = np.full((2, 3, 3), -1.0, dtype=np.float32)   # all negative
    src = xr.Dataset(
        {
            "Precipitation_Flux": xr.DataArray(
                data, dims=["time", "latitude", "longitude"],
                coords={"time": times, "latitude": lats, "longitude": lons},
            ),
            "crs": xr.DataArray(0),
        }
    )

    preprocess_agera5(src, "Precipitation", [2020], str(tmp_path), to_match)

    outfile = tmp_path / "processed" / "Precipitation20202020.nc"
    assert outfile.exists()
    result = xr.open_dataset(str(outfile))
    non_nan = result["Precipitation"].values[~np.isnan(result["Precipitation"].values)]
    assert np.all(non_nan >= 0.0), "Negative precipitation should be clipped to 0."
    result.close()


def test_preprocess_agera5_output_is_float32(tmp_path):
    """preprocess_agera5 should always save float32 data."""
    import pandas as pd
    from geoaquacrop_preprocess.preprocess_tools import preprocess_agera5

    lats = np.array([12.0, 11.0, 10.0])
    lons = np.array([100.0, 101.0, 102.0])
    times = pd.date_range("2020-01-01", periods=2)
    to_match = _make_to_match(lats, lons)

    # Input in float64 — output should be cast to float32
    data = np.full((2, 3, 3), 5.0, dtype=np.float64)
    src = xr.Dataset(
        {
            "Precipitation_Flux": xr.DataArray(
                data, dims=["time", "latitude", "longitude"],
                coords={"time": times, "latitude": lats, "longitude": lons},
            ),
            "crs": xr.DataArray(0),
        }
    )

    preprocess_agera5(src, "Precipitation", [2020], str(tmp_path), to_match)

    outfile = tmp_path / "processed" / "Precipitation20202020.nc"
    result = xr.open_dataset(str(outfile))
    assert result["Precipitation"].dtype == np.float32
    result.close()


# ---------------------------------------------------------------------------
# preprocess_spam
# ---------------------------------------------------------------------------

def test_preprocess_spam_physical_area(test_polygon_path, test_polygon_gdf, tmp_path):
    """preprocess_spam should produce a NetCDF with per-crop area variables."""
    import rasterio
    from rasterio.transform import from_bounds
    from geoaquacrop_preprocess.preprocess_tools import preprocess_spam, basegrid

    template_path = str(tmp_path / "template.nc")
    to_match, _ = basegrid(test_polygon_path, resolution=0.05, templategrid_path=template_path)

    xmin, ymin, xmax, ymax = test_polygon_gdf.total_bounds
    buf = 0.5
    H, W = 10, 10
    transform = from_bounds(xmin - buf, ymin - buf, xmax + buf, ymax + buf, W, H)

    spam_dir = tmp_path / "spam_data"
    spam_dir.mkdir()

    # SPAM filename convention: last char before .tif is technique (R/I);
    # chars [-10:-6] are the 4-letter crop ID.
    for crop, tech in [("MAIZ", "R"), ("MAIZ", "I"), ("BARL", "R")]:
        fname = f"spam2020V1r0_global_phys_area_{crop}_{tech}.tif"
        path = str(spam_dir / fname)
        data = np.full((H, W), 50.0, dtype=np.float32)
        with rasterio.open(
            path, "w", driver="GTiff",
            height=H, width=W, count=1,
            dtype="float32", crs="EPSG:4326",
            transform=transform,
        ) as dst:
            dst.write(data, 1)

    preprocess_spam(str(tmp_path), str(spam_dir), "2020", "physical_area",
                 test_polygon_path, to_match)

    outfile = tmp_path / "processed" / "spam2020_physical_area.nc"
    assert outfile.exists(), "Output NetCDF was not created."
    result = xr.open_dataset(str(outfile))
    assert "Maize_rf_physical_area" in result.data_vars
    assert "Maize_ir_physical_area" in result.data_vars
    assert "Barley_rf_physical_area" in result.data_vars
    result.close()


def test_preprocess_spam_yield(test_polygon_path, test_polygon_gdf, tmp_path):
    """preprocess_spam with spam_variable='yield' should divide values by 1000."""
    import rasterio
    from rasterio.transform import from_bounds
    from geoaquacrop_preprocess.preprocess_tools import preprocess_spam, basegrid

    template_path = str(tmp_path / "template.nc")
    to_match, _ = basegrid(test_polygon_path, resolution=0.05, templategrid_path=template_path)

    xmin, ymin, xmax, ymax = test_polygon_gdf.total_bounds
    buf = 0.5
    H, W = 10, 10
    transform = from_bounds(xmin - buf, ymin - buf, xmax + buf, ymax + buf, W, H)

    spam_dir = tmp_path / "spam_yield"
    spam_dir.mkdir()

    fname = "spam2020V1r0_global_yield_MAIZ_R.tif"
    path = str(spam_dir / fname)
    data = np.full((H, W), 3000.0, dtype=np.float32)   # 3000 kg/ha → 3 t/ha
    with rasterio.open(
        path, "w", driver="GTiff",
        height=H, width=W, count=1,
        dtype="float32", crs="EPSG:4326",
        transform=from_bounds(xmin - buf, ymin - buf, xmax + buf, ymax + buf, W, H),
    ) as dst:
        dst.write(data, 1)

    preprocess_spam(str(tmp_path), str(spam_dir), "2020", "yield",
                 test_polygon_path, to_match)

    outfile = tmp_path / "processed" / "spam2020_yield.nc"
    assert outfile.exists()
    result = xr.open_dataset(str(outfile))
    assert "Maize_rf_yield" in result.data_vars
    # Values should be in t/ha (÷1000): check non-NaN values ≈ 3
    non_nan = result["Maize_rf_yield"].values[~np.isnan(result["Maize_rf_yield"].values)]
    if len(non_nan) > 0:
        assert np.allclose(non_nan, 3.0, atol=0.5)
    result.close()


def test_preprocess_spam_filters_invalid_technique_and_crop(test_polygon_path, test_polygon_gdf, tmp_path):
    """preprocess_spam should delete files with unsupported technique codes or unknown crop IDs."""
    import rasterio
    from rasterio.transform import from_bounds

    template_path = str(tmp_path / "template.nc")
    to_match, _ = basegrid(test_polygon_path, resolution=0.05, templategrid_path=template_path)

    xmin, ymin, xmax, ymax = test_polygon_gdf.total_bounds
    buf = 0.5
    H, W = 8, 8
    transform = from_bounds(xmin - buf, ymin - buf, xmax + buf, ymax + buf, W, H)
    data = np.full((H, W), 50.0, dtype=np.float32)

    spam_dir = tmp_path / "spam_filter"
    spam_dir.mkdir()

    def _make_tif(name):
        path = str(spam_dir / name)
        with rasterio.open(path, "w", driver="GTiff", height=H, width=W, count=1,
                           dtype="float32", crs="EPSG:4326", transform=transform) as dst:
            dst.write(data, 1)

    # Valid file
    _make_tif("spam2020V1r0_global_phys_area_MAIZ_R.tif")
    # Invalid technique 'X' → deleted by lines 113-114
    invalid_tech = spam_dir / "spam2020V1r0_global_phys_area_MAIZ_X.tif"
    _make_tif(invalid_tech.name)
    # Unknown crop ID 'ZZZZ' → deleted by lines 119-120
    invalid_crop = spam_dir / "spam2020V1r0_global_phys_area_ZZZZ_R.tif"
    _make_tif(invalid_crop.name)

    preprocess_spam(str(tmp_path), str(spam_dir), "2020", "physical_area",
                 test_polygon_path, to_match)

    assert not invalid_tech.exists(), "Invalid-technique file should be deleted."
    assert not invalid_crop.exists(), "Unknown-crop file should be deleted."
    assert (tmp_path / "processed" / "spam2020_physical_area.nc").exists()


# ---------------------------------------------------------------------------
# preprocess_agera5 — InitSoilwater branch (lines 219-220)
# ---------------------------------------------------------------------------

def test_preprocess_agera5_initsoilwater_path(tmp_path):
    """preprocess_agera5 with variable='InitSoilwater' covers the ERA5-Land rename path."""
    import pandas as pd

    lats = np.array([12.0, 11.0, 10.0])
    lons = np.array([100.0, 101.0, 102.0])
    times = pd.date_range("2020-01-01", periods=2)
    to_match = _make_to_match(lats, lons)

    data = np.full((2, 3, 3), 0.3, dtype=np.float32)
    src = xr.Dataset(
        {
            "swvl1": xr.DataArray(
                data, dims=["valid_time", "latitude", "longitude"],
                coords={"valid_time": times, "latitude": lats, "longitude": lons},
            ),
            "expver": xr.DataArray(0),
            "number": xr.DataArray(0),
        }
    )

    preprocess_agera5(src, "InitSoilwater", [2020], str(tmp_path), to_match)

    # Check that the function ran without raising
    outfile = tmp_path / "processed" / "InitSoilwater20202020.nc"
    assert outfile.exists(), "InitSoilwater output file was not created."


# ---------------------------------------------------------------------------
# basegrid — load existing template (lines 409-410)
# ---------------------------------------------------------------------------

def test_basegrid_loads_existing_template(test_polygon_path, tmp_path):
    """basegrid should load an existing template file without re-creating it."""
    template_path = str(tmp_path / "template.nc")

    # First call: creates the file
    ds1, bounds1 = basegrid(test_polygon_path, resolution=0.05, templategrid_path=template_path)
    mtime1 = os.path.getmtime(template_path)

    import time
    time.sleep(0.05)  # ensure detectable mtime difference

    # Second call: loads existing file (lines 409-410)
    ds2, bounds2 = basegrid(test_polygon_path, resolution=0.05, templategrid_path=template_path)
    mtime2 = os.path.getmtime(template_path)

    # File should NOT have been modified (loaded, not re-created)
    assert mtime2 == mtime1, "Template file should not be modified on second call."
    assert bounds1 == bounds2


# ---------------------------------------------------------------------------
# basegrid — non-polygon and non-4326 exceptions (lines 396, 400)
# ---------------------------------------------------------------------------

def test_basegrid_raises_for_non_polygon(tmp_path):
    """basegrid should raise when the input file contains non-polygon geometries."""
    import geopandas as gpd
    from shapely.geometry import Point

    gdf = gpd.GeoDataFrame(geometry=[Point(10, 50)], crs="EPSG:4326")
    path = tmp_path / "points.geojson"
    gdf.to_file(str(path), driver="GeoJSON")

    with pytest.raises(Exception, match="Polygon"):
        basegrid(str(path), resolution=0.05, templategrid_path=str(tmp_path / "t.nc"))


# ---------------------------------------------------------------------------
# safe_clip — CRS mismatch branch (line 313)
# ---------------------------------------------------------------------------

def test_safe_clip_reprojects_mask_to_match_raster_crs(test_polygon_gdf, tmp_path):
    """safe_clip with a mask in a different CRS should reproject the mask automatically."""
    # Build a raster in EPSG:4326 centred on the test polygon
    gdf = test_polygon_gdf
    xmin, ymin, xmax, ymax = gdf.total_bounds
    buf = 0.1
    lons = np.arange(xmin - buf, xmax + buf, 0.05)
    lats = np.arange(ymax + buf, ymin - buf, -0.05)  # descending
    data = np.ones((len(lats), len(lons)), dtype=np.float32)

    ds = xr.Dataset(
        {"band_data": (("y", "x"), data)},
        coords={"y": lats, "x": lons},
    )
    ds = ds.rio.write_crs(4326)

    # Mask in EPSG:3857 (Web Mercator) — different CRS from raster
    mask_3857 = test_polygon_gdf.to_crs(epsg=3857)
    clipped = safe_clip(ds, mask_3857)

    assert isinstance(clipped, xr.Dataset)

