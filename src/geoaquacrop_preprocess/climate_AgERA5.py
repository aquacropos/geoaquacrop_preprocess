"""
Download and preprocess AgERA5 agrometeorological climate data.

Retrieves the following daily variables from the Copernicus Climate Data Store
(CDS) for a specified domain and time period:

- Minimum temperature [°C]
- Maximum temperature [°C]
- Precipitation [mm day⁻¹]
- Reference evapotranspiration (FAO-56 Penman-Monteith) [mm day⁻¹]

Downloads are split into yearly ZIP archives, each containing one ``.nc`` file
per day. These are automatically merged into yearly NetCDF files and then
combined and preprocessed into the final output files.

Includes a DNS fallback mechanism for university networks that intercept
port-53 DNS, using DNS-over-HTTPS (Cloudflare) to resolve the CDS hostname.
"""

import xarray as xr
#import rioxarray as rio
#import numpy as np
#from rasterio.warp import Resampling
import os
import geopandas as gpd
import cdsapi
from shapely.geometry import mapping
#import pdb # pdb.set_trace()

from .preprocess_tools import agera5_merge_yearly, preprocess_agera5, basegrid, makedirs, unzip_all

import socket
import requests

# Set of functions to automatically overcome DNS-based errors, often found on university networks
def force_resolve(ip, hostname="cds.climate.copernicus.eu"):
    """Monkey-patch Python's DNS resolver to map a hostname to a specific IP.

    Overrides :func:`socket.getaddrinfo` so that all subsequent lookups of
    ``hostname`` resolve to ``ip``, bypassing the system DNS entirely.

    Args:
        ip (str): IPv4 address to use for ``hostname``.
        hostname (str): Hostname to override. Defaults to
            ``'cds.climate.copernicus.eu'``.
    """
    print(f'Forcing resolve: {hostname} -> {ip}')
    orig_getaddrinfo = socket.getaddrinfo
 
    def new_getaddrinfo(*args, **kwargs):
        if args[0] == hostname:
            return orig_getaddrinfo(ip, *args[1:], **kwargs)
        return orig_getaddrinfo(*args, **kwargs)
 
    socket.getaddrinfo = new_getaddrinfo
 
 
def resolve_via_doh(hostname="cds.climate.copernicus.eu", doh_url="https://cloudflare-dns.com/dns-query"):
    """Resolve a hostname via DNS-over-HTTPS, bypassing system DNS.

    Useful on networks where port-53 DNS is intercepted or filtered (e.g. some
    university networks).

    Args:
        hostname (str): Hostname to resolve. Defaults to
            ``'cds.climate.copernicus.eu'``.
        doh_url (str): DNS-over-HTTPS endpoint to query. Defaults to the
            Cloudflare resolver.

    Returns:
        str: First IPv4 address (A record) returned by the DoH resolver.

    Raises:
        RuntimeError: If no A records are found for ``hostname``.
        requests.HTTPError: If the DoH request itself fails.
    """
    resp = requests.get(
        doh_url,
        params={"name": hostname, "type": "A"},
        headers={"Accept": "application/dns-json"},
    )
    resp.raise_for_status()
    data = resp.json()
    # Filter for A records (type 1)
    a_records = [ans["data"] for ans in data.get("Answer", []) if ans["type"] == 1]
    if not a_records:
        raise RuntimeError(f"No A records found for {hostname} via DoH")
    ip = a_records[0]
    print(f"Resolved {hostname} to {ip} via DoH")
    return ip
 
 
_dns_fallback_applied = False  # Module-level flag so we only apply the monkey-patch once
 
 
def _is_dns_error(exc):
    """Return True if an exception (or any cause in its chain) is a DNS failure.

    Walks the exception cause chain to detect :class:`socket.gaierror` or
    string patterns associated with DNS resolution failures.

    Args:
        exc (Exception): The exception to inspect.

    Returns:
        bool: ``True`` if a DNS-related error is found, ``False`` otherwise.
    """
    # Walk the cause chain — cdsapi wraps errors in requests exceptions
    current = exc
    while current is not None:
        if isinstance(current, socket.gaierror):
            return True
        # requests wraps socket errors in ConnectionError
        if 'Name or service not known' in str(current) or 'getaddrinfo failed' in str(current):
            return True
        current = getattr(current, '__cause__', None) or getattr(current, '__context__', None)
    return False
 
 
def retrieve_with_dns_fallback(client, dataset, request, target):
    """Wrap a CDS API retrieve call with automatic DNS fallback.

    Attempts a normal :meth:`cdsapi.Client.retrieve` call. If it fails with a
    DNS resolution error, resolves the CDS hostname via DNS-over-HTTPS, applies
    a socket monkey-patch via :func:`force_resolve`, and retries once.

    Args:
        client (cdsapi.Client): Authenticated CDS API client instance.
        dataset (str): CDS dataset identifier (e.g.
            ``'sis-agrometeorological-indicators'``).
        request (dict): CDS API request parameters.
        target (str): Local file path where the downloaded data is saved.

    Returns:
        cdsapi.api.Result: The CDS result object returned by the retrieve call.

    Raises:
        Exception: Any non-DNS exception raised by the CDS client is re-raised
            unchanged.
    """
    global _dns_fallback_applied
 
    # If we've already applied the fix in a previous call, just go straight through
    if _dns_fallback_applied:
        return client.retrieve(dataset, request, target)
 
    try:
        return client.retrieve(dataset, request, target)
    except Exception as e:
        if _is_dns_error(e):
            print('\nDNS resolution failed — falling back to public DNS...')
            ip = resolve_via_doh()
            force_resolve(ip)
            _dns_fallback_applied = True
            return client.retrieve(dataset, request, target)
        else:
            raise  # Not a DNS problem — re-raise as-is
            
def ensure_cds_dns(hostname="cds.climate.copernicus.eu"):
    """Verify that the CDS hostname resolves, applying a DoH fallback if needed.

    Performs a test DNS lookup for ``hostname``. If the system resolver fails,
    calls :func:`resolve_via_doh` and patches the socket module via
    :func:`force_resolve`.

    Args:
        hostname (str): Hostname to check. Defaults to
            ``'cds.climate.copernicus.eu'``.
    """
    try:
        socket.getaddrinfo(hostname, 443)
        print(f'DNS resolution OK for {hostname}')
    except socket.gaierror:
        print(f'System DNS failed for {hostname} — falling back to public DNS...')
        ip = resolve_via_doh(hostname)
        force_resolve(ip, hostname)


# Continue with main script functionality
def climate_AgERA5(basepath, start_year, end_year, api_token, to_match, variables=['MinTemp','MaxTemp','Precipitation','ReferenceET','InitSoilwater']):
    """Download and preprocess AgERA5 daily climate data for a given area and period.

    Retrieves minimum temperature, maximum temperature, precipitation, and reference
    evapotranspiration from the AgERA5 dataset via the Copernicus CDS API. Data
    are downloaded as yearly ZIP archives, merged into yearly NetCDF files, and then
    combined and preprocessed to produce the final outputs on the project grid.

    Args:
        basepath (str): Working directory. Raw downloads go to
            ``<basepath>/rawdata/climate/`` and processed files to
            ``<basepath>/processed/``.
        start_year (int): First year to download (AgERA5 is available from 1979).
        end_year (int): Last year to download (inclusive; must be before the
            current calendar year).
        api_token (str): Personal API token from the Copernicus Climate Data
            Store (https://cds.climate.copernicus.eu/).
        to_match (xarray.Dataset): Template raster from
            :func:`~geoaquacrop_preprocess.preprocess_tools.basegrid`; defines the
            output grid and domain mask.
        variables (list[str]): Climate variables to process. Defaults to
            ``['MinTemp', 'MaxTemp', 'Precipitation', 'ReferenceET',
            'InitSoilwater']``.
    """

    ## Years to be downloaded
    yearlist = list(range(start_year, end_year+1))

    # Define area and grid resolution to be downloaded (bounding box)
    templategrid_path = os.path.join(basepath, 'template_grid.nc')
    _tpl = xr.open_dataset(templategrid_path)           # Read spatial extent from template grid file
    _tpl.rio.write_crs(4326, inplace=True)
    bounds = list(_tpl.rio.bounds())                    # [xmin, ymin, xmax, ymax]
    bounds = [round(b,2) for b in bounds]               # round coordinates to shorten filenames (Windows limitation)
    bounds=[bounds[3],bounds[0],bounds[1],bounds[2]]    # reorder bounds to follow ERA5 CDS definition (N-W-S-E)

    # Prepare download directory
    target_dir = makedirs(basepath, 'rawdata', 'climate')

    # Prepare variable names and stats for API request
    varname_api = {'MinTemp': '2m_temperature', 'MaxTemp': '2m_temperature', 'Precipitation': 'precipitation_flux', 'ReferenceET': 'reference_evapotranspiration'}  # Names of data variables in AquaCrop and AgERA5 api, respectively
    stats_api = {'MinTemp': '24_hour_minimum', 'MaxTemp': '24_hour_maximum', 'Precipitation': '', 'ReferenceET': ''}  # Stats to be requested from API for each variable. Only needed for min and max temperature, as AgERA5 api provides daily accumulations for precipitation and reference ET

    # Prepare Copernicus Climate Data Store (CDS) API
    ensure_cds_dns()
    url = 'https://cds.climate.copernicus.eu/api'
    c = cdsapi.Client(url=url, key=api_token)

    ## Download Mintemp, Maxtemp, ReferenceET, and Precipitation in daily timestep from AgERA5.
    for variable in variables:
        if variable == 'InitSoilwater': # Skip initial soil water here, as it is downloaded from ERA5-Land below
            continue
        for year in yearlist:   # Split downloads into yearly chunks to avoid large files
            targetfile = os.path.join(target_dir, variable + str(year) + '.zip')
            yearfile = os.path.join(target_dir, variable + str(year) + '.nc')
            if not os.path.exists(targetfile) and not os.path.exists(yearfile):  # Skip download if zip file or merged yearly .nc file already exist
                print("        *** DOWNLOADING CLIMATE DATA FROM AgERA5: " + variable + str(year) + " ***")
                retrieve_with_dns_fallback(
                    c,
                    "sis-agrometeorological-indicators",
                    {
                        "variable": [varname_api.get(variable)],
                        "statistic": [stats_api.get(variable)],
                        "year": [str(year)],
                        "month": ["01","02","03","04","05","06","07","08","09","10","11","12"],
                        "day": ["01","02","03","04","05","06","07","08","09","10","11","12","13","14","15","16","17","18","19","20","21","22","23","24","25","26","27","28","29","30","31"],
                        "area": bounds,
                        "version": "2_0",
                    },
                    targetfile
                )

            # Unzip download file and merge the resulting daily files into one yearly file (AgERA5 api returns a zip file containing daily .nc files)
            if not os.path.exists(yearfile):  # Skip unzipping and file merging if yearly .nc file already exists
                agera5_merge_yearly(target_dir, yearfile)

        # Combine yearly files into one (yearly files stay on disk as resumable checkpoints)
        file_paths = [os.path.join(target_dir, variable + str(year) + '.nc') for year in yearlist]
        src = xr.open_mfdataset(file_paths, combine='by_coords').sortby('time')

        # Preprocessing
        preprocess_agera5(src, variable, yearlist, basepath, to_match)
        src.close()

    """
    ## DISABLED AS GRIDDED INITIAL SOIL WATER CONTENT IS CURRENTLY NOT SUPPORTED AS INPUT FOR SIMULATIONS.
    
    ## Download soil water content [m3/m3] for initial time step (has four soil depth layers) from ERA5-Land hourly (not available in AgERA5)
    variable = 'InitSoilwater'
    if variable in variables:
        targetfile = os.path.join(target_dir, variable + str(start_year) + '.nc')
        if not os.path.exists(targetfile):  # Skip download if file already exists
            print("        *** DOWNLOADING SOIL MOISTURE DATA FROM ERA5-Land: " + variable + " ***")
            retrieve_with_dns_fallback(
                    c,
                "reanalysis-era5-land",
                {
                    "variable": [
                        "volumetric_soil_water_layer_1",
                        "volumetric_soil_water_layer_2",
                        "volumetric_soil_water_layer_3",
                        "volumetric_soil_water_layer_4"
                    ],
                    "year": [str(start_year)],
                    "month": ["01"],
                    "day": ["01"],
                    "time": ["00:00"],
                    "data_format": "netcdf",
                    "download_format": "unarchived",
                    "area": bounds
                },
                targetfile
            )

        # Preprocessing
        src = xr.open_dataset(targetfile)
        #preprocess_era5(src, variable, yearlist, basepath, to_match)
        preprocess_agera5(src, variable, yearlist, basepath, to_match)
    """