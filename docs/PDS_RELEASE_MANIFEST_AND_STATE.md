# PDS release manifest and local update state

## Purpose

The distributed PDS Parquet must be accompanied by a small release manifest. The manifest describes the artifact, proves its identity, records the verified coverage boundary, and tells Catalog Manager how a local editable catalog may be initialized.

This work currently applies only to the PDS catalog.

## Two different Sol values

They must never be inferred from one another:

- `last_product_sol`: last Sol that actually contains at least one catalog product;
- `checked_through_sol`: last Sol that the builder inspected, including Sols with no accepted products.

For the current PDS release every camera was checked through Sol 3644. Some cameras have an earlier `last_product_sol`, for example MARDI at Sol 3642. That does not make the catalog incomplete.

## What the Parquet proves

The Parquet can prove product counts, columns, URLs, product Sol ranges, camera distribution, and its own SHA-256 identity. The verified round trip also proves that the editable product JSON can be reconstructed without semantic loss.

The Parquet cannot prove the original builder progress. In particular it does not contain:

- the original `scanned_sol_urls` list;
- empty directories that were inspected;
- the exact builder fingerprint;
- the original generation timestamp.

Catalog Manager must therefore never fabricate these values.

## Source-of-truth hierarchy

For PDS the hierarchy is now fixed:

1. the immutable distributed Parquet plus its matching manifest is the official base release;
2. a reconstructed JSON is an editable local working copy, not a new official release;
3. builder state records only scans actually performed on the local device;
4. future user customizations must remain a separate local layer with their own provenance.

## Product identity and uniqueness

The canonical record identity is `img_url`. In the current release all 387,276 values are present and unique. `product_id` is mandatory scientific metadata but cannot be the primary key because 740 values are repeated. `lbl_url` is optional because 1,483 products do not have one.

Merge and update rules must therefore:

- deduplicate and match records by normalized `img_url`;
- reject blank or duplicated `img_url` values in an official release;
- require non-blank `product_id`, `camera`, and `sol`;
- allow a missing `lbl_url` where the product source legitimately has no label;
- reject exact duplicate rows.

## Safe initialization rule

After reconstructing `Catalog_PDS.json`:

1. initialize the builder state as empty;
2. read `checked_through_sol` from the signed/downloaded release manifest;
3. use Sol 3645 as the start of a normal forward update for this release;
4. use the integrity check, or an explicitly selected overlap scan, to detect historical NASA backfills;
5. write new local state only from directories that the local builder actually checks.

This separates a fast forward update from a slower historical integrity audit and avoids falsely claiming that a local process visited directories it never accessed.

## Prototype files

- Generator: `devtools/build_pds_release_manifest.py`
- Manifest schema: `config/pds_release_manifest_schema.json`
- Local validator: `devtools/validate_pds_release.py`
- Generated test manifest: `data/catalog_json_rebuild/manifest_test/Catalog_PDS.manifest.json`

Example:

```powershell
python devtools\build_pds_release_manifest.py --checked-through-sol 3644
python devtools\validate_pds_release.py
```

The generated manifest is a prototype. It does not yet alter runtime paths, download files from Drive, or replace the current PDS catalog.

## Next integration step

Catalog Manager should validate the downloaded Parquet against the manifest before installing it. Validation must check filename, byte size, SHA-256, row count, column list, and the expected cameras. Only after all checks pass should the temporary download replace the local official base catalog.
