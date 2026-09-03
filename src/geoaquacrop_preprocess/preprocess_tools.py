# IMPORT LIBRARIES

import xarray as xr
from rasterio.warp import Resampling
import numpy as np
#from scipy.ndimage import convolve
import pandas as pd
import geopandas as gpd
import os
import glob
import time
import requests
from zipfile import ZipFile
#import pdb # pdb.set_trace()

import rioxarray
import scipy.ndimage as ndi
from shapely.geometry import mapping, box

## Download functions

def download_url(url, download_path="./"):
    """Download a file from a URL to disk, retrying silently on network errors.

    Args:
        url (str): URL of the file to download.
        download_path (str): Local file path where the download is saved.
            Defaults to ``"./"``.
    """
    while True:
        try:
            response = requests.get(url, timeout=30)
        except:
            print("    *** WARNING! Download froze, likely due to network instability. Restarting download...")
            time.sleep(2)
        else:
            if response.ok:
                # inmemory = tiff.imread(io.BytesIO(response.content))  # reads download data directly to memory (without writing to disk)
                with open(download_path, 'wb') as savefile:
                    savefile.write(response.content)  # write download data to disk
                break

def unzip_all(dir='.'):
    """Recursively unzip all ZIP archives found under a directory.

    Iterates until no ``.zip`` files remain. Each archive is extracted to a
    subdirectory with the same stem as the archive, then the archive is deleted.

    Args:
        dir (str): Root directory to search for ZIP files. Defaults to the
            current directory.
    """
    zipfiles = True
    while bool(zipfiles):
        zipfiles = []
        for root, d_names, f_names in os.walk(dir):
            for f in f_names:
                if f.endswith('.zip'):
                    zipfiles.append(os.path.join(root, f))
        if bool(zipfiles):
            for file in zipfiles:
                targetdir = file[:-4]
                if not os.path.exists(targetdir):
                    os.mkdir(targetdir)
                with ZipFile(file, 'r') as zObject:
                    zObject.extractall(path=targetdir)
                os.remove(file)

## Preprocessing functions
def preprocess_spam(basepath, download_dir, refyear, spam_variable, domain_path, to_match, mask=None):
    """Reproject, clip, and merge SPAM GeoTIFF layers into a domain NetCDF.

    Iterates over all per-crop GeoTIFF files in ``download_dir``, reprojects each
    to the template grid using area-weighted resampling, clips to the model domain,
    scales area values by the output-to-input pixel-area ratio, and merges all crop
    layers into a single NetCDF file saved to ``<basepath>/processed/``.

    Args:
        basepath (str): Working directory.
        download_dir (str): Directory containing the unzipped SPAM GeoTIFF files.
        refyear (str): SPAM reference year string, either ``'2010'`` or ``'2020'``.
        spam_variable (str): SPAM variable type. One of ``'physical_area'``,
            ``'harvested_area'``, ``'production'``, or ``'yield'``.
        domain_path (str): Path to the domain polygon file (EPSG:4326).
        to_match (xarray.Dataset): Template raster that defines the output grid.
        mask (geopandas.GeoDataFrame, optional): Pre-loaded domain GeoDataFrame.
            If ``None``, it is read from ``domain_path``.
    """
    if mask is None:
        mask = gpd.read_file(domain_path)
    to_match.rio.write_crs(4326, inplace=True)

    # Precompute output pixel size and domain bounds for efficient clipping
    out_res = abs(float(to_match.rio.resolution()[0]))
    xmin_dom, ymin_dom, xmax_dom, ymax_dom = mask.total_bounds

    # Dictionary that connects FAO crop ID's to crop names in AquaCrop. Used for layer naming
    crop_dict = {'BARL': 'Barley','COTT': 'Cotton','BEAN': 'DryBean','MAIZ': 'Maize','RICE': 'PaddyRice','POTA': 'Potato','SORG': 'Sorghum','SOYB': 'Soybean','SUGB': 'SugarBeet','SUGC': 'SugarCane','SUNF': 'Sunflower','CASS': 'Cassava'}    # Wheat removed as it is in SPAM data aggregated for winter and summer wheat and hence not useful for AquaCrop. 

    # Dictionnary to rename technology
    tech_dict = {'R': 'rf', 'I': 'ir'}

    # CHECK IF ALL FOUR VARIABLES ARE NEEDED. PROBABLY JUST PHYSICAL AREA AND - IF CALBRATION INCLUDED - YIELD
    search_criteria = os.path.join(download_dir, '**', '*.tif')
    layers = glob.glob(search_criteria, recursive=True)
    file_to_mosaic = []

    for layer in layers:

        # Preserve only layers referring to rainfed (R) or irrigated (I) technology
        technique = layer[-5:-4]
        if technique not in ['R','I']:
            os.remove(layer)
            continue

        # Get crop ID from layer name and preserve only if crop type is supported by AquaCrop
        cropID = layer[-10:-6]
        if cropID not in crop_dict:
            os.remove(layer)
            continue

        # print(cropID, technique)

        src = xr.open_dataset(layer)
        src.rio.write_crs(4326, inplace=True)
        # Actual input pixel size (e.g. 5 arcmin = 1/12°) for area scaling
        src_res = abs(float(src.rio.resolution()[0]))
        area_scale = (out_res / src_res) ** 2
        # Coarse bbox clip for efficiency: shrinks global file to domain extent before reproject
        buf = 0.5  # degree buffer to avoid edge effects during reprojection
        src_bbox = src.rio.clip_box(xmin_dom - buf, ymin_dom - buf, xmax_dom + buf, ymax_dom + buf)
        src_proj = src_bbox.rio.reproject_match(to_match, resampling=Resampling.average)  # area-weighted resampling
        # Precise polygon clip for accuracy: respects domain outline at output resolution
        src_clip = safe_clip(src_proj, mask)
        src.close()

        # Rename variables from FAO crop ID to crop strings used by AquaCrop
        layername_base = crop_dict.get(cropID) + '_' + tech_dict.get(technique)

        # Scale area values by the actual output-to-input pixel-area ratio
        if (spam_variable == 'physical_area') | (spam_variable == 'harvested_area') | (spam_variable == 'production'):
            src_clip[layername_base + '_' + spam_variable] = src_clip['band_data'] * area_scale
            #src_clip[layer[-12: -4] + '_percentage'] = src_clip[layer[-12: -4] + '_area'] / meters.ha  # Percentage only needed to restrict model to cells with very small crop area

        # Renaming variable for yield and change from kg/ha to t/ha
        elif spam_variable == 'yield':
            src_clip[layername_base + '_yield'] = src_clip['band_data'] / 1000

        # Drop band_data and append file
        src_clip = src_clip.drop_vars(['band_data'])
        file_to_mosaic.append(src_clip)

    # Merge data into one file
    src_mosaic = xr.merge(file_to_mosaic)
    src_mosaic = src_mosaic.rio.write_crs(4326)      # adds spatial_ref coordinate with crs_wkt
    #for var in src_mosaic.data_vars:               # ensure every data variable references the CRS
    #    src_mosaic[var].attrs['grid_mapping'] = 'spatial_ref'
    target_dir = makedirs(basepath, 'processed', '')
    targetfile = os.path.join(target_dir, 'spam' + refyear + '_' + spam_variable + '.nc')
    src_mosaic.to_netcdf(targetfile)

def spam_refyear(start_year, end_year):
    """Select the most appropriate SPAM reference year for a given period.

    Chooses between available SPAM reference years (2010 or 2020) by selecting
    the one closest to the midpoint of the modelling period.

    Args:
        start_year (int): First year of the modelling period.
        end_year (int): Last year of the modelling period.

    Returns:
        str: The selected SPAM reference year, either ``'2010'`` or ``'2020'``.
    """
    # Choose SPAM data reference year (available reference years are 2010 or 2020) according to average of start and end year of modelling horizon
    avg_year = np.mean([start_year, end_year])
    avg_year = np.ceil(avg_year)
    SPAM_refyears = [2010, 2020]
    refyear = min(SPAM_refyears, key=lambda x: abs(x - avg_year)) # select nearest reference year available in SPAM
    refyear = str(refyear)

    return refyear

## Preprocessing climate data from AgERA5 (and soil water content from ERA5-Land but this is currently not supported as input to simulations)
def preprocess_agera5(src, variable, yearlist, basepath, to_match):
    """Reproject, gap-fill, mask, and save an AgERA5 climate variable.

    Renames variables and converts units to AquaCrop conventions, reprojects to
    the template grid using nearest-neighbour resampling, fills spatial gaps via
    nearest-neighbour interpolation, applies the domain mask, and writes the
    result as a compressed NetCDF to ``<basepath>/processed/``.

    Args:
        src (xarray.Dataset): Merged multi-year AgERA5 dataset for one variable.
        variable (str): AquaCrop variable name. One of ``'MinTemp'``,
            ``'MaxTemp'``, ``'Precipitation'``, or ``'ReferenceET'``.
        yearlist (list[int]): Years contained in ``src``; used to construct the
            output filename.
        basepath (str): Working directory; processed files are written to
            ``<basepath>/processed/``.
        to_match (xarray.Dataset): Template raster from :func:`basegrid`;
            defines the output grid and domain mask.
    """
    print("        *** PREPROCESSING CLIMATE DATA: " + variable + " ***")

    # Variable name definitions for changing to AquaCrop conventions
    varname_dict = {'MinTemp': 'Temperature_Air_2m_Min_24h', 'MaxTemp': 'Temperature_Air_2m_Max_24h', 'Precipitation': 'Precipitation_Flux', 'ReferenceET': 'ReferenceET_PenmanMonteith_FAO56'}  # Names of data variables in AquaCrop and AgERA5 data, respectively

    # Adjust units and data variable names to AquaCrop definitions
    if variable in ['MinTemp', 'MaxTemp', 'Precipitation', 'ReferenceET']:
        src = src.rename_vars({varname_dict.get(variable): variable})  # Rename data variables to AquaCrop names
        src = src.drop_vars(['crs'])
    if variable in ['MinTemp', 'MaxTemp']:
        src = src - 273.15  # Convert from Kelvin to Celsius
        src[variable].attrs['units'] = 'degC'
    if variable in ['Precipitation', 'ReferenceET']:
        src[variable] = src[variable].where(src[variable] >= 0, 0)  # Set negative precipitation and evaporation values to 0.
    if variable in ['InitSoilwater']:
        src = src.drop_vars(['expver', 'number'])
        src = src.rename({'valid_time': 'time'})
        
    # Set CRS here, transformations above can strip it 
    src = ensure_xy_dims(src)
    src.rio.write_crs(4326, inplace=True)

    # Resample to project grid (before gap-filling to prevent ET0 NaNs)
    src_reproj = src.rio.reproject_match(to_match, resampling=Resampling.nearest)

    # Cast to float32 before gap-fill: raw AgERA5 is float32; scalar ops (e.g. -273.15)
    # silently upcast to float64, so we explicitly restore float32 here to halve
    # the memory footprint of data3d for large domains.
    for _v in list(src_reproj.data_vars):
        if src_reproj[_v].dtype != np.float32:
            src_reproj[_v] = src_reproj[_v].astype(np.float32)

    # Fill missing values in data variables (using nearest-neighbour interpolation)
    variables = list(src_reproj.data_vars)
    for variab in variables:    # Loop to make it work also for InitSoilwater data, which has four data variables (corresponding to four soil depths)
        data3d = src_reproj[variab].to_numpy()
        nodata_mask = np.isnan(data3d[0])  # This assumes that all timesteps have the same missing cells (fair assumption, since the same land water mask is applied to all time steps)
        dist, nearest_indices = ndi.distance_transform_edt(nodata_mask, return_indices=True)  # Nearest-neighbour interpolation
        src_reproj[variab].data = data3d[:, nearest_indices[0], nearest_indices[1]]

    src_masked = src_reproj.where(to_match['Band1'] == 1)

    # Prepare output directory
    target_dir = makedirs(basepath, 'processed', '')
    targetfile = os.path.join(target_dir, variable + str(yearlist[0]) + str(yearlist[-1]) + '.nc')

    # Save to disk. Drop singleton dimensions and auxiliary coordinates before saving
    src_masked = src_masked.squeeze(drop=True)
    src_masked = src_masked.drop_vars('spatial_ref', errors='ignore')
    src_masked = src_masked.rio.write_crs(4326)  # adds spatial_ref coordinate with crs_wkt
    for var in src_masked.data_vars:             # ensure every data variable references the CRS (required by QGIS)
        src_masked[var].encoding.pop('grid_mapping', None)
        src_masked[var].attrs['grid_mapping'] = 'spatial_ref'
        if src_masked[var].dtype != np.float32:  # guarantee float32 output
            src_masked[var] = src_masked[var].astype(np.float32)
    encoding = {var: {'zlib': True, 'complevel': 4} for var in variables}
    src_masked.to_netcdf(targetfile, mode='w', encoding=encoding)

def agera5_merge_yearly(target_dir, yearfile):
    """Merge the daily NetCDF files from an AgERA5 yearly download into one file.

    Expects the yearly ZIP to have already been extracted to a subdirectory
    with the same stem as ``yearfile``. Opens all daily ``.nc`` files in that
    folder, concatenates them along the time axis, writes the result to
    ``yearfile``, and removes the unzipped folder to save disk space.

    Args:
        target_dir (str): Directory that contains the yearly ZIP and that will
            receive the merged NetCDF.
        yearfile (str): Target path for the merged yearly NetCDF file.
    """
    import shutil
    unzip_all(target_dir)
    yearfolder = os.path.splitext(yearfile)[0]
    nc_files = sorted(glob.glob(os.path.join(yearfolder, '*.nc')))
    combined = xr.open_mfdataset(nc_files, combine='by_coords').load()  # load into RAM before closing files
    combined = combined.sortby('time')
    combined = combined.rio.write_crs(4326)      # adds spatial_ref coordinate with crs_wkt
    for var in combined.data_vars:               # ensure every data variable references the CRS (required by QGIS)
        combined[var].encoding.pop('grid_mapping', None)
        combined[var].attrs['grid_mapping'] = 'spatial_ref'
    combined.to_netcdf(yearfile)
    combined.close()

    shutil.rmtree(yearfolder)  # remove unzipped folder to save space


## Helper functions

def safe_clip(src, mask):
    """Clip a raster to polygon geometries, skipping nodata and out-of-extent polygons.

    Works with both :class:`xarray.DataArray` and :class:`xarray.Dataset` inputs.
    Multi-part polygons are exploded and clipped individually; results are merged
    with :meth:`xarray.Dataset.combine_first`.

    Args:
        src (xarray.Dataset or xarray.DataArray): Source raster with a CRS
            assigned via ``rio.write_crs``.
        mask (geopandas.GeoDataFrame): Polygon(s) to clip with. Can contain
            Polygon or MultiPolygon geometries.

    Returns:
        xarray.Dataset or xarray.DataArray: Clipped raster with the same type,
        CRS, and spatial structure as ``src``. If no polygon contained valid
        data, returns an all-NaN copy of ``src``.
    """
    # Ensure CRS match
    if mask.crs != src.rio.crs:
        mask = mask.to_crs(src.rio.crs)

    # Explode multipolygons
    mask_exploded = mask.explode(ignore_index=True)

    # Get raster bounds as shapely box
    raster_bounds = box(*src.rio.bounds())

    valid_clips = []

    for geom in mask_exploded.geometry:
        if not geom.intersects(raster_bounds):
            continue
        try:
            clipped = src.rio.clip([mapping(geom)], src.rio.crs, drop=False)
            # rioxarray adds a singleton 'band' dim — drop it now so it doesn't
            # stack when we merge clips from multiple sub-polygons
            if "band" in clipped.dims and clipped.sizes["band"] == 1:
                clipped = clipped.squeeze("band", drop=True)
            if clipped.notnull().any():
                valid_clips.append(clipped)
        except rioxarray.exceptions.NoDataInBounds:
            continue

    # If no valid clips, return empty raster with same structure
    if not valid_clips:
        print("Warning: no valid polygons contained data.")
        empty = src.copy(deep=True)
        for var in list(empty.data_vars):
            empty[var] = xr.full_like(empty[var], fill_value=np.nan)
        if "band" in empty.dims and empty.sizes["band"] == 1:
            empty = empty.squeeze("band", drop=True)
        return empty

    # Merge clips: start from the first, fill NaN cells from each subsequent one.
    # This works identically for Datasets and DataArrays and avoids the
    # concat+max pattern that failed to collapse the band dim on Datasets.
    combined = valid_clips[0]
    for clip in valid_clips[1:]:
        combined = combined.combine_first(clip)

    # Preserve metadata & CRS
    combined.rio.write_crs(src.rio.crs, inplace=True)
    combined.attrs.update(src.attrs)

    return combined

def basegrid(domain_shape_path, resolution, templategrid_path):
    """Create or load the template raster grid for a given domain polygon.

    If the template file already exists it is loaded directly; otherwise a new
    binary raster is created by rasterising the input polygon at the requested
    resolution (cell value 1 inside polygon, 0 outside) and saved as a NetCDF
    file. Coordinates follow the CF convention with descending latitudes.

    Args:
        domain_shape_path (str): Path to the domain polygon file (GeoJSON or
            shapefile). Must be in EPSG:4326 and contain only Polygon or
            MultiPolygon geometries.
        resolution (float): Cell size in decimal degrees.
        templategrid_path (str): File path where the template grid is saved
            (created if absent, loaded if present).

    Returns:
        tuple:
            - xarray.Dataset: Template raster with a single ``Band1`` variable
              (1 = inside domain, 0 = outside) and ``x``/``y`` coordinates.
            - list[float]: Bounding box ``[xmin, ymin, xmax, ymax]`` in decimal
              degrees, rounded to the output resolution.

    Raises:
        Exception: If the input file contains non-polygon geometries or is not
            in EPSG:4326.
    """
    from rasterio.transform import from_origin
    from rasterio import features
    from affine import Affine

    # Read shapefile
    mask = gpd.read_file(domain_shape_path)

    # Check if all geometries are Polygon or MultiPolygon
    if not all(g in ['Polygon', 'MultiPolygon'] for g in mask.geom_type.unique()):
        raise Exception("The input polygon file contains geometries other than Polygon/MultiPolygon.")

    # Check if it's EPSG:4326
    if not mask.crs.to_epsg() == 4326:
        raise Exception("The polygon file must be in EPSG:4326.")

    full_geom = mask.union_all()
    xmin, ymin, xmax, ymax = full_geom.bounds # in lat/lon
    xmin, ymin = np.floor(xmin * (1/resolution)) / (1/resolution) , np.floor(ymin * (1/resolution)) / (1/resolution) # round bounds down to cell resolution
    xmax, ymax = np.ceil(xmax * (1/resolution)) / (1/resolution) , np.ceil(ymax * (1/resolution)) / (1/resolution) # round upper bounds up to cell resolution
    bounds = [xmin, ymin, xmax, ymax]

    if os.path.exists(templategrid_path):
        ds = xr.open_dataset(templategrid_path)
        ds.rio.write_crs(4326, inplace=True)

    else:
        w = round((xmax - xmin) / resolution)
        h = round((ymax - ymin) / resolution)
        lons = np.arange(xmin+resolution/2, xmax, resolution)
        lats = np.arange(ymin+resolution/2, ymax, resolution)

        # Affine transform: top-left origin
        transform = Affine.translation(xmin, ymax) * Affine.scale(resolution, -resolution)

        # Mask: True = inside polygon
        mask_bin = features.geometry_mask([full_geom],out_shape=(h, w),transform=transform,invert=True)

        # Create data array: inside = 1, outside = nodata
        nodata_value = 0
        data = np.full((h, w), nodata_value, dtype=np.uint8)
        data[mask_bin] = 1

        # CF convention prefers descending latitudes
        lats = lats[::-1]

        # Create xarray Dataset
        ds = xr.Dataset({"Band1": (["y", "x"], data),},coords={"y": lats,"x": lons,},attrs={"Conventions": "CF-1.8","title": "Template raster from polygon shapefile","crs": "EPSG:4326"})
        ds["crs"] = xr.DataArray(0, attrs={"grid_mapping_name": "latitude_longitude", "epsg_code": 4326, "semi_major_axis": 6378137.0, "inverse_flattening": 298.257223563, "long_name": "CRS definition"})
        ds["Band1"].attrs.update({"grid_mapping": "crs", "_FillValue": nodata_value, "missing_value": nodata_value})
        ds.rio.write_crs(4326, inplace=True)

        # Save to NetCDF
        ds.to_netcdf(templategrid_path)

    return ds, bounds

def ensure_xy_dims(ds):
    """Rename spatial dimension names to the canonical ``'x'`` and ``'y'``.

    Standardises ``'longitude'``/``'latitude'`` or ``'lon'``/``'lat'`` dimension
    names to the ``'x'``/``'y'`` convention expected by rioxarray.

    Args:
        ds (xarray.Dataset or xarray.DataArray): Input dataset whose dimensions
            may need renaming.

    Returns:
        xarray.Dataset or xarray.DataArray: Dataset with dimensions renamed to
        ``'x'`` and ``'y'`` if applicable; unchanged otherwise.
    """
    # Rename dimensions to 'x' and 'y' if they are named differently
    if 'longitude' in ds.dims and 'latitude' in ds.dims:
        ds = ds.rename({'longitude': 'x', 'latitude': 'y'})
    elif 'lon' in ds.dims and 'lat' in ds.dims:
        ds = ds.rename({'lon': 'x', 'lat': 'y'})
    return ds

def makedirs(basepath, level1, level2):
    """Create a two-level subdirectory structure and return the resulting path.

    Constructs ``<basepath>/<level1>/<level2>`` (or ``<basepath>/<level1>``
    when ``level2`` is falsy), creates all missing intermediate directories,
    and returns the path.

    Args:
        basepath (str): Root working directory.
        level1 (str): First subdirectory name.
        level2 (str): Second subdirectory name, or an empty string to stop at
            the first level.

    Returns:
        str: Absolute path to the created (or already-existing) directory.
    """
    path = os.path.join(basepath, level1, level2) if level2 else os.path.join(basepath, level1)
    os.makedirs(path, exist_ok=True)
    return path

