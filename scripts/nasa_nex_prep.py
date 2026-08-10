import pandas as pd
import numpy as np
import xarray as xr
import rasterio
import os

from pyproj import Transformer


# ── Helper functions ────────────────────────────────────────────────────────
def lon_to_180(lon):
    """Convert a longitude from 0–360 convention to −180–180 convention.

    NASA-NEX GDDP-CMIP6 is stored on a 0–360 grid; AquaCrop and most
    point coordinates use −180–180, so longitudes east of 180 need shifting.
    """
    return lon - 360 if lon > 180 else lon


def reproject_point(x, y, src_crs, dst_crs):
    """Reproject a single (x, y) point from src_crs to dst_crs.

    always_xy=True forces (lon, lat) / (easting, northing) ordering so the
    result is independent of the CRS's native axis order.
    """
    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    return transformer.transform(x, y)


# ── Reference evapotranspiration ─────────────────────────────────────────────
def calc_faopm(df, lat, elev):
    """Calculate daily reference ET0 via the FAO-56 Penman-Monteith equation.

    Adds intermediate radiation/vapour-pressure terms and a final
    'ReferenceET' column (mm/day) to the input dataframe.

    Parameters
    ----------
    df : pandas.DataFrame
        Daily weather with the following columns (units as noted):
            - time     : date / datetime (used to derive Day, Month, Year)
            - MaxTemp  : maximum daily air temperature (°C)
            - MinTemp  : minimum daily air temperature (°C)
            - rsds     : surface downwelling shortwave radiation (MJ/m²/day)
            - hurs     : relative humidity (%)
            - sfcWind  : wind speed (m/s)
        (Precipitation is carried through elsewhere; it is not needed here.)
    lat : float
        Latitude of the point in decimal degrees (EPSG:4326). Converted to
        radians internally — coords must be in lat/lon, not projected.
    elev : float
        Elevation of the point in metres (used for atmospheric pressure).

    Returns
    -------
    pandas.DataFrame
        The input dataframe with added intermediate columns and a
        'ReferenceET' column (mm/day), floored at 0.1 mm/day.
    """

    # Create separate Day, Month, and Year columns
    dt_series = pd.to_datetime(df['time'])
    df['Day'] = dt_series.dt.day
    df['Month'] = dt_series.dt.month
    df['Year'] = dt_series.dt.year

    # Atmospheric pressure (kPa)
    AtmP = 101.3 * ((293 - 0.0065 * elev) / 293) ** 5.26

    # Psychometric constant (kPa/C)
    psy = 0.665 * 10 ** -3 * AtmP

    # Albedo for grass reference crop
    albedo = 0.23

    # Soil heat flux is negligible
    G = 0

    # Convert latitude from degrees to radians
    LatRad = (np.pi / 180) * lat

    # Stefan-Boltzmann constant (MJ/K^4/m2/day)
    sbc = 4.903 * 10 ** -9

    # Solar constant (MJ/m2/min)
    Gs = 0.0820

    # Numerator and denominator constants
    Cn = 900   # Short-reference grass crop
    Cd = 0.34  # Short-reference grass crop

    # Mean daily temperature (degC)
    df['Tmean'] = (df['MaxTemp'] + df['MinTemp']) / 2

    # Saturation vapour pressure at max and min temperatures
    df['e0max'] = 0.6108 * np.exp((17.27 * df['MaxTemp']) / (df['MaxTemp'] + 237.3))
    df['e0min'] = 0.6108 * np.exp((17.27 * df['MinTemp']) / (df['MinTemp'] + 237.3))

    # Saturation vapour pressure
    df['es'] = (df['e0max'] + df['e0min']) / 2

    # Actual vapour pressure using relative humidity (hurs)
    df['ea'] = (df['hurs'] / 100) * ((df['e0min'] + df['e0max']) / 2)

    # Slope of the saturation vapour pressure curve
    df['svp_slope'] = (4098 * (0.6108 * np.exp((17.27 * df['Tmean']) / (df['Tmean'] + 237.3)))) / ((df['Tmean'] + 237.0) ** 2)

    # Calculate Julian days
    df['J'] = df['Day'] - 32 + np.floor(275 * (df['Month'] / 9)) + (2 * np.floor(3 / (df['Month'] + 1))) + np.floor((df['Month'] / 100) - (((df['Year'] % 4) / 4)) + 0.975)

    # Penman-Monteith variables
    df['dr'] = 1 + 0.033 * np.cos(((2 * np.pi) / 365) * df['J'])
    df['sd'] = 0.409 * np.sin(((2 * np.pi) / 365) * df['J'] - 1.39)
    arccos_input = (-np.tan(LatRad)) * np.tan(df['sd'])  # added this and clip to abide mathematical constraint of arccos
    df['ws'] = np.arccos(np.clip(arccos_input, -1, 1))   # extreme lats and solar declination angles can result legitimately in values outside valid range

    # Extraterrestrial radiation (MJ/m^2/day)
    df['Ra'] = (24 * 60) / np.pi * Gs * df['dr'] * (df['ws'] * np.sin(LatRad) * np.sin(df['sd']) + np.cos(LatRad) * np.cos(df['sd']) * np.sin(df['ws']))

    # Net shortwave radiation (MJ/m^2/day)
    df['Rns'] = (1 - albedo) * df['rsds']

    # Clear-sky solar radiation (MJ/m^2/day)
    df['Rs0'] = (0.75 + (0.00002 * elev)) * df['Ra']

    # Cloudiness function
    df['fcd'] = 1.35 * (df['rsds'] / df['Rs0']) - 0.35
    df['fcd'] = np.where(df['fcd'] > 1.0, 1.0, df['fcd'])
    df['fcd'] = np.where(df['fcd'] < 0.05, 0.05, df['fcd'])

    # Net longwave radiation (MJ/m^2/day)
    df['Rnl'] = sbc * df['fcd'] * (0.34 - 0.14 * np.sqrt(df['ea'])) * (((df['MaxTemp'] + 273.16) ** 4 + (df['MinTemp'] + 273.16) ** 4) / 2)

    # Net radiation (MJ/m^2/day)
    df['Rn'] = df['Rns'] - df['Rnl']

    # Reference evapotranspiration calculation
    df['Et0'] = ((0.408 * df['svp_slope'] * (df['Rn'] - G)) + psy * (Cn / (df['Tmean'] + 273)) * df['sfcWind'] * (df['es'] - df['ea'])) / (df['svp_slope'] + psy * (1 + Cd * df['sfcWind']))

    # Et0 cannot be negative, adjust col name for AquaCrop
    df['ReferenceET'] = np.where(df['Et0'] < 0.1, 0.1, df['Et0'])

    return df


# ── Elevation lookup ─────────────────────────────────────────────────────────
def read_elev(x_coord, y_coord, elev_path):
    """Look up elevation (m) at a lat/lon point from a DEM raster.

    The point is reprojected from EPSG:4326 into the DEM's native CRS before
    indexing, so the DEM can be in any projection.

    Parameters
    ----------
    x_coord, y_coord : float
        Point longitude and latitude in EPSG:4326.
    elev_path : str
        Path to the DEM raster (any rasterio-readable format / CRS).

    Returns
    -------
    float
        Elevation at the nearest DEM pixel, in the DEM's units (metres).
    """
    with rasterio.open(elev_path) as dem:
        # reproject coords into DEM CRS
        rx, ry = reproject_point(
            x_coord,
            y_coord,
            src_crs="EPSG:4326",
            dst_crs=dem.crs.to_string()
        )

        row, col = dem.index(rx, ry)
        elev = dem.read(1)[row, col]

    return elev


# ── Point weather extraction + ET0 ───────────────────────────────────────────
def prepare_climate_data(
        input_files,
        x_coord,
        y_coord,
        source,
        elev_path=None
        ):
    """Extract daily climate at a single point and return AquaCrop-ready weather.

    Reads six CMIP6 variables (one per NetCDF file), each at the nearest grid
    cell to the requested point, applies source-specific unit conversions,
    computes FAO-56 Penman-Monteith ET0, and returns the columns AquaCrop
    expects.

    Parameters
    ----------
    input_files : dict
        Maps variable name -> NetCDF file path. Keys must include:
        'tasmin', 'tasmax', 'pr', 'rsds', 'sfcWind', 'hurs'.
    x_coord, y_coord : float
        Point longitude and latitude in EPSG:4326. Longitude is shifted to the
        dataset's 0–360 convention internally for selection; the original
        lat/lon is used for elevation lookup and the ET0 latitude term.
    source : str
        Climate dataset identifier controlling the unit conversions.
        Currently implemented: 'NASA-NEX'. 'CHESS-MET' is a placeholder.
    elev_path : str, optional
        Path to a DEM raster, required for the ET0 calculation (NASA-NEX).

    Returns
    -------
    pandas.DataFrame
        Columns: MinTemp (°C), MaxTemp (°C), Precipitation (mm/day),
        ReferenceET (mm/day), Date.

    Notes
    -----
    NASA-NEX GDDP-CMIP6 unit conversions applied here:
        - tasmin, tasmax : K  ->  °C   (subtract 273.15)
        - pr             : kg/m²/s  ->  mm/day   (× 86400)
        - rsds           : W/m²  ->  MJ/m²/day   (× 0.0864)
        - hurs           : clipped to a 100% ceiling
    """

    # Convert 0–360 to −180–180 once
    adj_lon = lon_to_180(x_coord)

    def extract_series(lon, lat, varname):
        with xr.open_dataset(input_files[varname], engine="netcdf4") as ds:
            return ds[varname].sel(lon=lon, lat=lat, method='nearest').to_pandas()

    # ---- Extract weather series ----
    ser_tmin = extract_series(adj_lon, y_coord, varname='tasmin')
    ser_tmax = extract_series(adj_lon, y_coord, varname='tasmax')
    ser_pr   = extract_series(adj_lon, y_coord, varname='pr')
    ser_rsds = extract_series(adj_lon, y_coord, varname='rsds')
    ser_wind = extract_series(adj_lon, y_coord, varname='sfcWind')
    ser_hurs = extract_series(adj_lon, y_coord, varname='hurs')

    # ---- Build minimal frame ----
    df_temp = pd.DataFrame({
        'time': ser_tmin.index,
        'tasmin': ser_tmin.values,
        'tasmax': ser_tmax.values,
        'pr': ser_pr.values,
        'rsds': ser_rsds.values,
        'sfcWind': ser_wind.values,
        'hurs': ser_hurs.values,
    })

    df_temp.reset_index(drop=True, inplace=True)

    # ---- Source-specific processing ----
    if source == 'CHESS-MET':
        raise NotImplementedError("Add CHESS-MET adjustments here if required.")

    elif source == 'NASA-NEX':

        # Unit conversions (see Notes in docstring)
        df_temp['tasmin'] -= 273.15      # K -> °C
        df_temp['tasmax'] -= 273.15      # K -> °C
        df_temp['pr'] *= 86400           # kg/m²/s -> mm/day
        df_temp['rsds'] *= 0.0864        # W/m² -> MJ/m²/day
        df_temp['hurs'] = df_temp['hurs'].clip(upper=100)

        # Clean date column
        df_temp['Date'] = pd.to_datetime(df_temp['time'].astype(str).str[:10])

        df_temp.rename(columns={
            'pr': 'Precipitation',
            'tasmin': 'MinTemp',
            'tasmax': 'MaxTemp'
        }, inplace=True)

        # Elevation lookup (DEM must be in lon/lat or correctly reprojected)
        elev_data = read_elev(x_coord, y_coord, elev_path)

        # Compute FAO PM ET0
        df_temp = calc_faopm(df=df_temp,
                             lat=y_coord,
                             elev=elev_data)

        return df_temp[['MinTemp', 'MaxTemp', 'Precipitation', 'ReferenceET', 'Date']]

    else:
        raise ValueError(f"Unsupported source: {source}")
        
# ──────────────────────────────────────────────────────────────────────────────
# EXAMPLE USAGE
# Extract daily weather for a single point and compute AquaCrop-ready inputs.
# Replace the example values below with your own.
# ──────────────────────────────────────────────────────────────────────────────

# Directory containing the NASA-NEX GDDP-CMIP6 NetCDF files
weather_path = "C:/data/nasa_nex/high_plains"

# DEM raster used for the elevation term in the ET0 calculation
elev_path = "C:/data/dem/srtm_high_plains.tif"

# Which GCM and scenario to read (must match the filenames in weather_path)
gcm_name = "GFDL-ESM4"        # e.g. one of the NASA-NEX GDDP-CMIP6 models
ssp_name = "ssp245"           # e.g. 'historical', 'ssp245', 'ssp585'

# Point of interest, in EPSG:4326 (lon/lat)
x_coord = -101.83             # longitude (decimal degrees, −180 to 180)
y_coord = 37.76               # latitude  (decimal degrees)

# Which dataset's unit conventions to apply
weather_source = "NASA-NEX"

# Build the variable -> filepath mapping.
# Filename pattern here is: {var}_day_{gcm}_{ssp}_HPsubset.nc
input_files = {
    'tasmin':  os.path.join(weather_path, f'tasmin_day_{gcm_name}_{ssp_name}_HPsubset.nc'),
    'tasmax':  os.path.join(weather_path, f'tasmax_day_{gcm_name}_{ssp_name}_HPsubset.nc'),
    'pr':      os.path.join(weather_path, f'pr_day_{gcm_name}_{ssp_name}_HPsubset.nc'),
    'rsds':    os.path.join(weather_path, f'rsds_day_{gcm_name}_{ssp_name}_HPsubset.nc'),
    'sfcWind': os.path.join(weather_path, f'sfcWind_day_{gcm_name}_{ssp_name}_HPsubset.nc'),
    'hurs':    os.path.join(weather_path, f'hurs_day_{gcm_name}_{ssp_name}_HPsubset.nc'),
}

# Extract, convert units, and compute ET0
weather_data = prepare_climate_data(
    input_files=input_files,
    x_coord=x_coord,
    y_coord=y_coord,
    source=weather_source,
    elev_path=elev_path,
)

# weather_data is now an AquaCrop-ready dataframe:
#   MinTemp (°C) | MaxTemp (°C) | Precipitation (mm/day) | ReferenceET (mm/day) | Date
print(weather_data.head())