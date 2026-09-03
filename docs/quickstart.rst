Quick start
===========

Option A — edit and run the main script
-----------------------------------------

Open ``src/geoaquacrop_preprocess/preprocess_main.py``, set the input arguments at
the top of the file, and run:

.. code-block:: bash

   conda activate geoaquacrop
   python -m geoaquacrop_preprocess.preprocess_main

Key input arguments:

.. code-block:: python

   workingdirectory = '/path/to/your/output/directory'
   domain_path      = '/path/to/your/domain.geojson'   # polygon in EPSG:4326
   start_year       = 2020
   end_year         = 2022
   cell_resolution  = 0.05   # degrees (~3 arcmin)
   api_token        = 'your-copernicus-api-token'       # required for AgERA5 only

For future climate projections (NASA NEX-GDDP-CMIP6), also set:

.. code-block:: python

   nasanex_model    = 'GFDL-CM4'
   nasanex_scenario = 'ssp245'   # ssp126 | ssp245 | ssp370 | ssp585
   nasanex_ensemble = 'r1i1p1f1'

Option B — Python API
----------------------

.. code-block:: python

   from geoaquacrop_preprocess import geoaquacrop_preprocess

   geoaquacrop_preprocess(
       domain_shape_path='domain.geojson',
       start_year=2020,
       end_year=2022,
       api_token='your-api-token',       # required for AgERA5 only
       cell_resolution=0.05,
       workingdirectory='/path/to/output',
   )

Output files
------------

Processed datasets are written to ``<workingdirectory>/processed/``:

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - File
     - Contents
   * - ``soil_<depth>.nc``
     - Clay, sand, silt, and soil organic matter for one depth layer
   * - ``spam<year>_physical_area.nc``
     - Crop physical area [ha] per type and irrigation mode
   * - ``cropcalendar.nc``
     - Planting DOY and growing season length per crop and irrigation mode
   * - ``MinTemp<years>.nc``
     - Daily minimum air temperature [°C]
   * - ``MaxTemp<years>.nc``
     - Daily maximum air temperature [°C]
   * - ``Precipitation<years>.nc``
     - Daily precipitation [mm day⁻¹]
   * - ``ReferenceET<years>.nc``
     - Daily FAO-56 Penman-Monteith reference ET₀ [mm day⁻¹]

Raw downloaded files are kept in ``<workingdirectory>/rawdata/`` as resumable
checkpoints and can be deleted once processing is complete.

Supported crop types
--------------------

Barley, Cassava, Cotton, Dry Bean, Maize, Paddy Rice (seasons 1 & 2), Potato,
Sorghum, Soybean, Sugar Beet, Sugar Cane, Sunflower, Wheat (summer & winter)
