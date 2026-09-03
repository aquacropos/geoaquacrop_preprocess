"""
Shared pytest fixtures for geoaquacrop-preprocess-dev tests.
"""

import os
import pytest
import geopandas as gpd


TESTS_DIR = os.path.dirname(__file__)
TEST_POLYGON_PATH = os.path.join(TESTS_DIR, "test_polygon.geojson")


@pytest.fixture(scope="session")
def test_polygon_path():
    """Absolute path to the small test polygon (Vietnam ward, EPSG:4326)."""
    return TEST_POLYGON_PATH


@pytest.fixture(scope="session")
def test_polygon_gdf():
    """GeoDataFrame loaded from the test polygon file."""
    return gpd.read_file(TEST_POLYGON_PATH)
