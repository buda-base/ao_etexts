## BDRC Etext folder structure

This document describes the folder structure of a BDRC etext instance archival object.

We use the following conventions:
- `{ie_id}`, the identifier of an etext instance (ie: `IE3KG218`)
- `{ve_id}`, the identifier of an etext volume (ie: `VE1ER123`)
- `{ut_id}`, the identifier of an etext unit (ie: `UT1ALS00415M_0001`)

The folder structure is as follows:

```
{ie_id}/
├─ sources/
│  ├─ {ve_id}/
│  │  ├─ source_file.txt
│  ├─ source_file.txt
├─ archive/
│  ├─ {ve_id}/
│  │  ├─ {ut_id}.xml
```

With the following conventions:
- there should be no folder in `{ie_id}` except `sources/` and `archive/`
- there should be no folder in `archive/` except the ones corresponding to volumes
- there should be no files in `archive/{ve_id}/` except xml files for each etext unit
- there should be no file directly in `{ie_id}` or `archive`
- there should be no `.DS_Store` files, `__MACOS` directories, etc.
- the `sources/` directory structure is not strictly defined, we recommend that files are organized in folders corresponding to volumes, but it is not enforced and files can have any structure

All `{ie_id}` and `{ve_id}` must match a catalog record. `{ut_id}` are constructed by removing replacing the first two letters (`VE`) of the `{ve_id}` by `UT` and adding a suffix composed of `_` followed by the etext unit index in the volume, padded on 4 digits. For instance the first etext in `VE1ER123` is `UT1ER123_0001.xml`.