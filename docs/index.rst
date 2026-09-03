geoaquacrop-preprocess
===================

**geoaquacrop-preprocess** is an automated data download and preprocessing pipeline
for running `FAO AquaCrop <https://www.fao.org/aquacrop>`_ over large regions in
gridded format.

Given a polygon defining the area of interest and a time period, the pipeline
automatically downloads, reprojects, and harmonises the following datasets onto
a common output grid:

.. list-table::
   :header-rows: 1
   :widths: 20 30 30 20

   * - Dataset
     - Variables
     - Source
     - Native resolution
   * - Climate (past)
     - Min/max temperature, precipitation, reference ET
     - `AgERA5 <https://cds.climate.copernicus.eu/datasets/sis-agrometeorological-indicators>`_ via Copernicus CDS
     - 0.1°, daily
   * - Climate (future)
     - Min/max temperature, precipitation, reference ET
     - `NASA NEX-GDDP-CMIP6 <https://www.nccs.nasa.gov/services/data-collections/land-based-products/nex-gddp-cmip6>`_
     - 0.25°, daily
   * - Soil
     - Clay, sand, silt, soil organic matter (6 depth layers)
     - `ISRIC SoilGrids <https://soilgrids.org/>`_
     - 250 m
   * - Crop calendar
     - Planting DOY, growing season length
     - `GGCMI phase 3 v1.01 <https://zenodo.org/records/5062513>`_
     - 0.5°
   * - Crop areas
     - Physical area by crop and irrigation type
     - `SPAM 2010/2020 <https://www.mapspam.info/>`_
     - ~10 km

The climate source is chosen automatically: **AgERA5 reanalysis** is used when
both years fall within its availability window (1979 to the previous complete
year); **NASA NEX-GDDP-CMIP6 projections** are used otherwise.

.. toctree::
   :maxdepth: 1
   :caption: Getting started

   installation
   quickstart

.. toctree::
   :maxdepth: 2
   :caption: API reference

   api/index

Indices and tables
------------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
