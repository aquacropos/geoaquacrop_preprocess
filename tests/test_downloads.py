"""
Live-service / download tests for geoaquacrop-preprocess-dev.

These tests hit real external APIs and download actual data.
They are intentionally kept separate and are only executed when the
environment variable RUN_DOWNLOAD_TESTS=1 is set, to avoid slowing
down the standard CI matrix.

In GitHub Actions these run on a single platform + Python version job
that is triggered only when download-related files change (see the
workflow configuration).

Usage:
    RUN_DOWNLOAD_TESTS=1 pytest tests/test_downloads.py -v
"""

import os
import pytest

# Skip the entire module unless explicitly opted in.
pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DOWNLOAD_TESTS", "0") != "1",
    reason="Set RUN_DOWNLOAD_TESTS=1 to run live-service tests",
)

# Mark all tests in this file with the 'download' marker for filtering.
pytestmark = [pytestmark, pytest.mark.download]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_env(name: str) -> str:
    """Return the value of an environment variable or skip the test."""
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"Environment variable {name!r} is not set.")
    return value


# ---------------------------------------------------------------------------
# Soil (ISRIC SoilGrids)
# ---------------------------------------------------------------------------

def test_soil_download(test_polygon_path, tmp_path):
    """Download and preprocessess ISRIC SoilGrids data for the test polygon."""
    from geoaquacrop_preprocess.preprocess_tools import basegrid
    from geoaquacrop_preprocess.soil import soil

    template_path = str(tmp_path / "template_grid.nc")
    to_match, _ = basegrid(test_polygon_path, resolution=0.05, templategrid_path=template_path)

    soil(test_polygon_path, res=0.05, basepath=str(tmp_path),
         templategrid_path=template_path, to_match=to_match)

    output_files = list((tmp_path / "processed").glob("soil_*.nc"))
    assert len(output_files) > 0, "No soil output files were produced."


# ---------------------------------------------------------------------------
# Crop calendar (GGCMI)
# ---------------------------------------------------------------------------

def test_cropcalendar_download(test_polygon_path, tmp_path):
    """Download and preprocessess the GGCMI crop calendar for the test polygon."""
    from geoaquacrop_preprocess.preprocess_tools import basegrid
    from geoaquacrop_preprocess.cropcalendar_module import cropcalendar

    template_path = str(tmp_path / "template_grid.nc")
    to_match, _ = basegrid(test_polygon_path, resolution=0.05, templategrid_path=template_path)

    cropcalendar(test_polygon_path, basepath=str(tmp_path),
                 referenceraster_path=template_path, to_match=to_match)

    output_files = list((tmp_path / "processed").glob("cropcalendar*.nc"))
    assert len(output_files) > 0, "No crop calendar output file was produced."


# ---------------------------------------------------------------------------
# Crop areas (SPAM)
# ---------------------------------------------------------------------------

def test_crop_areas_download(test_polygon_path, tmp_path):
    """Download and preprocessess SPAM crop areas for the test polygon."""
    from geoaquacrop_preprocess.preprocess_tools import basegrid
    from geoaquacrop_preprocess.crop_areas import crop_areas

    template_path = str(tmp_path / "template_grid.nc")
    to_match, _ = basegrid(test_polygon_path, resolution=0.05, templategrid_path=template_path)

    crop_areas(
        domain_path=test_polygon_path,
        spam_variable="physical_area",
        start_year=2009,
        end_year=2011,
        basepath=str(tmp_path),
        to_match=to_match,
    )

    output_files = list((tmp_path / "processed").glob("spam*physical_area*.nc"))
    assert len(output_files) > 0, "No SPAM output file was produced."


# ---------------------------------------------------------------------------
# Climate – NASA NEX-GDDP-CMIP6 (no API token required)
# ---------------------------------------------------------------------------

def test_climate_nasanex_download(test_polygon_path, tmp_path):
    """Download and preprocessess NASA NEX climate data for the test polygon."""
    from geoaquacrop_preprocess.preprocess_tools import basegrid
    from geoaquacrop_preprocess.climate_nasanex import climate_nasanex

    template_path = str(tmp_path / "template_grid.nc")
    to_match, _ = basegrid(test_polygon_path, resolution=0.05, templategrid_path=template_path)

    climate_nasanex(
        basepath=str(tmp_path),
        start_year=2030,
        end_year=2030,
        to_match=to_match,
        model="GFDL-CM4",
        scenario="ssp245",
        ensemble="r1i1p1f1",
    )

    output_files = list((tmp_path / "processed").glob("*.nc"))
    assert len(output_files) > 0, "No NASA NEX output files were produced."


# ---------------------------------------------------------------------------
# Climate – AgERA5 (requires CDS API token)
# ---------------------------------------------------------------------------

def test_climate_agera5_download(test_polygon_path, tmp_path):
    """Download and preprocessess AgERA5 climate data for the test polygon.

    Requires the CDS_API_TOKEN environment variable to be set with a valid
    Copernicus Climate Data Store token.
    """
    api_token = _require_env("CDS_API_TOKEN")

    from geoaquacrop_preprocess.preprocess_tools import basegrid
    from geoaquacrop_preprocess.climate_AgERA5 import climate_AgERA5

    template_path = str(tmp_path / "template_grid.nc")
    to_match, _ = basegrid(test_polygon_path, resolution=0.05, templategrid_path=template_path)

    climate_AgERA5(
        basepath=str(tmp_path),
        start_year=2000,
        end_year=2000,
        api_token=api_token,
        to_match=to_match,
        variables=["MinTemp"],  # test with single variable to keep runtime short
    )

    output_files = list((tmp_path / "processed").glob("MinTemp*.nc"))
    assert len(output_files) > 0, "No AgERA5 output file was produced."
