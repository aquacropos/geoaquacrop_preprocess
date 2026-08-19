# geoaquacrop-preproc

> Automated data download and preprocessing pipeline for running FAO AquaCrop over large regions in gridded format.

\![Python](https://img.shields.io/badge/python-3.11%2B-blue)
\![License](https://img.shields.io/badge/license-MIT-green)

## Overview

**geoaquacrop-preproc** prepares all spatial input datasets required to run the [FAO AquaCrop](https://www.fao.org/aquacrop) crop water productivity model over large regions (e.g. river basins, countries) in a gridded setup. Given a polygon defining the area of interest and a time period, the pipeline automatically downloads, reprojects, and harmonises the following datasets onto a common output grid:

| Dataset | Variables | Source | Native resolution |
|---------|-----------|--------|-------------------|
| Climate (past) | Min/max temperature, precipitation, reference ET | [AgERA5](https://cds.climate.copernicus.eu/datasets/sis-agrometeorological-indicators) via Copernicus CDS | 0.1°, daily |
| Climate (future) | Min/max temperature, precipitation, reference ET | [NASA NEX-GDDP-CMIP6](https://www.nccs.nasa.gov/services/data-collections/land-based-products/nex-gddp-cmip6) | 0.25°, daily |
| Soil | Clay, sand, silt, soil organic matter (6 depth layers) | [ISRIC SoilGrids](https://soilgrids.org/) | 250 m |
| Crop calendar | Planting day of year, growing season length | [GGCMI phase 3 v1.01](https://zenodo.org/records/5062513) | 0.5° |
| Crop areas | Physical area by crop and irrigation type | [SPAM 2010/2020](https://www.mapspam.info/) | ~10 km |

The climate data source is selected automatically:

- **Past climate** (1979 to last complete year) → AgERA5 reanalysis via the Copernicus CDS API
- **Future climate** (any year ≥ current year, or before 1979) → NASA NEX-GDDP-CMIP6 projections

All outputs are written as compressed NetCDF files on a shared spatial grid at the user-specified resolution.

## Supported crop types

Barley, Cassava, Cotton, Dry Bean, Maize, Paddy Rice (seasons 1 & 2), Potato, Sorghum, Soybean, Sugar Beet, Sugar Cane, Sunflower, Wheat (summer & winter)

## Prerequisites

- [Miniconda](https://docs.conda.io/en/latest/miniconda.html) or [Anaconda](https://www.anaconda.com/)
- **For past climate (AgERA5) only:** a free [Copernicus CDS account](https://cds.climate.copernicus.eu/) and your personal API token

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/josiasritter/geoaquacrop-preproc-dev
   cd geoaquacrop-preproc-dev
   ```

2. **Create and activate the conda environment:**
   ```bash
   conda env create -f environment.yml
   conda activate geoaquacrop
   ```

## Quick start

### Option A — edit and run the main script

Open `src/geoaquacrop_preproc/preproc_main.py`, set the input arguments at the top of the file, and run:

```bash
conda activate geoaquacrop
python -m geoaquacrop_preproc.preproc_main
```

Key input arguments:

```python
workingdirectory = '/path/to/your/output/directory'
domain_path      = '/path/to/your/domain.geojson'   # polygon in EPSG:4326
start_year       = 2020
end_year         = 2022
cell_resolution  = 0.05   # output grid size in degrees (~3 arcmin)
api_token        = 'your-copernicus-api-token'       # required for AgERA5 only
```

For future climate projections (NASA NEX-GDDP-CMIP6), also configure:

```python
nasanex_model    = 'GFDL-CM4'
nasanex_scenario = 'ssp245'   # ssp126 | ssp245 | ssp370 | ssp585
nasanex_ensemble = 'r1i1p1f1'
```

### Option B — Python API

```python
from geoaquacrop_preproc import geoaquacrop_preproc

geoaquacrop_preproc(
    domain_shape_path='domain.geojson',
    start_year=2020,
    end_year=2022,
    api_token='your-api-token',       # required for AgERA5 only
    cell_resolution=0.05,
    workingdirectory='/path/to/output',
)
```

## Output files

Processed datasets are written to `<workingdirectory>/processed/`:

| File | Contents |
|------|----------|
| `soil_<depth>.nc` | Clay, sand, silt, and soil organic matter for one depth layer |
| `spam<year>_physical_area.nc` | Crop physical area [ha] per type and irrigation mode |
| `cropcalendar.nc` | Planting DOY and growing season length per crop and irrigation mode |
| `MinTemp<years>.nc` | Daily minimum air temperature [°C] |
| `MaxTemp<years>.nc` | Daily maximum air temperature [°C] |
| `Precipitation<years>.nc` | Daily precipitation [mm/day] |
| `ReferenceET<years>.nc` | Daily FAO-56 Penman-Monteith reference ET0 [mm/day] |

Raw downloaded files are kept in `<workingdirectory>/rawdata/` as resumable checkpoints and can be deleted once processing is complete.

## Configuration reference

| Parameter | Default | Description |
|-----------|---------|-------------|
| `cell_resolution` | `0.05` | Output grid cell size in decimal degrees |
| `preprocess` | all steps | Steps to run: `'soil'`, `'crop_areas'`, `'cropcalendar'`, `'climate'` |
| `nasanex_model` | `'GFDL-CM4'` | CMIP6 model name (see [catalog](https://ds.nccs.nasa.gov/thredds/catalog/AMES/NEX/GDDP-CMIP6/catalog.html)) |
| `nasanex_scenario` | `'ssp245'` | SSP scenario for years >= 2015 |
| `nasanex_ensemble` | `'r1i1p1f1'` | Ensemble member identifier |

## Obtaining a Copernicus CDS API token

An API token is required only when processing **past climate data** (AgERA5, 1979 to last complete year):

1. Create a free account at https://cds.climate.copernicus.eu/
2. Go to **Your profile -> API Token** and copy your token
3. Accept the dataset terms of use at the [AgERA5 download page](https://cds.climate.copernicus.eu/datasets/sis-agrometeorological-indicators?tab=download)

## License

This project is licensed under the terms described in the [LICENSE](LICENSE) file.
