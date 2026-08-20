Installation
============

Prerequisites
-------------

- `Miniconda <https://docs.conda.io/en/latest/miniconda.html>`_ or
  `Anaconda <https://www.anaconda.com/>`_
- **For past climate (AgERA5) only:** a free
  `Copernicus CDS account <https://cds.climate.copernicus.eu/>`_ and personal
  API token (see :ref:`cds-token`)

Steps
-----

1. Clone the repository::

      git clone https://github.com/josiasritter/geoaquacrop-preproc-dev
      cd geoaquacrop-preproc-dev

2. Create and activate the conda environment::

      conda env create -f environment.yml
      conda activate geoaquacrop

.. _cds-token:

Obtaining a Copernicus CDS API token
-------------------------------------

An API token is required **only** when processing past climate data (AgERA5,
covering 1979 to last complete year):

1. Create a free account at https://cds.climate.copernicus.eu/
2. Go to **Your profile → API Token** and copy your token.
3. Accept the dataset terms of use at the
   `AgERA5 download page <https://cds.climate.copernicus.eu/datasets/sis-agrometeorological-indicators?tab=download>`_.
