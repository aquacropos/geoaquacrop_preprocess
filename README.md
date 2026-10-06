# geoaquacrop_preprocess

> Automated data download and preprocessing pipeline for running FAO AquaCrop over large regions in gridded format.

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-Apache%20License%202.0-blue)

## Overview

This package is the data preparation stage of [**GeoAquaCrop**](https://github.com/aquacropos/geoaquacrop), the umbrella repository that combines preprocessing, simulation and visualisation. GeoAquaCrop is distributed as a Python package (`pip install geoaquacrop`), where this stage is available as `geoaquacrop.preprocess`.

**geoaquacrop_preprocess** prepares all spatial input datasets required to run the [FAO AquaCrop](https://www.fao.org/aquacrop) crop water productivity model over large regions (e.g. river basins, countries) in a gridded setup. Given a polygon defining the area of interest and a time period, the pipeline automatically downloads, reprojects, and harmonises the following datasets onto a common output grid:

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

## Documentation

Full documentation is available at <https://geoaquacrop-preprocessing.readthedocs.io/en/latest/>.

## Prerequisites

- [Miniconda](https://docs.conda.io/en/latest/miniconda.html) or [Anaconda](https://www.anaconda.com/)
- **For past climate (AgERA5) only:** a free [Copernicus CDS account](https://cds.climate.copernicus.eu/) and your personal API token

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/aquacropos/geoaquacrop_preprocess
   cd geoaquacrop_preprocess
   ```

2. **Create and activate the conda environment:**
   ```bash
   conda env create -f environment.yml
   conda activate geoaquacrop
   ```

## Quick start

### Option A — edit and run the main script

Open `src/geoaquacrop_preprocess/preprocess_main.py`, set the input arguments at the top of the file, and run:

```bash
conda activate geoaquacrop
python -m geoaquacrop_preprocess.preprocess_main
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
from geoaquacrop_preprocess import run

run(
    domain_shape_path='domain.geojson',
    start_year=2020,
    end_year=2022,
    api_token='your-api-token',       # required for AgERA5 only
    cell_resolution=0.05,
    workingdirectory='/path/to/output',
)
```

Individual steps can also be run directly, without needing to build a `preprocess` list:

```python
from geoaquacrop_preprocess import soil, crop_area, crop_calendar, weather

soil(domain_shape_path='domain.geojson', start_year=2020, end_year=2022,
     workingdirectory='/path/to/output')
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
| `preprocess` | all steps | Steps to run: `'soil'`, `'crop_areas'`, `'crop_calendar'`, `'climate'` |
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

## Data attributions

geoaquacrop_preprocess does not contain any of the datasets listed below. It downloads them from the original providers when you run it, and then reprojects, resamples and harmonises them onto a common grid. If you use the outputs of this tool, please credit the original data providers and follow each provider's terms of use.

### Past climate: AgERA5

Daily past climate data (minimum and maximum temperature, precipitation and reference evapotranspiration) come from AgERA5, produced for the Copernicus Climate Change Service (C3S) and downloaded from the Copernicus Climate Data Store. The data are licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Changes made by this tool: regridding and harmonisation.

> Contains modified Copernicus Climate Change Service information 2026. Neither the European Commission nor ECMWF is responsible for any use that may be made of this information.

Boogaard, H., Schubert, J., De Wit, A., Lazebnik, J., Hutjes, R., Van der Grijn, G. (2020): Agrometeorological indicators from 1979 to present derived from reanalysis. Copernicus Climate Change Service (C3S) Climate Data Store (CDS). DOI: [10.24381/cds.6c68c9bb](https://doi.org/10.24381/cds.6c68c9bb) (accessed on DD-MMM-YYYY).

### Future climate: NASA NEX-GDDP-CMIP6

Future climate projections come from the NASA Earth Exchange Global Daily Downscaled Projections (NEX-GDDP-CMIP6). The dataset was prepared by the Climate Analytics Group and the NASA Ames Research Center using the NASA Earth Exchange, and is distributed by the NASA Center for Climate Simulation (NCCS). We thank the World Climate Research Programme and its Working Group on Coupled Modelling, which coordinated CMIP6. We also thank the climate modelling groups who produced and shared their model output, the Earth System Grid Federation (ESGF) for archiving and providing access, and the agencies that fund CMIP6 and ESGF. The underlying CMIP6 model output is subject to the [CMIP6 terms of use](https://pcmdi.llnl.gov/CMIP6/TermsOfUse/TermsOfUse6-1.html).

- Thrasher, B., Wang, W., Michaelis, A., Melton, F., Lee, T., Nemani, R. (2022): NASA Global Daily Downscaled Projections, CMIP6. Scientific Data 9, 262. [https://doi.org/10.1038/s41597-022-01393-4](https://doi.org/10.1038/s41597-022-01393-4)
- Thrasher, B., Wang, W., Michaelis, A., Nemani, R. (2021): NEX-GDDP-CMIP6. NASA Center for Climate Simulation. [https://doi.org/10.7917/OFSG3345](https://doi.org/10.7917/OFSG3345)

### Soil: ISRIC SoilGrids

Soil texture and organic matter data come from SoilGrids 2.0, produced by ISRIC – World Soil Information and licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Changes made by this tool: clipping, resampling and harmonisation.

Poggio, L., de Sousa, L. M., Batjes, N. H., Heuvelink, G. B. M., Kempen, B., Ribeiro, E., Rossiter, D. (2021): SoilGrids 2.0: producing soil information for the globe with quantified spatial uncertainty. SOIL 7, 217–240. [https://doi.org/10.5194/soil-7-217-2021](https://doi.org/10.5194/soil-7-217-2021)

### Crop calendar: GGCMI Phase 3

Planting dates and growing season lengths come from the GGCMI Phase 3 crop calendar (v1.01), licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Changes made by this tool: regridding and conversion to AquaCrop inputs.

- Jägermeyr, J., Müller, C., Minoli, S., Ray, D., Siebert, S. (2021): GGCMI Phase 3 crop calendar (v1.01) [Data set]. Zenodo. [https://doi.org/10.5281/zenodo.5062513](https://doi.org/10.5281/zenodo.5062513)
- Jägermeyr, J., Müller, C., Ruane, A. C. et al. (2021): Climate impacts on global agriculture emerge earlier in new generation of climate and crop models. Nature Food 2, 873–885. [https://doi.org/10.1038/s43016-021-00400-y](https://doi.org/10.1038/s43016-021-00400-y)

### Crop areas: SPAM (MapSPAM)

Physical crop areas come from the Spatial Production Allocation Model (SPAM), developed by the International Food Policy Research Institute (IFPRI) and partners. Please check the licence of the SPAM version you use on its Harvard Dataverse page. The MapSPAM terms of use refer to a [CC BY-NC 3.0](https://creativecommons.org/licenses/by-nc/3.0/) licence, which does not allow commercial use.

- SPAM 2020: International Food Policy Research Institute (IFPRI), 2026, "Global Spatially-Disaggregated Crop Production Statistics Data for 2020 Version 2.0 Release 2", [https://doi.org/10.7910/DVN/SWPENT](https://doi.org/10.7910/DVN/SWPENT), Harvard Dataverse, V5
- SPAM 2010: International Food Policy Research Institute, 2019, "Global Spatially-Disaggregated Crop Production Statistics Data for 2010 Version 2.0", [https://doi.org/10.7910/DVN/PRFF8V](https://doi.org/10.7910/DVN/PRFF8V), Harvard Dataverse, V4
- Yu, Q., You, L., Wood-Sichra, U., Ru, Y., Joglekar, A. K. B., Fritz, S., Xiong, W., Lu, M., Wu, W., Yang, P. (2020): A cultivated planet in 2010 – Part 2: The global gridded agricultural-production maps. Earth System Science Data 12, 3545–3572. [https://doi.org/10.5194/essd-12-3545-2020](https://doi.org/10.5194/essd-12-3545-2020)
