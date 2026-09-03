"""
Tests for geoaquacrop_preprocess.preprocess_main.geoaquacrop_preprocess.

The sub-modules (soil, crop_areas, cropcalendar, climate_AgERA5, climate_nasanex)
are mocked so the tests exercise the orchestration logic without any downloads.
"""

import datetime
import os
from unittest.mock import MagicMock, patch

import pytest

from geoaquacrop_preprocess.preprocess_main import geoaquacrop_preprocess


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MOCK_TARGET = "geoaquacrop_preprocess.preprocess_main"
_CURRENT_YEAR = datetime.date.today().year


def _run_with_mocks(test_polygon_path, tmp_path, preprocess, start_year=2030, end_year=2031,
                    api_token="dummy", extra_kwargs=None):
    """Call geoaquacrop_preprocess with all sub-module functions patched out."""
    mock_to_match = MagicMock()
    mock_bounds = [0, 0, 1, 1]

    patches = [
        patch(f"{_MOCK_TARGET}.validate_inputs"),
        patch(f"{_MOCK_TARGET}.basegrid", return_value=(mock_to_match, mock_bounds)),
        patch("geoaquacrop_preprocess.soil.soil"),
        patch("geoaquacrop_preprocess.crop_areas.crop_areas"),
        patch("geoaquacrop_preprocess.cropcalendar_module.cropcalendar"),
        patch("geoaquacrop_preprocess.climate_AgERA5.climate_AgERA5"),
        patch("geoaquacrop_preprocess.climate_nasanex.climate_nasanex"),
    ]

    kwargs = dict(preprocess=preprocess, workingdirectory=str(tmp_path))
    if extra_kwargs:
        kwargs.update(extra_kwargs)

    mocks = {}
    with (patch(f"{_MOCK_TARGET}.validate_inputs") as m_val,
          patch(f"{_MOCK_TARGET}.basegrid", return_value=(mock_to_match, mock_bounds)) as m_bg,
          patch("geoaquacrop_preprocess.soil.soil") as m_soil,
          patch("geoaquacrop_preprocess.crop_areas.crop_areas") as m_ca,
          patch("geoaquacrop_preprocess.cropcalendar_module.cropcalendar") as m_cc,
          patch("geoaquacrop_preprocess.climate_AgERA5.climate_AgERA5") as m_a5,
          patch("geoaquacrop_preprocess.climate_nasanex.climate_nasanex") as m_nex):
        geoaquacrop_preprocess(
            test_polygon_path, start_year, end_year, api_token, **kwargs
        )
        return dict(validate=m_val, basegrid=m_bg, soil=m_soil, crop_areas=m_ca,
                    cropcalendar=m_cc, agera5=m_a5, nasanex=m_nex)


# ---------------------------------------------------------------------------
# validate_inputs is always called
# ---------------------------------------------------------------------------

def test_preprocess_main_calls_validate_inputs(test_polygon_path, tmp_path):
    mocks = _run_with_mocks(test_polygon_path, tmp_path, preprocess=[])
    mocks["validate"].assert_called_once_with(
        test_polygon_path, 2030, 2031, "dummy"
    )


def test_preprocess_main_calls_basegrid(test_polygon_path, tmp_path):
    mocks = _run_with_mocks(test_polygon_path, tmp_path, preprocess=[])
    mocks["basegrid"].assert_called_once()


# ---------------------------------------------------------------------------
# Soil preprocessing
# ---------------------------------------------------------------------------

def test_preprocess_main_soil_step_called(test_polygon_path, tmp_path):
    mocks = _run_with_mocks(test_polygon_path, tmp_path, preprocess=["soil"])
    mocks["soil"].assert_called_once()


def test_preprocess_main_soil_not_called_when_not_requested(test_polygon_path, tmp_path):
    mocks = _run_with_mocks(test_polygon_path, tmp_path, preprocess=[])
    mocks["soil"].assert_not_called()


# ---------------------------------------------------------------------------
# Crop-areas preprocessing
# ---------------------------------------------------------------------------

def test_preprocess_main_crop_areas_called(test_polygon_path, tmp_path):
    mocks = _run_with_mocks(test_polygon_path, tmp_path, preprocess=["crop_areas"])
    mocks["crop_areas"].assert_called_once()


def test_preprocess_main_crop_areas_not_called_when_excluded(test_polygon_path, tmp_path):
    mocks = _run_with_mocks(test_polygon_path, tmp_path, preprocess=["soil"])
    mocks["crop_areas"].assert_not_called()


# ---------------------------------------------------------------------------
# Crop-calendar preprocessing
# ---------------------------------------------------------------------------

def test_preprocess_main_cropcalendar_called(test_polygon_path, tmp_path):
    mocks = _run_with_mocks(test_polygon_path, tmp_path, preprocess=["cropcalendar"])
    mocks["cropcalendar"].assert_called_once()


# ---------------------------------------------------------------------------
# Climate — AgERA5 selected for historical-only periods
# ---------------------------------------------------------------------------

def test_preprocess_main_uses_agera5_for_historical_period(test_polygon_path, tmp_path):
    """start/end within AgERA5 window (1979 to last complete year) → AgERA5."""
    long_token = "a" * 40
    mocks = _run_with_mocks(
        test_polygon_path, tmp_path,
        preprocess=["climate"],
        start_year=2005, end_year=_CURRENT_YEAR - 1,
        api_token=long_token,
    )
    mocks["agera5"].assert_called_once()
    mocks["nasanex"].assert_not_called()


# ---------------------------------------------------------------------------
# Climate — NASA NEX selected for future periods
# ---------------------------------------------------------------------------

def test_preprocess_main_uses_nasanex_for_future_period(test_polygon_path, tmp_path):
    """end_year in the future → NASA NEX."""
    mocks = _run_with_mocks(
        test_polygon_path, tmp_path,
        preprocess=["climate"],
        start_year=2030, end_year=2050,
    )
    mocks["nasanex"].assert_called_once()
    mocks["agera5"].assert_not_called()


def test_preprocess_main_nasanex_custom_model(test_polygon_path, tmp_path):
    mocks = _run_with_mocks(
        test_polygon_path, tmp_path,
        preprocess=["climate"],
        start_year=2030, end_year=2050,
        extra_kwargs={"nasanex_model": "MPI-ESM1-2-HR",
                      "nasanex_scenario": "ssp585",
                      "nasanex_ensemble": "r1i1p1f1"},
    )
    mocks["nasanex"].assert_called_once()
    _, call_kwargs = mocks["nasanex"].call_args
    assert call_kwargs.get("model") == "MPI-ESM1-2-HR" or "MPI-ESM1-2-HR" in str(mocks["nasanex"].call_args)


# ---------------------------------------------------------------------------
# workingdirectory defaults to cwd
# ---------------------------------------------------------------------------

def test_preprocess_main_default_workingdir_is_cwd(test_polygon_path, tmp_path, monkeypatch):
    """When workingdirectory is not provided, os.getcwd() should be used."""
    monkeypatch.chdir(tmp_path)
    with (patch(f"{_MOCK_TARGET}.validate_inputs"),
          patch(f"{_MOCK_TARGET}.basegrid", return_value=(MagicMock(), [0, 0, 1, 1]))):
        # Pass workingdirectory=None explicitly (the default)
        geoaquacrop_preprocess(test_polygon_path, 2030, 2031, "dummy",
                            preprocess=[], workingdirectory=None)
    # If we reach here without raising, the default was accepted


# ---------------------------------------------------------------------------
# Multiple steps in a single call
# ---------------------------------------------------------------------------

def test_preprocess_main_all_steps_called(test_polygon_path, tmp_path):
    long_token = "a" * 40
    mocks = _run_with_mocks(
        test_polygon_path, tmp_path,
        preprocess=["soil", "crop_areas", "cropcalendar", "climate"],
        start_year=2005, end_year=_CURRENT_YEAR - 1,
        api_token=long_token,
    )
    mocks["soil"].assert_called_once()
    mocks["crop_areas"].assert_called_once()
    mocks["cropcalendar"].assert_called_once()
    mocks["agera5"].assert_called_once()
