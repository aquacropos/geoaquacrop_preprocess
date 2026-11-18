# MARC provides two calendars (Zhao et al. 2024, ESSD 16, 3893):
# - 'group': rice seasons grouped by transplanting window, so each layer is
#   the same season everywhere. Group 1 = DOY 182-304 (Jul-Oct, main/wet
#   season), group 2 = DOY 60-181 (Mar-Jun), group 3 = DOY 305-59 (Nov-Feb,
#   dry season). A group is empty where that season grows no rice.
# - 'cropping': the first, second and third rice crop of each cell in
#   calendar order, so a layer is the wet season in one place and a
#   Feb-Apr crop in another.
MARC_CALENDARS = {
    'group': ('1_Transplanting_Harvest_Group.nc', 'Transplanting_{k}_Group', 'Harvest_{k}_Group'),
    'cropping': ('3_Transplanting_Harvest_Cropping.nc', 'Transplanting_{k}_Cropping', 'Harvest_{k}_Cropping'),
}


# Origin of each season's dates in the output (variable <crop>_calendar_source)
SOURCE_OBSERVED, SOURCE_OBSERVED_SHIFTED, SOURCE_FILLED, SOURCE_FILLED_SHIFTED = 1, 2, 3, 4


def _doy(x):
    """Wrap day-of-year values to 1-365."""
    return (x - 1) % 365 + 1


def _conflict(start_a, length_a, start_b, length_b, min_fallow_days):
    """True where two seasons (start DOY, length in days) overlap on the yearly
    cycle or leave fewer than ``min_fallow_days`` between them."""
    gap_ab = (start_b - (start_a + length_a)) % 365     # end of a -> start of b
    gap_ba = (start_a - (start_b + length_b)) % 365     # end of b -> start of a
    # Disjoint seasons and their two gaps cover the year exactly once
    overlap = gap_ab + length_b + gap_ba + length_a > 365 + 1e-6
    return overlap | (gap_ab < min_fallow_days) | (gap_ba < min_fallow_days)


def fill_and_sequence(plant, harvest, min_fallow_days=7):
    """Fill missing seasons and make the seasons of each cell sequential.

    MARC estimates each season's dates separately per 0.5° cell, from sampled
    fields and smoothed over neighbouring cells (Zhao et al. 2024, Sect. 2.3),
    so seasons of one cell can overlap, and a cell can lack a season that a
    crop model needs. This function returns a calendar in which, in every
    cell, no two seasons grow at the same time.

    1. Cells without any season copy all seasons from the nearest cell that
       has at least one, so their seasons come from one place.
    2. A season still missing is copied from the nearest cell that has it.
    3. In each cell, seasons are placed in priority order: observed before
       filled, then in the order given. A season that overlaps an already
       placed one, or starts or ends less than ``min_fallow_days`` from it,
       is moved by the fewest days that make it fit, earlier or later,
       keeping its length. A season that fits nowhere is left empty.

    Args:
        plant (numpy.ndarray): Transplanting DOY, shape (season, y, x); NaN or
            <= 0 where missing.
        harvest (numpy.ndarray): Harvest DOY, same shape.
        min_fallow_days (int): Minimum days between the harvest of one season
            and the transplanting of the next.

    Returns:
        tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]: Transplanting DOY,
        season length (days) and origin code per season and cell
        (``SOURCE_*``; 0 where empty).
    """
    import numpy as np
    import scipy.ndimage as ndi

    # Whole days, so the sequencing below still holds after the output is rounded
    plant = np.round(np.where(plant > 0, plant, np.nan).astype(float))
    harvest = np.round(np.where(harvest > 0, harvest, np.nan).astype(float))
    length = np.mod(harvest - plant, 365)
    observed = np.isfinite(plant) & np.isfinite(length) & (length > 0)
    plant = np.where(observed, plant, np.nan)
    length = np.where(observed, length, np.nan)
    source = np.where(observed, SOURCE_OBSERVED, 0)

    # 1. Cells with no season at all: all seasons from the nearest cell with any
    any_obs = observed.any(axis=0)
    if any_obs.any():
        _, (iy, ix) = ndi.distance_transform_edt(~any_obs, return_indices=True)
        empty = ~any_obs
        donor = observed[:, iy, ix] & empty
        plant = np.where(donor, plant[:, iy, ix], plant)
        length = np.where(donor, length[:, iy, ix], length)
        source = np.where(donor, SOURCE_FILLED, source)

    # 2. Seasons still missing: from the nearest cell that observes that season
    for k in range(plant.shape[0]):
        if not observed[k].any():
            continue
        _, (iy, ix) = ndi.distance_transform_edt(~observed[k], return_indices=True)
        missing = source[k] == 0
        plant[k] = np.where(missing, plant[k][iy, ix], plant[k])
        length[k] = np.where(missing, length[k][iy, ix], length[k])
        source[k] = np.where(missing, SOURCE_FILLED, source[k])

    # 3. Sequence the seasons of every cell with more than one
    n_seasons = np.isfinite(plant).sum(axis=0)
    for y, x in zip(*np.nonzero(n_seasons > 1)):
        order = sorted((k for k in range(plant.shape[0]) if np.isfinite(plant[k, y, x])),
                       key=lambda k: (source[k, y, x] != SOURCE_OBSERVED, k))
        placed = []
        for k in order:
            start, dur = plant[k, y, x], length[k, y, x]
            # The smallest move that fits starts either at the original date, just
            # after a placed season (its harvest + fallow), or just before one
            # (harvest = its transplanting - fallow)
            candidates = ([start]
                          + [_doy(s + l + min_fallow_days) for s, l in placed]
                          + [_doy(s - min_fallow_days - dur) for s, l in placed])
            candidates.sort(key=lambda c: min((c - start) % 365, (start - c) % 365))
            fits = [c for c in candidates
                    if not any(_conflict(c, dur, s, l, min_fallow_days) for s, l in placed)]
            if not fits:
                plant[k, y, x] = length[k, y, x] = np.nan
                source[k, y, x] = 0
                continue
            if fits[0] != start:
                plant[k, y, x] = fits[0]
                source[k, y, x] += 1          # observed -> observed, shifted; filled -> filled, shifted
            placed.append((plant[k, y, x], dur))

    return plant, length, source


def ricecalendar_marc(domain_path, basepath, referenceraster_path, calendar_type='group',
                      groups=(1, 2, 3), min_fallow_days=7):
    """Download and preprocess the MARC rice calendar dataset.

    Downloads the Monsoon Asia Rice Calendar (MARC, https://essd.copernicus.org/articles/16/3893/2024/), reprojects to
    the project grid, and saves a single merged NetCDF. Outputs contain 12 layers:
    3 rice growing seasons (PaddyRice1, PaddyRice2, PaddyRice3) × 2 variables
    (planting DOY and growing season length) × 2 irrigation modes (rainfed and
    irrigated). Note that MARC does not distinguish rainfed from irrigated — the
    ``rf`` and ``ir`` layers are identical.

    With ``calendar_type='group'`` (default), PaddyRice1/2/3 are MARC's
    seasonal groups: transplanting in Jul-Oct (main/wet season), Mar-Jun and
    Nov-Feb (dry season), the same season in every cell. With
    ``'cropping'``, they are the first, second and third crop of each cell in
    calendar order.

    On MARC's native 0.5° grid, missing seasons are filled from the nearest
    cells and the seasons of each cell are made sequential, so no two crops
    grow at the same time in a cell (see :func:`fill_and_sequence`). Only the
    seasons listed in ``groups`` are produced and sequenced against each
    other, so an unused season cannot displace one that is simulated. The
    variable ``PaddyRice<k>_calendar_source`` records where each cell's dates
    come from: 1 observed, 2 observed and shifted, 3 filled, 4 filled and
    shifted.

    Args:
        domain_path (str): Path to the domain polygon file (GeoJSON or shapefile,
            EPSG:4326).
        basepath (str): Working directory. Raw downloads go to
            ``<basepath>/rawdata/cropcalendar/marc_rice/`` and the processed file
            is written to ``<basepath>/processed/ricecalendar_marc.nc``.
        referenceraster_path (str): Path to the template raster NetCDF used to
            align the output grid.
        calendar_type (str): ``'group'`` (default) or ``'cropping'``; see above.
        groups (tuple[int]): Seasons (groups or croppings) to produce, from 1, 2
            and 3. Default all three.
        min_fallow_days (int): Minimum days between the harvest of one season
            and the transplanting of the next in a cell. Default 7.
    """

    import os
    import glob
    import numpy as np
    import geopandas as gpd
    import xarray as xr
    import rioxarray  # noqa: F401  – registers .rio accessor on xarray objects
    from .preprocess_tools import download_url, unzip_all, ensure_xy_dims, makedirs, safe_clip

    if calendar_type not in MARC_CALENDARS:
        raise ValueError(f"calendar_type must be one of {list(MARC_CALENDARS)}, not {calendar_type!r}")
    groups = tuple(groups)
    if not groups or not set(groups) <= {1, 2, 3} or len(set(groups)) != len(groups):
        raise ValueError(f"groups must be distinct values from 1, 2 and 3, not {groups!r}")
    marc_name, transplant_pattern, harvest_pattern = MARC_CALENDARS[calendar_type]

    # ------------------------------------------------------------------ #
    # Load reference raster and domain polygon
    # ------------------------------------------------------------------ #
    mask = gpd.read_file(domain_path)
    to_match = xr.open_dataset(referenceraster_path)
    to_match.rio.write_crs(4326, inplace=True)

    # ------------------------------------------------------------------ #
    # Download MARC rice calendar data
    # ------------------------------------------------------------------ #
    print("        *** DOWNLOADING MARC RICE CALENDAR DATA ***")
    url = 'https://db.cger.nies.go.jp/nies_data/10.17595/20230728.001/Rice_Calendar_Data_ver.1.0.zip'

    # Build target directory: rawdata/cropcalendar/marc_rice/
    cropcal_dir = makedirs(basepath, 'rawdata', 'cropcalendar')
    target_dir = os.path.join(cropcal_dir, 'marc_rice')
    os.makedirs(target_dir, exist_ok=True)

    download_path = os.path.join(target_dir, 'Rice_Calendar_Data_ver.1.0.zip')

    # Check for any already-unzipped content (NetCDF files present)
    existing_nc = glob.glob(os.path.join(target_dir, '**', marc_name), recursive=True)

    if existing_nc:
        nc_file = existing_nc[0]
        print(f"MARC rice calendar already unzipped, skipping: {nc_file}")
    else:
        if os.path.exists(download_path):
            print(f"ZIP already exists, skipping download: {download_path}")
        else:
            print("Downloading MARC rice calendar data")
            print('URL:', url)
            download_url(url, download_path=download_path)

        print("Unzipping MARC rice calendar data...")
        unzip_all(dir=target_dir)

        existing_nc = glob.glob(os.path.join(target_dir, '**', marc_name), recursive=True)
        if not existing_nc:
            raise FileNotFoundError(
                f"Could not find '{marc_name}' after unzipping. "
                f"Check contents of: {target_dir}"
            )
        nc_file = existing_nc[0]

    # ------------------------------------------------------------------ #
    # Open source file
    # ------------------------------------------------------------------ #
    src = xr.open_dataset(nc_file)
    src = ensure_xy_dims(src)
    src.rio.write_crs(4326, inplace=True)

    # ------------------------------------------------------------------ #
    # Check that domain polygon lies fully within the raster extent
    # ------------------------------------------------------------------ #
    raster_bounds = src.rio.bounds()          # (left, bottom, right, top)
    poly_bounds = mask.to_crs(4326).total_bounds  # [minx, miny, maxx, maxy]

    fully_inside = (
        poly_bounds[0] >= raster_bounds[0] and   # poly west  ≥ raster west
        poly_bounds[1] >= raster_bounds[1] and   # poly south ≥ raster south
        poly_bounds[2] <= raster_bounds[2] and   # poly east  ≤ raster east
        poly_bounds[3] <= raster_bounds[3]        # poly north ≤ raster north
    )

    if fully_inside:
        print("Input polygon is fully inside the MARC raster extent.")
    else:
        print("WARNING: Input polygon extends (partly or fully) beyond the MARC raster extent!")
        print(f"  Polygon bounds [W, S, E, N]: {poly_bounds}")
        print(f"  Raster bounds  [W, S, E, N]: "
              f"[{raster_bounds[0]}, {raster_bounds[1]}, {raster_bounds[2]}, {raster_bounds[3]}]")

    # ------------------------------------------------------------------ #
    # Fill missing seasons and sequence them, on the native grid
    # Group (or cropping) k -> PaddyRice<k>
    # ------------------------------------------------------------------ #
    plant_all = np.stack([src[transplant_pattern.format(k=k)].astype(float).values for k in groups])
    harvest_all = np.stack([src[harvest_pattern.format(k=k)].astype(float).values for k in groups])
    plant_all, season_all, source_all = fill_and_sequence(plant_all, harvest_all, min_fallow_days)
    template = src[transplant_pattern.format(k=groups[0])].astype(float)

    file_to_mosaic = []

    for i, k in enumerate(groups):
        crop_name = f'PaddyRice{k}'
        print(f"    Processing {crop_name} ({transplant_pattern.format(k=k)} / {harvest_pattern.format(k=k)})")

        layers_native = {
            'planting': template.copy(data=plant_all[i]),
            'season': template.copy(data=season_all[i]),
            'source': template.copy(data=source_all[i].astype(float)),
        }
        processed = {}
        for name, da in layers_native.items():
            da.rio.write_crs(4326, inplace=True)
            # ---- Reproject to reference grid (nearest neighbour) and clip to domain ----
            processed[name] = safe_clip(da.rio.reproject_match(to_match), mask)
        plant_clip, season_clip = processed['planting'], processed['season']

        # Replace DOY 60 (Feb 29) with 61 (Mar 1) to avoid leap-year artefacts
        plant_clip = plant_clip.where(plant_clip != 60, 61)

        # ---- Create rf and ir layers (identical — MARC has no irrigation split) ----
        for technique in ['rf', 'ir']:
            layername = f'{crop_name}_{technique}'

            plant_layer = xr.DataArray(
                np.round(plant_clip.values).astype('float32'),
                dims=plant_clip.dims,
                coords=plant_clip.coords,
                name=f'{layername}_planting',
                attrs={'units': 'day of year',
                       'long_name': f'Planting day {technique}'},
            )

            # Store as float32 with integer values (range ~25–200) so that the
            # values are directly readable without timedelta decoding.
            season_layer = xr.DataArray(
                np.round(season_clip.values).astype('float32'),
                dims=season_clip.dims,
                coords=season_clip.coords,
                name=f'{layername}_growing_season_length',
                attrs={'units': 'days',
                       'long_name': f'Growing season length {technique}'},
            )

            file_to_mosaic.append(plant_layer)
            file_to_mosaic.append(season_layer)

        source_clip = processed['source']
        file_to_mosaic.append(xr.DataArray(
            source_clip.values.astype('float32'),
            dims=source_clip.dims,
            coords=source_clip.coords,
            name=f'{crop_name}_calendar_source',
            attrs={'long_name': f'Origin of the {crop_name} dates',
                   'flag_values': [SOURCE_OBSERVED, SOURCE_OBSERVED_SHIFTED, SOURCE_FILLED, SOURCE_FILLED_SHIFTED],
                   'flag_meanings': 'observed observed_shifted filled filled_shifted'},
        ))

    # ------------------------------------------------------------------ #
    # Merge all layers and save
    # ------------------------------------------------------------------ #
    src_mosaic = xr.merge(file_to_mosaic)
    src_mosaic = src_mosaic.rio.write_crs(4326)   # adds spatial_ref coordinate
    src_mosaic.attrs.update({
        'source': f'MARC v1.0 rice calendar, {marc_name}',
        'calendar_type': calendar_type,
        'groups': list(groups),
        'min_fallow_days': min_fallow_days,
        'gap_filling': ('missing seasons copied from the nearest cell (all seasons from one cell where a '
                        'cell has none); seasons of each cell made sequential with at least min_fallow_days '
                        'between them (geoaquacrop_preprocess.ricecalendar_marc.fill_and_sequence)'),
        'seasons': ('PaddyRice1: transplanting DOY 182-304 (main/wet season); PaddyRice2: DOY 60-181; '
                    'PaddyRice3: DOY 305-59 (dry season)') if calendar_type == 'group' else
                   'PaddyRice1/2/3: first, second and third rice crop of each cell in calendar order',
    })

    target_out_dir = makedirs(basepath, 'processed', 'cropcalendar_marc')
    targetfile = os.path.join(target_out_dir, 'cropcalendar.nc')
    src_mosaic.to_netcdf(targetfile)

    print(f"MARC rice calendar saved to: {targetfile}")
    print(f"Output variables ({len(src_mosaic.data_vars) - 1} + spatial_ref):")
    for var in src_mosaic.data_vars:
        if var != 'spatial_ref':
            print(f"  {var}")


if __name__ == '__main__':
    domain_path = '/Users/ritterj1/PythonProjects/geoaquacrop_preprocess/inputdata/mekong/basin_outline/mekong_jrc_outline.geojson'
    basepath = '/Users/ritterj1/PythonProjects/geoaquacrop_preprocess'
    referenceraster_path = '/Users/ritterj1/PythonProjects/geoaquacrop_preprocess/template_grid.nc'
    ricecalendar_marc(domain_path, basepath, referenceraster_path)