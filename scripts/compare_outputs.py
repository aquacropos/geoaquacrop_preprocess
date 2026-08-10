"""Quick comparison of new vs reference climate NetCDF outputs."""
import numpy as np
import xarray as xr
import os

ref_dir = '/Users/ritterj1/PythonProjects/geoaquacrop-preproc-dev_niedersachsen/processed'
new_dir = '/Users/ritterj1/PythonProjects/aquagropgrid-preproc_niedersachsen-streamlined/processed'

vars_to_check = [
    'MaxTemp20302031',
    'MinTemp20302031',
    'Precipitation20302031',
    'ReferenceET20302031',
]

for v in vars_to_check:
    ref = xr.open_dataset(os.path.join(ref_dir, f'{v}.nc'))
    new = xr.open_dataset(os.path.join(new_dir, f'{v}.nc'))
    varname = v.replace('20302031', '')
    rv = ref[varname].values.astype(np.float64)
    nv = new[varname].values.astype(np.float64)

    valid = ~np.isnan(rv)
    diff = np.abs(rv - nv)

    print(f"\n{'='*55}")
    print(f" {v}")
    print(f"  ref dtype  : {ref[varname].dtype}   new dtype: {new[varname].dtype}")
    print(f"  shape      : {rv.shape}")
    nan_ref = np.isnan(rv).sum()
    nan_new = np.isnan(nv).sum()
    print(f"  NaN match  : {nan_ref == nan_new}  (ref={nan_ref}, new={nan_new})")
    if valid.any():
        print(f"  max |diff| : {diff[valid].max():.6g}   (>1e-4: {(diff[valid] > 1e-4).sum()} values)")
        print(f"  mean|diff| : {diff[valid].mean():.6g}")
    ref.close()
    new.close()

print("\nDone.")
