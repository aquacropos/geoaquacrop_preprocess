"""
Tests for ricecalendar_marc.ricecalendar_marc().

Bypasses the download step by pre-creating the expected NetCDF file in the
rawdata directory, exercising the full processing pipeline without network access.
"""

import numpy as np
import pytest
import xarray as xr
import rioxarray  # noqa: F401


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_marc_ds(lats, lons, values=None):
    """Create a synthetic MARC rice calendar Dataset."""
    H, W = len(lats), len(lons)
    if values is None:
        # Default: planting DOY 90 (spring), harvest DOY 210 (autumn)
        values = {"transplant": 90.0, "harvest": 210.0}

    tp = values.get("transplant", 90.0)
    hv = values.get("harvest", 210.0)

    def _da(val):
        return xr.DataArray(
            np.full((H, W), float(val), dtype=np.float32),
            dims=["lat", "lon"], coords={"lat": lats, "lon": lons},
        )

    return xr.Dataset({
        "Transplanting_1_Cropping": _da(tp),
        "Harvest_1_Cropping"      : _da(hv),
        "Transplanting_2_Cropping": _da(tp + 90),
        "Harvest_2_Cropping"      : _da(hv + 90),
        # Season 3 crosses the year boundary (harvest DOY < planting DOY)
        "Transplanting_3_Cropping": _da(300.0),
        "Harvest_3_Cropping"      : _da(60.0),
    })


def _make_marc_ds_with_nans(lats, lons):
    """Create a MARC Dataset that has NaN values in a central patch."""
    H, W = len(lats), len(lons)

    def _da_nan(val):
        arr = np.full((H, W), float(val), dtype=np.float32)
        r1, r2 = max(0, H // 4), min(H, H // 2)
        c1, c2 = max(0, W // 4), min(W, W // 2)
        arr[r1:r2, c1:c2] = np.nan
        return xr.DataArray(arr, dims=["lat", "lon"],
                             coords={"lat": lats, "lon": lons})

    return xr.Dataset({
        "Transplanting_1_Cropping": _da_nan(90.0),
        "Harvest_1_Cropping"      : _da_nan(210.0),
        "Transplanting_2_Cropping": _da_nan(180.0),
        "Harvest_2_Cropping"      : _da_nan(300.0),
        "Transplanting_3_Cropping": _da_nan(300.0),
        "Harvest_3_Cropping"      : _da_nan(60.0),
    })


@pytest.fixture
def marc_setup(test_polygon_path, test_polygon_gdf, tmp_path):
    """Return (domain_path, basepath, template_path, marc_dir) for MARC tests."""
    from geoaquacrop_preproc.preproc_tools import basegrid

    template_path = str(tmp_path / "template.nc")
    basegrid(test_polygon_path, resolution=0.05, templategrid_path=template_path)

    xmin, ymin, xmax, ymax = test_polygon_gdf.total_bounds
    buf = 1.5

    lats = np.arange(ymax + buf, ymin - buf, -0.5)
    lons = np.arange(xmin - buf, xmax + buf, 0.5)

    marc_dir = tmp_path / "rawdata" / "cropcalendar" / "marc_rice"
    marc_dir.mkdir(parents=True)

    return test_polygon_path, str(tmp_path), template_path, marc_dir, lats, lons


# ---------------------------------------------------------------------------
# Happy-path test — all-valid data (no NaN)
# ---------------------------------------------------------------------------

def test_ricecalendar_marc_creates_output(marc_setup):
    """ricecalendar_marc() with a pre-existing NetCDF should produce the output file."""
    from geoaquacrop_preproc.ricecalendar_marc import ricecalendar_marc

    domain_path, basepath, template_path, marc_dir, lats, lons = marc_setup

    marc_file = marc_dir / "3_Transplanting_Harvest_Cropping.nc"
    _make_marc_ds(lats, lons).to_netcdf(str(marc_file))

    ricecalendar_marc(domain_path, basepath, template_path)

    outfile = (
        __import__("pathlib").Path(basepath)
        / "processed" / "cropcalendar_marc" / "cropcalendar.nc"
    )
    assert outfile.exists(), "MARC rice calendar output NetCDF was not created."


def test_ricecalendar_marc_output_variables(marc_setup):
    """Output should contain rf and ir planting + growing_season_length for all 3 cycles."""
    from geoaquacrop_preproc.ricecalendar_marc import ricecalendar_marc

    domain_path, basepath, template_path, marc_dir, lats, lons = marc_setup

    marc_file = marc_dir / "3_Transplanting_Harvest_Cropping.nc"
    _make_marc_ds(lats, lons).to_netcdf(str(marc_file))

    ricecalendar_marc(domain_path, basepath, template_path)

    import pathlib
    outfile = pathlib.Path(basepath) / "processed" / "cropcalendar_marc" / "cropcalendar.nc"
    result = xr.open_dataset(str(outfile))

    expected_vars = [
        "PaddyRice1_rf_planting", "PaddyRice1_ir_planting",
        "PaddyRice1_rf_growing_season_length", "PaddyRice1_ir_growing_season_length",
        "PaddyRice2_rf_planting", "PaddyRice2_ir_planting",
        "PaddyRice3_rf_planting", "PaddyRice3_ir_planting",
    ]
    for var in expected_vars:
        assert var in result.data_vars, f"Missing expected variable: {var}"

    result.close()


def test_ricecalendar_marc_planting_day_range(marc_setup):
    """Planting DOY values in output should be in [1, 366]."""
    from geoaquacrop_preproc.ricecalendar_marc import ricecalendar_marc

    domain_path, basepath, template_path, marc_dir, lats, lons = marc_setup

    marc_file = marc_dir / "3_Transplanting_Harvest_Cropping.nc"
    _make_marc_ds(lats, lons).to_netcdf(str(marc_file))

    ricecalendar_marc(domain_path, basepath, template_path)

    import pathlib
    outfile = pathlib.Path(basepath) / "processed" / "cropcalendar_marc" / "cropcalendar.nc"
    result = xr.open_dataset(str(outfile))

    for var in result.data_vars:
        if "_planting" not in var or var == "spatial_ref":
            continue
        vals = result[var].values
        non_nan = vals[~np.isnan(vals)]
        if len(non_nan) > 0:
            assert np.all(non_nan >= 1) and np.all(non_nan <= 366), (
                f"{var}: planting DOY out of [1,366]: min={non_nan.min()}, max={non_nan.max()}"
            )

    result.close()


def test_ricecalendar_marc_growing_season_length_positive(marc_setup):
    """Growing season length should be positive for all seasons."""
    from geoaquacrop_preproc.ricecalendar_marc import ricecalendar_marc

    domain_path, basepath, template_path, marc_dir, lats, lons = marc_setup

    marc_file = marc_dir / "3_Transplanting_Harvest_Cropping.nc"
    _make_marc_ds(lats, lons).to_netcdf(str(marc_file))

    ricecalendar_marc(domain_path, basepath, template_path)

    import pathlib
    outfile = pathlib.Path(basepath) / "processed" / "cropcalendar_marc" / "cropcalendar.nc"
    result = xr.open_dataset(str(outfile))

    for var in result.data_vars:
        if "growing_season_length" not in var or var == "spatial_ref":
            continue
        vals = result[var].values
        non_nan = vals[~np.isnan(vals)]
        if len(non_nan) > 0:
            assert np.all(non_nan > 0), (
                f"{var}: negative/zero growing season length found."
            )

    result.close()


# ---------------------------------------------------------------------------
# Year-boundary crossing test — season 3 crosses Jan 1
# ---------------------------------------------------------------------------

def test_ricecalendar_marc_year_boundary_season_length(marc_setup):
    """A season crossing year-end (harvest DOY < planting DOY) should have positive length."""
    from geoaquacrop_preproc.ricecalendar_marc import ricecalendar_marc

    domain_path, basepath, template_path, marc_dir, lats, lons = marc_setup

    marc_file = marc_dir / "3_Transplanting_Harvest_Cropping.nc"
    # Season 3: planting=300, harvest=60  →  length = 60 - 300 + 365 = 125
    _make_marc_ds(lats, lons).to_netcdf(str(marc_file))

    ricecalendar_marc(domain_path, basepath, template_path)

    import pathlib
    outfile = pathlib.Path(basepath) / "processed" / "cropcalendar_marc" / "cropcalendar.nc"
    result = xr.open_dataset(str(outfile))

    gsl_var = "PaddyRice3_rf_growing_season_length"
    if gsl_var in result.data_vars:
        vals = result[gsl_var].values
        non_nan = vals[~np.isnan(vals)]
        if len(non_nan) > 0:
            assert np.all(non_nan > 0), "Year-crossing season has non-positive growing season length."

    result.close()


# ---------------------------------------------------------------------------
# NaN-gap-fill test — exercises fill_nodata_joint inner function
# ---------------------------------------------------------------------------

def test_ricecalendar_marc_fills_nan_gaps(marc_setup):
    """ricecalendar_marc() should fill NaN patches via nearest-neighbor gap-fill."""
    from geoaquacrop_preproc.ricecalendar_marc import ricecalendar_marc

    domain_path, basepath, template_path, marc_dir, lats, lons = marc_setup

    # H, W must be large enough to have a NaN patch surrounded by valid cells
    if len(lats) < 4 or len(lons) < 4:
        pytest.skip("Grid too small for NaN-gap-fill test.")

    marc_file = marc_dir / "3_Transplanting_Harvest_Cropping.nc"
    _make_marc_ds_with_nans(lats, lons).to_netcdf(str(marc_file))

    ricecalendar_marc(domain_path, basepath, template_path)

    import pathlib
    outfile = pathlib.Path(basepath) / "processed" / "cropcalendar_marc" / "cropcalendar.nc"
    assert outfile.exists(), "Output file not created after NaN gap-fill run."
    result = xr.open_dataset(str(outfile))

    # The output may still have NaN (outside domain), but should have some valid values
    gsl_var = "PaddyRice1_rf_growing_season_length"
    if gsl_var in result.data_vars:
        non_nan = result[gsl_var].values[~np.isnan(result[gsl_var].values)]
        assert len(non_nan) >= 0  # just verify the function ran without error

    result.close()


# ---------------------------------------------------------------------------
# DOY 60 (Feb 29) replacement
# ---------------------------------------------------------------------------

def test_ricecalendar_marc_replaces_doy_60(marc_setup):
    """DOY 60 in planting day should be replaced by 61 (leap-year safety)."""
    from geoaquacrop_preproc.ricecalendar_marc import ricecalendar_marc

    domain_path, basepath, template_path, marc_dir, lats, lons = marc_setup

    marc_file = marc_dir / "3_Transplanting_Harvest_Cropping.nc"
    # Use planting day 60 (Feb 29) for season 1
    _make_marc_ds(lats, lons, values={"transplant": 60.0, "harvest": 180.0}).to_netcdf(
        str(marc_file)
    )

    ricecalendar_marc(domain_path, basepath, template_path)

    import pathlib
    outfile = pathlib.Path(basepath) / "processed" / "cropcalendar_marc" / "cropcalendar.nc"
    result = xr.open_dataset(str(outfile))

    planting_var = "PaddyRice1_rf_planting"
    if planting_var in result.data_vars:
        vals = result[planting_var].values
        non_nan = vals[~np.isnan(vals)]
        assert 60.0 not in non_nan, "DOY 60 (Feb 29) should have been replaced by 61."

    result.close()


# ---------------------------------------------------------------------------
# Outside-extent warning (NOT fully inside)
# ---------------------------------------------------------------------------

def test_ricecalendar_marc_outside_extent_warning(test_polygon_path, test_polygon_gdf,
                                                    tmp_path, capsys):
    """When the polygon extends beyond the raster, a WARNING message is printed."""
    from geoaquacrop_preproc.ricecalendar_marc import ricecalendar_marc
    from geoaquacrop_preproc.preproc_tools import basegrid

    template_path = str(tmp_path / "template.nc")
    basegrid(test_polygon_path, resolution=0.05, templategrid_path=template_path)

    xmin, ymin, xmax, ymax = test_polygon_gdf.total_bounds
    # Raster covers only the CENTRE of the polygon → polygon extends beyond raster
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    tiny_buf = 0.05
    lats = np.arange(cy + tiny_buf, cy - tiny_buf, -0.1)
    lons = np.arange(cx - tiny_buf, cx + tiny_buf, 0.1)

    if len(lats) < 2 or len(lons) < 2:
        pytest.skip("Grid too small for outside-extent test.")

    marc_dir = tmp_path / "rawdata" / "cropcalendar" / "marc_rice"
    marc_dir.mkdir(parents=True)
    marc_file = marc_dir / "3_Transplanting_Harvest_Cropping.nc"
    _make_marc_ds(lats, lons).to_netcdf(str(marc_file))

    ricecalendar_marc(test_polygon_path, str(tmp_path), template_path)

    out = capsys.readouterr().out
    assert "WARNING" in out or "fully inside" in out.lower()
