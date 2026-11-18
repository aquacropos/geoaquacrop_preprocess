import os
from .preprocess_tools import spam_refyear, preprocess_spam, makedirs, download_url, unzip_all

# SPAM release and download URL per (reference year, variable). The release is
# part of the local download name, so a newer release is downloaded afresh
# instead of an older cached one being reused.
SPAM_SOURCES = {
    ('2010', 'physical_area'): ('V2r0', "https://s3.amazonaws.com/mapspam-data/2010/v2.0/geotiff/spam2010v2r0_global_phys_area.geotiff.zip"),
    ('2010', 'yield'):         ('V2r0', "https://s3.amazonaws.com/mapspam/2010/v2.0/geotiff/spam2010v2r0_global_yield.geotiff.zip"),
    ('2020', 'physical_area'): ('V2r2', "https://www.dropbox.com/scl/fi/ubus2gp4u09133trryaai/spam2020V2r2_global_physical_area.geotiff.zip?rlkey=5wzkn6dtyqq8g8i2xpy49f5wp&dl=1"),
    ('2020', 'yield'):         ('V2r0', "https://www.dropbox.com/scl/fi/kajp48kh5wnh65ar2ltbr/spam2020V2r0_global_yield.geotiff.zip?rlkey=n1w5823k0ra9uqqg1tbc18ag4&e=1&dl=1"),
}


def spam_download_name(refyear, spam_variable):
    """Local name of a SPAM download, e.g. ``'spam2020V2r2_physical_area'``."""
    release, _ = SPAM_SOURCES[(refyear, spam_variable)]
    return f'spam{refyear}{release}_{spam_variable}'


def crop_areas(domain_path, spam_variable, start_year, end_year, basepath, to_match, mask=None):
    """Download and preprocess SPAM crop area or yield data.

    Downloads global gridded crop statistics from the Spatial Production Allocation
    Model (SPAM), reprojects to the project grid, and clips to the model domain.
    The most suitable SPAM reference year (2010 or 2020) is selected automatically
    based on the midpoint of the modelling period.

    Args:
        domain_path (str): Path to the domain polygon file (GeoJSON or shapefile,
            EPSG:4326).
        spam_variable (str): Variable to download. One of ``'physical_area'``,
            ``'harvested_area'``, ``'production'``, or ``'yield'``.
        start_year (int): First year of the modelling period, used to select the
            SPAM reference year.
        end_year (int): Last year of the modelling period, used to select the
            SPAM reference year.
        basepath (str): Working directory. Raw downloads go to
            ``<basepath>/rawdata/cropmasks/`` and processed files to
            ``<basepath>/processed/``.
        to_match (xarray.Dataset): Template raster from
            :func:`~geoaquacrop_preprocess.preprocess_tools.basegrid`; defines the
            output grid.
        mask (geopandas.GeoDataFrame, optional): Pre-loaded domain GeoDataFrame.
            If ``None``, it is read from ``domain_path``.
    """

    # Define most suitable reference year of crop mask
    refyear = spam_refyear(start_year, end_year)

    ## Download global crop masks from SPAM data (cultivated areas for 16 crop types)
    def download_spam(refyear, spam_variable, basepath):
        # Download URL for this reference year and variable
        _, url = SPAM_SOURCES[(refyear, spam_variable)]

        # Define target dir and paths
        if spam_variable in ['physical_area', 'harvested_area']:
            target_dir = makedirs(basepath, 'rawdata', 'cropmasks')
        else:  # yield, production
            target_dir = makedirs(basepath, 'rawdata', 'calibration')

        download_path = os.path.join(target_dir, spam_download_name(refyear, spam_variable) + '.zip')
        unzipped_dir = download_path[:-4]

        print("        *** DOWNLOADING SPAM CROP AREAS ***")
        # If unzipped data already exists, skip everything
        if os.path.exists(unzipped_dir):
            print(f"SPAM data already unzipped, skipping download and unzip: {unzipped_dir}")
            return unzipped_dir

        # Otherwise, check if ZIP exists
        if os.path.exists(download_path):
            print(f" SPAM zip already exists, skipping download: {download_path}")
        else:
            print(f"Downloading SPAM {refyear} data ({spam_variable})")
            print('URL:', url)
            download_url(url, download_path=download_path)

        # Unzip (if not already unzipped)
        print(" Unzipping SPAM data...")
        unzip_all(dir=target_dir)

        return unzipped_dir

    # Run downloader
    download_dir = download_spam(refyear, spam_variable, basepath)

    ## Preprocess data for model domain
    target_dir = makedirs(basepath, 'processed', '')
    targetfile = os.path.join(target_dir, 'spam' + refyear + '_' + spam_variable + '.nc')
    if not os.path.exists(targetfile):  # Skip processing if file already exists
        print(f"Processing SPAM data for model domain and saving to {targetfile}")
        preprocess_spam(basepath, download_dir, refyear, spam_variable, domain_path, to_match, mask=mask,
                        source=spam_download_name(refyear, spam_variable))
