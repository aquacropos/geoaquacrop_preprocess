"""
GeoAquaCrop preprocessing pipeline — main entry point.

Takes user-defined inputs (domain polygon, time period, resolution, and API
credentials) and downloads and prepares all datasets needed to run GeoAquaCrop.

Required inputs:

- Path to a vector polygon file (GeoJSON or shapefile) representing the model
  domain (EPSG:4326).
- Time period to model: ``start_year`` and ``end_year``.
- Desired cell resolution in decimal degrees (default 0.05° ≈ 3 arcmin). Higher resolution may be possible for smaller domains, but keep in mind that the spatial resolution of most input datasets is quite coarse (e.g. 0.25 degrees for future climate data), so higher resolution may not always be useful and may lead to longer processing times and larger file sizes.
- Copernicus CDS API token (only required for AgERA5 past climate data).

Generated output datasets:

- **Climate** — daily precipitation, reference ET, minimum and maximum
  temperature. Source is selected automatically:

  - Both years in the past (< current year): AgERA5 reanalysis via Copernicus CDS.
  - ``end_year`` in the future (≥ current year): NASA NEX-GDDP-CMIP6 projections.

- **Soil** — clay, sand, silt, and soil organic matter for six depth layers
  (ISRIC SoilGrids).
- **Crop calendar** — planting day and growing season length for all supported
  crop types (GGCMI).
- **Crop areas** — cultivated areas per crop type and irrigation mode (SPAM).
"""

import os
import geopandas as gpd
from .preproc_tools import basegrid
from .validate_inputs import validate_inputs
# import pdb

## INPUT ARGUMENTS. REPLACE THESE WITH YOUR OWN VALUES
# Output directory: all rawdata and processed files are written here
workingdirectory = '/Users/ritterj1/PythonProjects/geoaquacrop-preproc-dev'
# Domain: absolute path so the script can be run from any directory
domain_path = '/Users/ritterj1/PythonProjects/geoaquacrop-preproc-dev/tests/test_polygon.geojson'
#domain_path = os.path.join(os.getcwd(), 'inputdata', 'mekong', 'basin_outline', 'mekong_jrc_outline.geojson')
start_year = 2030
end_year = 2031
cell_resolution = 0.05 # cell resolution in degrees (e.g. 0.05 for 3 arcmin). Resolution of 0.05 degrees is reasonable given the coarse spatial resolution of most input datasets.
api_token = 'xxx'  # your API token when using AgERA5 as climate input, retrieved from your profile page on the Copernicus Climate Data Store (https://cds.climate.copernicus.eu/)

# NASA NEX-GDDP-CMIP6 settings (used for climate projection inputs when end_year >= current year)
nasanex_model    = 'GFDL-CM4'   # CMIP6 model; see https://ds.nccs.nasa.gov/thredds/catalog/AMES/NEX/GDDP-CMIP6/catalog.html
nasanex_scenario = 'ssp245'     # SSP scenario for years >= 2015: 'ssp126', 'ssp245', 'ssp370', 'ssp585'
nasanex_ensemble = 'r1i1p1f1'   # ensemble member (check catalog for model-specific members)

##
def geoaquacrop_preproc(domain_shape_path, start_year, end_year, api_token, cell_resolution=0.05, preprocess=['soil', 'crop_areas', 'cropcalendar', 'climate'],
                        nasanex_model='GFDL-CM4', nasanex_scenario='ssp245', nasanex_ensemble='r1i1p1f1', workingdirectory=None):
    """Run the full GeoAquaCrop preprocessing pipeline.

    Downloads and preprocesses all input datasets required to run FAO AquaCrop
    over large regions in gridded format for the specified domain and time period.
    The climate source is selected automatically: AgERA5 reanalysis is used when
    both years fall within its availability window (1979 to the previous complete
    year), otherwise NASA NEX-GDDP-CMIP6 projections are used.

    Args:
        domain_shape_path (str): Path to a GeoJSON or shapefile polygon defining
            the model domain. Must be in EPSG:4326 and contain only Polygon or
            MultiPolygon geometries.
        start_year (int): First year of the modelling period.
        end_year (int): Last year of the modelling period (inclusive).
        api_token (str): Personal API token from the Copernicus Climate Data
            Store (https://cds.climate.copernicus.eu/). Required only when the
            period falls within AgERA5 availability (1979 to last complete year).
        cell_resolution (float): Output grid resolution in decimal degrees.
            Default is ``0.05`` (≈ 3 arcmin). Note that most input datasets have
            a coarser native resolution (e.g. 0.25° for NASA NEX climate data),
            so increasing this beyond the native resolution has limited benefit.
        preprocess (list[str]): Preprocessing steps to execute. Any subset of
            ``['soil', 'crop_areas', 'cropcalendar', 'climate']``.
        nasanex_model (str): CMIP6 model name used when downloading NASA
            NEX-GDDP-CMIP6 projections. Default ``'GFDL-CM4'``.
        nasanex_scenario (str): SSP scenario for years >= 2015. One of
            ``'ssp126'``, ``'ssp245'``, ``'ssp370'``, ``'ssp585'``.
            Default ``'ssp245'``.
        nasanex_ensemble (str): Ensemble member identifier for the selected
            CMIP6 model. Default ``'r1i1p1f1'``.
        workingdirectory (str, optional): Root directory for all raw and
            processed output. Defaults to the current working directory.
    """
    if workingdirectory is None:
        workingdirectory = os.getcwd()

    # Validate user inputs
    validate_inputs(domain_shape_path, start_year, end_year, api_token)

    # Read domain mask GeoDataFrame once; shared by all preprocessing modules to avoid repeated file I/O
    mask = gpd.read_file(domain_shape_path)

    # Create template raster file from domain shape for all other datasets to align
    templategrid_path = os.path.join(workingdirectory, 'template_grid.nc')
    to_match, bounds = basegrid(domain_shape_path, cell_resolution, templategrid_path)

    # Download and preprocess soil data from ISRIC Soilgrids
    if 'soil' in preprocess:
        from .soil import soil
        soil(domain_shape_path, cell_resolution, workingdirectory, templategrid_path, mask=mask, to_match=to_match)

    # Download and preprocess crop areas (crop mask) and crop yield from SPAM data (https://www.mapspam.info/)
    if 'crop_areas' in preprocess:
        from .crop_areas import crop_areas
        spam_variable = 'physical_area' # crop masks, seperately for rainfed and irrigated areas
        crop_areas(domain_shape_path, spam_variable, start_year, end_year, workingdirectory, to_match, mask=mask)
        # spam_variable = 'yield' # crop yields, seperately for rainfed and irrigated areas. Used only for calibration and/or validation
        # crop_areas(domain_shape_path, spam_variable, start_year, end_year, workingdirectory, to_match, mask=mask)

    # Download and preprocess crop calendar from GGCMI (https://zenodo.org/records/5062513)
    if 'cropcalendar' in preprocess:
        from .cropcalendar_module import cropcalendar 
        cropcalendar(domain_shape_path, workingdirectory, templategrid_path, mask=mask, to_match=to_match)

    # Download and preprocess climate data.
    # Source selection:
    #   AgERA5 reanalysis  – both years within its availability window (1979 to last complete year)
    #   NASA NEX-GDDP-CMIP6 – any other case (start_year < 1979 or end_year >= current year)
    if 'climate' in preprocess:
        import datetime
        current_year = datetime.date.today().year
        AGERA5_START = 1979
        use_agera5 = (start_year >= AGERA5_START) and (end_year < current_year)
        if use_agera5:
            from .climate_AgERA5 import climate_AgERA5
            climate_AgERA5(workingdirectory, start_year, end_year, api_token, to_match)
        else:
            from .climate_nasanex import climate_nasanex
            climate_nasanex(workingdirectory, start_year, end_year, to_match,
                            model=nasanex_model, scenario=nasanex_scenario, ensemble=nasanex_ensemble)

if __name__ == '__main__':
    ## Run preprocessing
    geoaquacrop_preproc(domain_path, start_year, end_year, api_token, cell_resolution=cell_resolution, preprocess=['soil', 'crop_areas', 'cropcalendar', 'climate'],
                         nasanex_model=nasanex_model, nasanex_scenario=nasanex_scenario, nasanex_ensemble=nasanex_ensemble,
                         workingdirectory=workingdirectory)
