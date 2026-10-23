import os
import geopandas as gpd
import glob
import xarray as xr
import rioxarray as rio
from shapely.geometry import mapping
from rasterio.warp import Resampling
from .preprocess_tools import download_url, get_with_retries, ensure_xy_dims, makedirs, safe_clip


def download_ggcmi_files(record_url, target_dir):
    """Download all files of a Zenodo record into ``target_dir``.

    Reads the file listing from the Zenodo record API and fetches each file
    from its own URL. Files are first written to ``<target_dir>.partial`` and
    the folder is renamed to ``target_dir`` only once every file is complete,
    so an interrupted run never leaves an incomplete ``target_dir`` behind.
    Files already present in the partial folder with the expected size are
    not downloaded again.

    Args:
        record_url (str): Zenodo record API URL, e.g.
            ``'https://zenodo.org/api/records/5062513'``.
        target_dir (str): Directory where the files are saved.
    """
    print("Downloading GGCMI crop calendar data")
    print('Record:', record_url)
    files = get_with_retries(record_url).json()['files']

    partial_dir = target_dir + '.partial'
    os.makedirs(partial_dir, exist_ok=True)
    for i, f in enumerate(files, start=1):
        file_path = os.path.join(partial_dir, f['key'])
        if os.path.exists(file_path) and os.path.getsize(file_path) == f['size']:
            continue
        print(f"  [{i}/{len(files)}] {f['key']}")
        download_url(f['links']['self'], download_path=file_path)
        if os.path.getsize(file_path) != f['size']:
            raise IOError(f"Incomplete download of {f['key']}: expected {f['size']} bytes, "
                          f"got {os.path.getsize(file_path)}.")

    os.replace(partial_dir, target_dir)


def cropcalendar(domain_path, basepath, referenceraster_path, mask=None, to_match=None):
    """Download and preprocess GGCMI phase 3 crop calendar data.

    Downloads planting day and growing season length for all GGCMI v1.01 crop
    types (Jägermeyr et al., 2021; https://zenodo.org/records/5062513), reprojects
    to the project grid, clips to the model domain, and saves a single merged NetCDF
    file. Day-of-year 60 (Feb 29) is replaced by 61 (Mar 1) to avoid leap-year
    artefacts.

    Args:
        domain_path (str): Path to the domain polygon file (GeoJSON or shapefile,
            EPSG:4326).
        basepath (str): Working directory. Raw downloads go to
            ``<basepath>/rawdata/cropcalendar/`` and the processed file is written
            to ``<basepath>/processed/cropcalendar.nc``.
        referenceraster_path (str): Path to the template raster NetCDF used to
            align the output grid.
        mask (geopandas.GeoDataFrame, optional): Pre-loaded domain GeoDataFrame.
            If ``None``, it is read from ``domain_path``.
        to_match (xarray.Dataset, optional): Pre-loaded template raster. If
            ``None``, it is read from ``referenceraster_path``.
    """

    # For reprojecting and clipping
    if mask is None:
        mask = gpd.read_file(domain_path)
    if to_match is None:
        to_match = xr.open_dataset(referenceraster_path)
        to_match.rio.write_crs(4326, inplace=True)
    
    print("        *** DOWNLOADING GGCMI CROP CALENDAR DATA ***")
    ## Download crop calendar dataset from GGCMI (Jägermeyr et al. 2021; https://zenodo.org/records/5062513)
    # The Zenodo files-archive (zip bundle) endpoint is no longer available, so each file
    # is fetched from its own URL as listed by the record API.
    record_url = 'https://zenodo.org/api/records/5062513'
    target_dir = makedirs(basepath, 'rawdata', 'cropcalendar')
    unzipped_download_directory = os.path.join(target_dir, 'ggcmi_cropcalendar')

    #  Skip everything if already downloaded
    if os.path.exists(unzipped_download_directory):
        print(f"GGCMI crop calendar already downloaded, skipping: {unzipped_download_directory}")
    else:
        download_ggcmi_files(record_url, unzipped_download_directory)


    ## Convert separate files to rasterstack, reproject (nearest neighbour) to 0.05 degrees, and clip to domain

    # Dictionary that connects GGCMI crop ID's to crop names in AquaCrop. Used for layer naming
    crop_dict = {'bar': 'Barley', 'cot': 'Cotton', 'bea': 'DryBean', 'mai': 'Maize', 'ri1': 'PaddyRice1', 'ri2': 'PaddyRice2', 'pot': 'Potato', 'sor': 'Sorghum', 'soy': 'Soybean', 'sgb': 'SugarBeet', 'sgc': 'SugarCane', 'sun': 'Sunflower', 'swh': 'Wheat_summer', 'wwh': 'Wheat_winter', 'cas': 'Cassava'}

    search_criteria = os.path.join(unzipped_download_directory, '*.nc4')
    layers = glob.glob(search_criteria)
    file_to_mosaic = []
    for layer in layers:

        # Get crop ID from layer name and preserve only if crop type is supported by AquaCrop
        cropID = layer[-43:-40]
        technique = layer[-39:-37]
        if cropID not in crop_dict:
            os.remove(layer)
            continue

        src = xr.open_dataset(layer, decode_timedelta=False)       
        src = ensure_xy_dims(src)
        #src = src.drop_vars(['growing_season_length', 'data_source_used'])
        src = src.drop_vars(['maturity_day', 'data_source_used'])
        src.rio.write_crs(4326, inplace=True)

        # Reproject and clip to model domain
        src_proj = src.rio.reproject_match(to_match)#, resampling=Resampling.nearest)  # nearest-neighbor
        #src_clip = src_proj.rio.clip(mask.geometry.apply(mapping))
        src_clip = safe_clip(src_proj, mask)

        # Rename variables from FAO crop ID to crop strings used by AquaCrop
        layername_base = crop_dict.get(cropID) + '_' + technique
        src_clip[layername_base + '_planting'] = src_clip['planting_day']
        # Replace DOY 60 (Feb 29) with 61 (Mar 1) to avoid leap-year artefacts
        src_clip[layername_base + '_planting'] = src_clip[layername_base + '_planting'].where(
            src_clip[layername_base + '_planting'] != 60, 61
        )
        #src_clip[layername_base + '_harvest'] = src_clip['maturity_day']
        src_clip[layername_base + '_growing_season_length'] = src_clip['growing_season_length']

        # Select relevant data variables for merging
        file_to_mosaic.append(src_clip[layername_base + '_planting'])
        #file_to_mosaic.append(src_clip[layername_base + '_harvest'])
        file_to_mosaic.append(src_clip[layername_base + '_growing_season_length'])

    # Merge data into one file
    src_mosaic = xr.merge(file_to_mosaic)
    target_dir = makedirs(basepath, 'processed', '')
    targetfile = os.path.join(target_dir, 'cropcalendar.nc')
    src_mosaic.to_netcdf(targetfile)
