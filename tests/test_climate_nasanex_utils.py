"""
Tests for pure / computation-only functions in climate_nasanex.

All tests run without any network access.
"""

import numpy as np
import pandas as pd
import pytest
import xarray as xr
import rioxarray  # noqa: F401 – registers .rio accessor

from geoaquacrop_preproc.climate_nasanex import (
    _scenario_for_year,
    _build_ncss_url,
    _calc_et0_xr,
    _preproc_and_save,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_da(value, times, lats, lons, name="var"):
    """Uniform (time, y, x) DataArray filled with *value*."""
    data = np.full((len(times), len(lats), len(lons)), value, dtype=np.float32)
    return xr.DataArray(
        data,
        dims=["time", "y", "x"],
        coords={"time": times, "y": lats, "x": lons},
        name=name,
    )


def _make_to_match(lats, lons):
    """Minimal template raster (Band1 = 1 everywhere)."""
    ds = xr.Dataset(
        {"Band1": (("y", "x"), np.ones((len(lats), len(lons)), dtype=np.uint8))},
        coords={"y": lats, "x": lons},
    )
    return ds.rio.write_crs(4326)


# ---------------------------------------------------------------------------
# _scenario_for_year
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("year,ssp,expected", [
    (2000, "ssp245", "historical"),
    (2014, "ssp245", "historical"),   # boundary — still historical
    (2015, "ssp245", "ssp245"),        # boundary — switches to SSP
    (2100, "ssp585", "ssp585"),
    (1950, "ssp126", "historical"),
])
def test_scenario_for_year(year, ssp, expected):
    assert _scenario_for_year(year, ssp) == expected


# ---------------------------------------------------------------------------
# _build_ncss_url
# ---------------------------------------------------------------------------

def test_build_ncss_url_contains_model_and_variable():
    url = _build_ncss_url(
        "GFDL-CM4", "ssp245", "r1i1p1f1", "tasmin", 2030,
        north=50.0, west=5.0, south=45.0, east=15.0,
    )
    assert "GFDL-CM4" in url
    assert "ssp245" in url
    assert "tasmin" in url
    assert "2030" in url


def test_build_ncss_url_bbox_params():
    url = _build_ncss_url(
        "GFDL-CM4", "ssp245", "r1i1p1f1", "tasmax", 2030,
        north=50.0, west=5.0, south=45.0, east=15.0,
    )
    assert "north=50.0" in url
    assert "south=45.0" in url
    assert "west=5.0" in url
    assert "east=15.0" in url


def test_build_ncss_url_version_suffix():
    url = _build_ncss_url(
        "GFDL-CM4", "ssp245", "r1i1p1f1", "tasmin", 2030,
        north=50.0, west=5.0, south=45.0, east=15.0,
        grid="gr1", version_suffix="_v2.0",
    )
    assert "_v2.0" in url
    assert "gr1" in url


def test_build_ncss_url_returns_string():
    url = _build_ncss_url(
        "GFDL-CM4", "ssp245", "r1i1p1f1", "pr", 2030,
        north=50.0, west=5.0, south=45.0, east=15.0,
    )
    assert isinstance(url, str)
    assert url.startswith("https://")


# ---------------------------------------------------------------------------
# _calc_et0_xr
# ---------------------------------------------------------------------------

@pytest.fixture
def tropical_climate():
    """Five-day synthetic climate over a 2×2 tropical grid (lats ~10–15°N)."""
    times = pd.date_range("2020-06-01", periods=5)
    lats = np.array([15.0, 10.0])   # descending
    lons = np.array([100.0, 105.0])
    return dict(
        tasmin  = _make_da(20.0,  times, lats, lons),
        tasmax  = _make_da(30.0,  times, lats, lons),
        hurs    = _make_da(60.0,  times, lats, lons),
        rsds    = _make_da(20.0,  times, lats, lons),   # MJ m-2 d-1
        wind10m = _make_da(2.0,   times, lats, lons),
        times=times, lats=lats, lons=lons,
    )


def test_calc_et0_returns_dataarray(tropical_climate):
    c = tropical_climate
    et0 = _calc_et0_xr(c["tasmin"], c["tasmax"], c["hurs"], c["rsds"], c["wind10m"])
    assert isinstance(et0, xr.DataArray)
    assert et0.name == "ReferenceET"


def test_calc_et0_non_negative(tropical_climate):
    c = tropical_climate
    et0 = _calc_et0_xr(c["tasmin"], c["tasmax"], c["hurs"], c["rsds"], c["wind10m"])
    assert float(et0.min()) >= 0.0


def test_calc_et0_plausible_tropical_range(tropical_climate):
    """Tropical summer ET0 with moderate radiation should be 3–12 mm/day."""
    c = tropical_climate
    et0 = _calc_et0_xr(c["tasmin"], c["tasmax"], c["hurs"], c["rsds"], c["wind10m"])
    mean_et0 = float(et0.mean())
    assert 0.5 < mean_et0 < 15.0, f"ET0 mean {mean_et0:.2f} outside plausible range"


def test_calc_et0_shape_matches_input(tropical_climate):
    c = tropical_climate
    et0 = _calc_et0_xr(c["tasmin"], c["tasmax"], c["hurs"], c["rsds"], c["wind10m"])
    assert et0.shape == c["tasmin"].shape


def test_calc_et0_elevation_changes_result(tropical_climate):
    """ET0 at high elevation should differ from sea level due to pressure change."""
    c = tropical_climate
    et0_sea  = _calc_et0_xr(c["tasmin"], c["tasmax"], c["hurs"], c["rsds"], c["wind10m"], elev=0.0)
    et0_high = _calc_et0_xr(c["tasmin"], c["tasmax"], c["hurs"], c["rsds"], c["wind10m"], elev=3000.0)
    assert not np.allclose(float(et0_sea.mean()), float(et0_high.mean()), rtol=1e-3)


def test_calc_et0_zero_radiation_reduces_et0(tropical_climate):
    """With zero solar radiation, ET0 should be lower than with normal radiation."""
    c = tropical_climate
    et0_normal = _calc_et0_xr(c["tasmin"], c["tasmax"], c["hurs"], c["rsds"], c["wind10m"])
    zero_rsds = _make_da(0.0, c["times"], c["lats"], c["lons"])
    et0_dark = _calc_et0_xr(c["tasmin"], c["tasmax"], c["hurs"], zero_rsds, c["wind10m"])
    assert float(et0_dark.mean()) < float(et0_normal.mean())


def test_calc_et0_output_attrs(tropical_climate):
    c = tropical_climate
    et0 = _calc_et0_xr(c["tasmin"], c["tasmax"], c["hurs"], c["rsds"], c["wind10m"])
    assert "units" in et0.attrs
    assert "mm" in et0.attrs["units"].lower() or "day" in et0.attrs["units"].lower()


# ---------------------------------------------------------------------------
# _preproc_and_save
# ---------------------------------------------------------------------------

def test_preproc_and_save_writes_file(test_polygon_path, tmp_path):
    """_preproc_and_save should reproject synthetic data and write a NetCDF."""
    from geoaquacrop_preproc.preproc_tools import basegrid
    import geopandas as gpd

    template_path = str(tmp_path / "template.nc")
    to_match, _ = basegrid(test_polygon_path, resolution=0.05, templategrid_path=template_path)

    gdf = gpd.read_file(test_polygon_path)
    xmin, ymin, xmax, ymax = gdf.total_bounds
    buf = 1.0

    lats = np.arange(ymax + buf, ymin - buf, -0.25)
    lons = np.arange(xmin - buf, xmax + buf, 0.25)
    times = pd.date_range("2030-01-01", periods=5)

    data = np.full((len(times), len(lats), len(lons)), 20.0, dtype=np.float32)
    src = xr.Dataset(
        {"MinTemp": xr.DataArray(data, dims=["time", "y", "x"],
                                  coords={"time": times, "y": lats, "x": lons})}
    )

    _preproc_and_save(src, "MinTemp", [2030, 2031], str(tmp_path), to_match,
                      model="GFDL-CM4", scenario="ssp245", ensemble="r1i1p1f1")

    outfile = tmp_path / "processed" / "MinTemp20302031.nc"
    assert outfile.exists(), "Output file was not created."
    result = xr.open_dataset(str(outfile))
    assert "MinTemp" in result.data_vars
    assert result["MinTemp"].dtype == np.float32
    result.close()


def test_preproc_and_save_cf_attributes(test_polygon_path, tmp_path):
    """Output file should carry NASA NEX provenance attributes."""
    from geoaquacrop_preproc.preproc_tools import basegrid
    import geopandas as gpd

    template_path = str(tmp_path / "template.nc")
    to_match, _ = basegrid(test_polygon_path, resolution=0.05, templategrid_path=template_path)

    gdf = gpd.read_file(test_polygon_path)
    xmin, ymin, xmax, ymax = gdf.total_bounds
    buf = 1.0
    lats = np.arange(ymax + buf, ymin - buf, -0.25)
    lons = np.arange(xmin - buf, xmax + buf, 0.25)
    times = pd.date_range("2030-01-01", periods=3)
    data = np.ones((len(times), len(lats), len(lons)), dtype=np.float32)
    src = xr.Dataset(
        {"MaxTemp": xr.DataArray(data, dims=["time", "y", "x"],
                                  coords={"time": times, "y": lats, "x": lons})}
    )

    _preproc_and_save(src, "MaxTemp", [2030], str(tmp_path), to_match,
                      model="GFDL-CM4", scenario="ssp245", ensemble="r1i1p1f1")

    outfile = tmp_path / "processed" / "MaxTemp20302030.nc"
    result = xr.open_dataset(str(outfile))
    assert result.attrs.get("cmip6_model") == "GFDL-CM4"
    assert result.attrs.get("cmip6_scenario") == "ssp245"
    result.close()
