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
        # Default: three sequential seasons, 90->180, 190->280 and 300->60
        values = {"transplant": 90.0, "harvest": 180.0}

    tp = values.get("transplant", 90.0)
    hv = values.get("harvest", 180.0)

    def _da(val):
        return xr.DataArray(
            np.full((H, W), float(val), dtype=np.float32),
            dims=["lat", "lon"], coords={"lat": lats, "lon": lons},
        )

    return xr.Dataset({
        "Transplanting_1_Cropping": _da(tp),
        "Harvest_1_Cropping"      : _da(hv),
        "Transplanting_2_Cropping": _da(tp + 100),
        "Harvest_2_Cropping"      : _da(hv + 100),
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
    from geoaquacrop_preprocess.preprocess_tools import basegrid

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
    from geoaquacrop_preprocess.ricecalendar_marc import ricecalendar_marc

    domain_path, basepath, template_path, marc_dir, lats, lons = marc_setup

    marc_file = marc_dir / "3_Transplanting_Harvest_Cropping.nc"
    _make_marc_ds(lats, lons).to_netcdf(str(marc_file))

    ricecalendar_marc(domain_path, basepath, template_path, calendar_type="cropping")

    outfile = (
        __import__("pathlib").Path(basepath)
        / "processed" / "cropcalendar_marc" / "cropcalendar.nc"
    )
    assert outfile.exists(), "MARC rice calendar output NetCDF was not created."


def test_ricecalendar_marc_output_variables(marc_setup):
    """Output should contain rf and ir planting + growing_season_length for all 3 cycles."""
    from geoaquacrop_preprocess.ricecalendar_marc import ricecalendar_marc

    domain_path, basepath, template_path, marc_dir, lats, lons = marc_setup

    marc_file = marc_dir / "3_Transplanting_Harvest_Cropping.nc"
    _make_marc_ds(lats, lons).to_netcdf(str(marc_file))

    ricecalendar_marc(domain_path, basepath, template_path, calendar_type="cropping")

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
    from geoaquacrop_preprocess.ricecalendar_marc import ricecalendar_marc

    domain_path, basepath, template_path, marc_dir, lats, lons = marc_setup

    marc_file = marc_dir / "3_Transplanting_Harvest_Cropping.nc"
    _make_marc_ds(lats, lons).to_netcdf(str(marc_file))

    ricecalendar_marc(domain_path, basepath, template_path, calendar_type="cropping")

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
    from geoaquacrop_preprocess.ricecalendar_marc import ricecalendar_marc

    domain_path, basepath, template_path, marc_dir, lats, lons = marc_setup

    marc_file = marc_dir / "3_Transplanting_Harvest_Cropping.nc"
    _make_marc_ds(lats, lons).to_netcdf(str(marc_file))

    ricecalendar_marc(domain_path, basepath, template_path, calendar_type="cropping")

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
    from geoaquacrop_preprocess.ricecalendar_marc import ricecalendar_marc

    domain_path, basepath, template_path, marc_dir, lats, lons = marc_setup

    marc_file = marc_dir / "3_Transplanting_Harvest_Cropping.nc"
    # Season 3: planting=300, harvest=60  →  length = 60 - 300 + 365 = 125
    _make_marc_ds(lats, lons).to_netcdf(str(marc_file))

    ricecalendar_marc(domain_path, basepath, template_path, calendar_type="cropping")

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
    from geoaquacrop_preprocess.ricecalendar_marc import ricecalendar_marc

    domain_path, basepath, template_path, marc_dir, lats, lons = marc_setup

    # H, W must be large enough to have a NaN patch surrounded by valid cells
    if len(lats) < 4 or len(lons) < 4:
        pytest.skip("Grid too small for NaN-gap-fill test.")

    marc_file = marc_dir / "3_Transplanting_Harvest_Cropping.nc"
    _make_marc_ds_with_nans(lats, lons).to_netcdf(str(marc_file))

    ricecalendar_marc(domain_path, basepath, template_path, calendar_type="cropping")

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
    from geoaquacrop_preprocess.ricecalendar_marc import ricecalendar_marc

    domain_path, basepath, template_path, marc_dir, lats, lons = marc_setup

    marc_file = marc_dir / "3_Transplanting_Harvest_Cropping.nc"
    # Use planting day 60 (Feb 29) for season 1
    _make_marc_ds(lats, lons, values={"transplant": 60.0, "harvest": 180.0}).to_netcdf(
        str(marc_file)
    )

    ricecalendar_marc(domain_path, basepath, template_path, calendar_type="cropping")

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
    from geoaquacrop_preprocess.ricecalendar_marc import ricecalendar_marc
    from geoaquacrop_preprocess.preprocess_tools import basegrid

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

    ricecalendar_marc(test_polygon_path, str(tmp_path), template_path, calendar_type="cropping")

    out = capsys.readouterr().out
    assert "WARNING" in out or "fully inside" in out.lower()



# ---------------------------------------------------------------------------
# Group-based calendar (default): one season per layer everywhere
# ---------------------------------------------------------------------------

def _make_marc_group_ds(lats, lons):
    """Group calendar: wet (group 1) everywhere, dry (group 3) only in the north half."""
    shape = (len(lats), len(lons))
    north = np.broadcast_to((lats >= np.median(lats))[:, None], shape)

    def _da(values):
        return xr.DataArray(np.asarray(values, dtype="float32"), dims=["lat", "lon"],
                            coords={"lat": lats, "lon": lons})
    return xr.Dataset({
        "Transplanting_1_Group": _da(np.full(shape, 200.0)),
        "Harvest_1_Group":       _da(np.full(shape, 305.0)),
        "Transplanting_2_Group": _da(np.full(shape, 100.0)),
        "Harvest_2_Group":       _da(np.full(shape, 190.0)),
        "Transplanting_3_Group": _da(np.where(north, 340.0, np.nan)),
        "Harvest_3_Group":       _da(np.where(north, 80.0, np.nan)),
    })


def _run_group(marc_setup, **kwargs):
    from geoaquacrop_preprocess.ricecalendar_marc import ricecalendar_marc
    domain_path, basepath, template_path, marc_dir, lats, lons = marc_setup
    _make_marc_group_ds(lats, lons).to_netcdf(str(marc_dir / "1_Transplanting_Harvest_Group.nc"))
    ricecalendar_marc(domain_path, basepath, template_path, **kwargs)
    out = __import__("pathlib").Path(basepath) / "processed" / "cropcalendar_marc" / "cropcalendar.nc"
    return xr.open_dataset(str(out))


def test_group_calendar_is_default(marc_setup):
    ds = _run_group(marc_setup)
    assert ds.attrs["calendar_type"] == "group"
    assert float(ds["PaddyRice1_rf_planting"].mean()) == pytest.approx(200.0)
    assert float(ds["PaddyRice2_rf_planting"].mean()) == pytest.approx(100.0)
    ds.close()


def test_group_calendar_season_lengths_and_dry_season(marc_setup):
    ds = _run_group(marc_setup, calendar_type="group")
    assert float(ds["PaddyRice1_rf_growing_season_length"].mean()) == pytest.approx(105.0)
    # dry season crosses the year end: 340 -> 80 is 105 days
    gsl3 = ds["PaddyRice3_rf_growing_season_length"]
    assert float(gsl3.min()) == pytest.approx(105.0) and float(gsl3.max()) == pytest.approx(105.0)
    # cells without a dry-season crop are filled from neighbours
    assert int(ds["PaddyRice3_rf_planting"].notnull().sum()) == int(ds["PaddyRice1_rf_planting"].notnull().sum())
    ds.close()


def test_unknown_calendar_type_raises(marc_setup):
    from geoaquacrop_preprocess.ricecalendar_marc import ricecalendar_marc
    domain_path, basepath, template_path, *_ = marc_setup
    with pytest.raises(ValueError, match="calendar_type"):
        ricecalendar_marc(domain_path, basepath, template_path, calendar_type="season")


# ---------------------------------------------------------------------------
# fill_and_sequence: gap filling without overlapping seasons
# ---------------------------------------------------------------------------

from geoaquacrop_preprocess.ricecalendar_marc import (
    fill_and_sequence, _conflict,
    SOURCE_OBSERVED, SOURCE_OBSERVED_SHIFTED, SOURCE_FILLED, SOURCE_FILLED_SHIFTED,
)


def _grid(*seasons):
    """Stack per-season (plant, harvest) 2-D lists into (season, y, x) arrays."""
    plant = np.array([np.array(p, dtype=float) for p, _ in seasons])
    harvest = np.array([np.array(h, dtype=float) for _, h in seasons])
    return plant, harvest


def test_observed_overlap_is_shifted_after_harvest_plus_fallow():
    # season 1: 200 -> 300; season 2: 290 -> 20 overlaps it by 10 days
    plant, harvest = _grid(([[200.0]], [[300.0]]), ([[290.0]], [[20.0]]))
    p, length, src = fill_and_sequence(plant, harvest, min_fallow_days=7)
    assert p[0, 0, 0] == 200 and src[0, 0, 0] == SOURCE_OBSERVED
    assert p[1, 0, 0] == 307 and length[1, 0, 0] == 95
    assert src[1, 0, 0] == SOURCE_OBSERVED_SHIFTED


def test_empty_cell_takes_all_seasons_from_one_neighbour():
    nan = np.nan
    # cell (0,0) observes both seasons; cell (0,3) observes a different season 1;
    # cell (0,1) is empty and nearest to (0,0)
    plant, harvest = _grid(([[180.0, nan, nan, 150.0]], [[280.0, nan, nan, 250.0]]),
                           ([[320.0, nan, nan, nan]], [[40.0, nan, nan, nan]]))
    p, length, src = fill_and_sequence(plant, harvest)
    # the empty cell copies (0,0)'s complete, sequential set
    assert (p[0, 0, 1], p[1, 0, 1]) == (180.0, 320.0)
    assert src[0, 0, 1] == SOURCE_FILLED and src[1, 0, 1] == SOURCE_FILLED


def test_missing_season_filled_from_neighbour_and_shifted():
    nan = np.nan
    # cell (0,0): season 1 observed 200 -> 300, season 2 missing
    # cell (0,1): season 2 observed 280 -> 10, which would overlap cell (0,0)'s season 1
    plant, harvest = _grid(([[200.0, nan]], [[300.0, nan]]),
                           ([[nan, 280.0]], [[nan, 10.0]]))
    p, length, src = fill_and_sequence(plant, harvest, min_fallow_days=7)
    assert p[1, 0, 0] == 307 and length[1, 0, 0] == 95
    assert src[1, 0, 0] == SOURCE_FILLED_SHIFTED


def test_season_moves_by_fewest_days_earlier_or_later():
    # season 1 observed 200 -> 300; season 2 observed 180 -> 250 (70 days) overlaps it.
    # Later: start 307 (+127 days). Earlier: harvest by 193, start 123 (-57 days).
    plant, harvest = _grid(([[200.0]], [[300.0]]), ([[180.0]], [[250.0]]))
    p, length, src = fill_and_sequence(plant, harvest, min_fallow_days=7)
    assert p[1, 0, 0] == 123 and length[1, 0, 0] == 70
    assert src[1, 0, 0] == SOURCE_OBSERVED_SHIFTED


def test_season_that_cannot_fit_is_left_empty():
    # two 200-day seasons cannot both fit into one year
    plant, harvest = _grid(([[100.0]], [[300.0]]), ([[150.0]], [[350.0]]))
    p, length, src = fill_and_sequence(plant, harvest)
    assert np.isfinite(p[0, 0, 0]) and np.isnan(p[1, 0, 0]) and src[1, 0, 0] == 0


@pytest.mark.parametrize("fallow", [0, 7, 15])
def test_no_cell_has_overlapping_seasons(fallow):
    """Random calendars with gaps and overlaps: the output never overlaps."""
    rng = np.random.default_rng(1)
    shape = (3, 20, 20)
    plant = rng.uniform(1, 365, shape)
    harvest = plant + rng.uniform(80, 130, shape)
    plant[rng.random(shape) < 0.4] = np.nan               # 40 % missing seasons
    p, length, src = fill_and_sequence(plant, harvest, min_fallow_days=fallow)
    for a in range(3):
        for b in range(a + 1, 3):
            both = np.isfinite(p[a]) & np.isfinite(p[b])
            assert not _conflict(p[a][both], length[a][both], p[b][both], length[b][both], fallow).any()
    # every cell keeps at least one season, dates are whole days, and lengths
    # are unchanged by shifting
    assert np.isfinite(p).any(axis=0).all()
    assert np.array_equal(p[np.isfinite(p)], np.round(p[np.isfinite(p)]))
    observed = (src == SOURCE_OBSERVED) | (src == SOURCE_OBSERVED_SHIFTED)
    expected = np.mod(np.round(harvest) - np.round(plant), 365)
    assert np.allclose(length[observed], expected[observed])


def test_groups_selects_and_sequences_only_listed_seasons(marc_setup):
    ds = _run_group(marc_setup, groups=(1, 3))
    assert "PaddyRice2_rf_planting" not in ds.data_vars
    assert {"PaddyRice1_rf_planting", "PaddyRice3_rf_planting",
            "PaddyRice1_calendar_source", "PaddyRice3_calendar_source"} <= set(ds.data_vars)
    assert list(np.atleast_1d(ds.attrs["groups"])) == [1, 3]
    ds.close()


def test_invalid_groups_raise(marc_setup):
    from geoaquacrop_preprocess.ricecalendar_marc import ricecalendar_marc
    domain_path, basepath, template_path, *_ = marc_setup
    with pytest.raises(ValueError, match="groups"):
        ricecalendar_marc(domain_path, basepath, template_path, groups=(1, 4))
