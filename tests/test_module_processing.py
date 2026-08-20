"""
Tests for soil, crop_areas, and cropcalendar processing logic.

Each test pre-populates the expected raw-data directory with synthetic files so
the modules skip their download steps and exercise only the data-processing code.
No network access is required.
"""

import os

import numpy as np
import pytest
import rioxarray  # noqa: F401 – registers .rio accessor
import xarray as xr


# ---------------------------------------------------------------------------
# Shared fixture — template grid from the test polygon
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def template_grid(tmp_path_factory, test_polygon_path):
    """Create a reusable basegrid template for the test polygon."""
    from geoaquacrop_preproc.preproc_tools import basegrid

    tmp = tmp_path_factory.mktemp("template")
    template_path = str(tmp / "template.nc")
    to_match, bounds = basegrid(test_polygon_path, resolution=0.05,
                                templategrid_path=template_path)
    return to_match, bounds, template_path


# ===========================================================================
# soil.py
# ===========================================================================

def _create_synthetic_soilgrids_tifs(soilgrids_dir, test_polygon_gdf):
    """Write minimal GeoTIFF files that mimic an ISRIC SoilGrids download."""
    import rasterio
    from rasterio.transform import from_bounds

    xmin, ymin, xmax, ymax = test_polygon_gdf.total_bounds
    buf = 0.5
    H, W = 8, 8
    transform = from_bounds(xmin - buf, ymin - buf, xmax + buf, ymax + buf, W, H)

    soil_types = ["clay", "sand", "silt", "soc"]
    depth_tags = ["0-5cm", "5-15cm", "15-30cm", "30-60cm", "60-100cm", "100-200cm"]

    for soiltype in soil_types:
        for depth in depth_tags:
            fname = f"{soiltype}_{depth}_mean.tif"
            path = str(soilgrids_dir / fname)
            # Use 200 g/kg = 20% (non-zero so masking by !=0 keeps all values)
            data = np.full((H, W), 200, dtype=np.int16)
            with rasterio.open(
                path, "w", driver="GTiff",
                height=H, width=W, count=1,
                dtype="int16", crs="EPSG:4326",
                transform=transform,
            ) as dst:
                dst.write(data, 1)


def test_soil_processes_synthetic_tifs(test_polygon_path, test_polygon_gdf, tmp_path,
                                        template_grid):
    """soil() with pre-existing tif files skips WCS download and writes NetCDF outputs."""
    from geoaquacrop_preproc.soil import soil

    to_match, _, template_path = template_grid

    soilgrids_dir = tmp_path / "rawdata" / "soilgrids"
    soilgrids_dir.mkdir(parents=True)
    _create_synthetic_soilgrids_tifs(soilgrids_dir, test_polygon_gdf)

    # Call soil() — presence of ≥6 tifs per soil type triggers the skip-download path
    soil(test_polygon_path, 0.05, str(tmp_path), template_path,
         mask=test_polygon_gdf, to_match=to_match)

    processed_dir = tmp_path / "processed"
    output_files = sorted(processed_dir.glob("soil_*.nc"))
    assert len(output_files) == 6, (
        f"Expected 6 soil NetCDF files (one per depth), found {len(output_files)}"
    )


def test_soil_output_contains_expected_variables(test_polygon_path, test_polygon_gdf,
                                                   tmp_path, template_grid):
    """Each output soil file should contain Clay, Sand, Silt, and Som variables."""
    from geoaquacrop_preproc.soil import soil

    to_match, _, template_path = template_grid

    soilgrids_dir = tmp_path / "rawdata" / "soilgrids"
    soilgrids_dir.mkdir(parents=True)
    _create_synthetic_soilgrids_tifs(soilgrids_dir, test_polygon_gdf)

    soil(test_polygon_path, 0.05, str(tmp_path), template_path,
         mask=test_polygon_gdf, to_match=to_match)

    output_files = sorted((tmp_path / "processed").glob("soil_*.nc"))
    assert output_files, "No soil output files were created."

    result = xr.open_dataset(str(output_files[0]))
    for var in ("Clay", "Sand", "Silt", "Som"):
        assert var in result.data_vars, f"Variable '{var}' missing from {output_files[0].name}"
    result.close()


def test_soil_skips_existing_output_file(test_polygon_path, test_polygon_gdf,
                                          tmp_path, template_grid):
    """soil() should skip depth layers whose output files already exist."""
    from geoaquacrop_preproc.soil import soil

    to_match, _, template_path = template_grid

    soilgrids_dir = tmp_path / "rawdata" / "soilgrids"
    soilgrids_dir.mkdir(parents=True)
    _create_synthetic_soilgrids_tifs(soilgrids_dir, test_polygon_gdf)

    # Pre-create one output file as a sentinel
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    sentinel = processed_dir / "soil_0-5cm.nc"
    sentinel.write_text("placeholder")

    # Should not raise and should leave sentinel intact
    soil(test_polygon_path, 0.05, str(tmp_path), template_path,
         mask=test_polygon_gdf, to_match=to_match)

    assert sentinel.read_text() == "placeholder", "Existing output was overwritten."


# ===========================================================================
# crop_areas.py
# ===========================================================================

def _create_synthetic_spam_tifs(spam_unzipped_dir, test_polygon_gdf, refyear,
                                  spam_variable, crops=None):
    """Create minimal SPAM GeoTIFFs inside the pre-unzipped directory."""
    import rasterio
    from rasterio.transform import from_bounds

    xmin, ymin, xmax, ymax = test_polygon_gdf.total_bounds
    buf = 0.5
    H, W = 8, 8
    transform = from_bounds(xmin - buf, ymin - buf, xmax + buf, ymax + buf, W, H)

    if crops is None:
        crops = [("MAIZ", "R"), ("MAIZ", "I"), ("BARL", "R")]

    var_abbrev = "phys_area" if spam_variable == "physical_area" else spam_variable
    for crop, tech in crops:
        fname = f"spam{refyear}V1r0_global_{var_abbrev}_{crop}_{tech}.tif"
        path = str(spam_unzipped_dir / fname)
        data = np.full((H, W), 50.0, dtype=np.float32)
        with rasterio.open(
            path, "w", driver="GTiff",
            height=H, width=W, count=1,
            dtype="float32", crs="EPSG:4326",
            transform=transform,
        ) as dst:
            dst.write(data, 1)


def test_crop_areas_physical_area(test_polygon_path, test_polygon_gdf, tmp_path,
                                   template_grid):
    """crop_areas() with a pre-unzipped spam dir should produce a processed NetCDF."""
    from geoaquacrop_preproc.crop_areas import crop_areas

    to_match, _, _ = template_grid

    # Determine the refyear and pre-create the unzipped directory
    from geoaquacrop_preproc.preproc_tools import spam_refyear, makedirs
    refyear = spam_refyear(2020, 2030)   # → '2020'
    target_dir = makedirs(str(tmp_path), "rawdata", "cropmasks")
    spam_unzipped_dir = tmp_path / "rawdata" / "cropmasks" / f"spam{refyear}_physical_area"
    spam_unzipped_dir.mkdir(parents=True)
    _create_synthetic_spam_tifs(spam_unzipped_dir, test_polygon_gdf, refyear, "physical_area")

    crop_areas(test_polygon_path, "physical_area", 2020, 2030, str(tmp_path), to_match,
               mask=test_polygon_gdf)

    outfile = tmp_path / "processed" / f"spam{refyear}_physical_area.nc"
    assert outfile.exists(), f"Expected output at {outfile}"
    result = xr.open_dataset(str(outfile))
    assert "Maize_rf_physical_area" in result.data_vars
    result.close()


def test_crop_areas_skips_processing_when_output_exists(test_polygon_path, test_polygon_gdf,
                                                          tmp_path, template_grid):
    """crop_areas() should skip processing if the target NetCDF already exists."""
    from geoaquacrop_preproc.crop_areas import crop_areas
    from geoaquacrop_preproc.preproc_tools import spam_refyear, makedirs

    to_match, _, _ = template_grid
    refyear = spam_refyear(2020, 2030)

    # Pre-create unzipped dir and the processed output
    spam_unzipped_dir = tmp_path / "rawdata" / "cropmasks" / f"spam{refyear}_physical_area"
    spam_unzipped_dir.mkdir(parents=True)
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir(parents=True)
    sentinel = processed_dir / f"spam{refyear}_physical_area.nc"
    sentinel.write_text("already_there")

    # Should skip processing and leave sentinel intact
    crop_areas(test_polygon_path, "physical_area", 2020, 2030, str(tmp_path), to_match,
               mask=test_polygon_gdf)

    assert sentinel.read_text() == "already_there"


# ===========================================================================
# cropcalendar_module.py
# ===========================================================================

def _create_synthetic_ggcmi_nc4(path, lats, lons, planting_val=90, gsl_val=120):
    """Create a minimal synthetic GGCMI crop-calendar NC4 file."""
    H, W = len(lats), len(lons)
    ds = xr.Dataset({
        "planting_day": xr.DataArray(
            np.full((H, W), float(planting_val), dtype=np.float32),
            dims=["lat", "lon"], coords={"lat": lats, "lon": lons},
        ),
        "growing_season_length": xr.DataArray(
            np.full((H, W), float(gsl_val), dtype=np.float32),
            dims=["lat", "lon"], coords={"lat": lats, "lon": lons},
        ),
        "maturity_day": xr.DataArray(
            np.full((H, W), float(planting_val + gsl_val), dtype=np.float32),
            dims=["lat", "lon"], coords={"lat": lats, "lon": lons},
        ),
        "data_source_used": xr.DataArray(
            np.zeros((H, W), dtype=np.float32),
            dims=["lat", "lon"], coords={"lat": lats, "lon": lons},
        ),
    })
    # Save as NetCDF4 (used as a .nc4 file)
    ds.to_netcdf(path, format="NETCDF4")


def test_cropcalendar_processes_synthetic_nc4_files(test_polygon_path, test_polygon_gdf,
                                                      tmp_path, template_grid):
    """cropcalendar() with a pre-unzipped ggcmi dir should produce cropcalendar.nc."""
    from geoaquacrop_preproc.cropcalendar_module import cropcalendar

    to_match, _, template_path = template_grid

    xmin, ymin, xmax, ymax = test_polygon_gdf.total_bounds
    buf = 1.0
    lats = np.arange(ymax + buf, ymin - buf, -0.5)
    lons = np.arange(xmin - buf, xmax + buf, 0.5)

    # Pre-create the unzipped directory (bypasses download step)
    ggcmi_dir = tmp_path / "rawdata" / "cropcalendar" / "ggcmi_cropcalendar"
    ggcmi_dir.mkdir(parents=True)

    # Create two synthetic crop calendar files
    # Filename convention: {crop_id}_{tech}_ggcmi_crop_calendar_phase3_v1.01.nc4  (43 chars total)
    # cropID = fname[-43:-40], technique = fname[-39:-37]
    for crop_id, tech in [("mai", "rf"), ("bar", "rf")]:
        fname = f"{crop_id}_{tech}_ggcmi_crop_calendar_phase3_v1.01.nc4"
        assert len(fname) == 43, f"Filename length mismatch: {len(fname)}"
        _create_synthetic_ggcmi_nc4(str(ggcmi_dir / fname), lats, lons)

    cropcalendar(test_polygon_path, str(tmp_path), template_path,
                 mask=test_polygon_gdf, to_match=to_match)

    outfile = tmp_path / "processed" / "cropcalendar.nc"
    assert outfile.exists(), "cropcalendar.nc was not created."

    result = xr.open_dataset(str(outfile))
    # Expect Maize_rf_planting and Barley_rf_planting
    assert any("planting" in v for v in result.data_vars), \
        f"No planting variable found in {list(result.data_vars)}"
    assert any("growing_season_length" in v for v in result.data_vars), \
        f"No growing_season_length variable found in {list(result.data_vars)}"
    result.close()


def test_cropcalendar_output_planting_range(test_polygon_path, test_polygon_gdf,
                                              tmp_path, template_grid):
    """Planting day values in output should be in [1, 366] (day of year)."""
    from geoaquacrop_preproc.cropcalendar_module import cropcalendar

    to_match, _, template_path = template_grid

    xmin, ymin, xmax, ymax = test_polygon_gdf.total_bounds
    buf = 1.0
    lats = np.arange(ymax + buf, ymin - buf, -0.5)
    lons = np.arange(xmin - buf, xmax + buf, 0.5)

    ggcmi_dir = tmp_path / "rawdata" / "cropcalendar" / "ggcmi_cropcalendar"
    ggcmi_dir.mkdir(parents=True)

    fname = "mai_rf_ggcmi_crop_calendar_phase3_v1.01.nc4"
    _create_synthetic_ggcmi_nc4(str(ggcmi_dir / fname), lats, lons,
                                  planting_val=90, gsl_val=120)

    cropcalendar(test_polygon_path, str(tmp_path), template_path,
                 mask=test_polygon_gdf, to_match=to_match)

    result = xr.open_dataset(str(tmp_path / "processed" / "cropcalendar.nc"))
    planting_vars = [v for v in result.data_vars if "planting" in v]
    assert planting_vars, "No planting variable found."
    vals = result[planting_vars[0]].values
    non_nan = vals[~np.isnan(vals)]
    if len(non_nan) > 0:
        assert np.all(non_nan >= 1) and np.all(non_nan <= 366), \
            f"Planting day out of [1, 366] range: min={non_nan.min()}, max={non_nan.max()}"
    result.close()
