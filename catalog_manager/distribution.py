"""Download and install pre-built catalog releases (an alternative to scanning PDS/RAW
from scratch, for a fresh install or a user who'd rather not wait for a multi-hour scan).

`config/catalog_distribution_sources.json` points at where each catalog's manifest+parquet
are hosted; `fetch_remote_*_manifest` reads the remote manifest to see what's available,
`local_*_release` reads what's currently installed, and `install_remote_*_release` does the
actual download (skipping it if the local file's SHA-256 already matches) with a
validate-then-atomic-swap-then-revalidate sequence, rolling back to the previous release on
any failure at any step. Used by `app.py`'s "Download & Install" onboarding flow, not by
any of the `workers/` (those build catalogs from PDS/RAW directly, not from a distribution).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

from devtools.validate_pds_release import validate_release
from devtools.validate_raw_release import validate_raw_release


ProgressCallback = Callable[[int, int | None], None]


def load_distribution_config(project_root: Path) -> dict[str, Any]:
    """Load and sanity-check `config/catalog_distribution_sources.json` (schema_version 1, with a `"pds"` section)."""
    path = project_root / "config" / "catalog_distribution_sources.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("pds"), dict):
        raise ValueError("Invalid catalog distribution source configuration")
    return payload


def _download_bytes(url: str, *, timeout: int = 60) -> bytes:
    """GET `url` and return the full response body (used for the small manifest JSON files, not the multi-GB parquet)."""
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.content


def fetch_remote_pds_manifest(project_root: Path, *, timeout: int = 60) -> dict[str, Any]:
    """Download and parse the PDS release manifest (checks `catalog_key == "pds"`, guarding against a misconfigured URL pointing at the wrong release)."""
    config = load_distribution_config(project_root)["pds"]
    payload = _download_bytes(str(config["manifest"]["download_url"]), timeout=timeout)
    manifest = json.loads(payload.decode("utf-8"))
    if manifest.get("catalog_key") != "pds":
        raise ValueError("The remote manifest is not a PDS release")
    return manifest


def fetch_remote_raw_manifest(project_root: Path, *, timeout: int = 60) -> dict[str, Any]:
    """Download and parse the RAW release manifest (checks `catalog_key == "raw"`, the RAW-catalog counterpart of `fetch_remote_pds_manifest`)."""
    config = load_distribution_config(project_root)["raw"]
    payload = _download_bytes(str(config["manifest"]["download_url"]), timeout=timeout)
    manifest = json.loads(payload.decode("utf-8"))
    if manifest.get("catalog_key") != "raw":
        raise ValueError("The remote manifest is not a RAW release")
    return manifest


def _download_file(url: str, destination: Path, progress: ProgressCallback | None, *, timeout: int = 120) -> None:
    """Stream `url` to `destination` in 1MB chunks, calling `progress(downloaded, total)` as data arrives; raises if the server returns an HTML page instead of a file (the tell-tale sign of a Google Drive quota/interstitial page instead of the real download)."""
    downloaded = 0
    with requests.get(url, stream=True, timeout=(30, timeout)) as response:
        response.raise_for_status()
        total_text = response.headers.get("Content-Length")
        total = int(total_text) if total_text and total_text.isdigit() else None
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if "text/html" in content_type:
            raise RuntimeError("Google Drive returned an HTML page instead of the catalog file")
        with destination.open("wb") as stream:
            for block in response.iter_content(chunk_size=1024 * 1024):
                if not block:
                    continue
                stream.write(block)
                downloaded += len(block)
                if progress:
                    progress(downloaded, total)
    if progress:
        progress(downloaded, total or downloaded)


def _file_sha256(path: Path) -> str:
    """Compute `path`'s SHA-256 hex digest, streamed in 1MB chunks (files here can be multiple GB)."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def local_pds_release(project_root: Path) -> dict[str, Any] | None:
    """Return the currently-installed PDS release's manifest, or `None` if no distributed release is installed (e.g. the catalog was built by scanning instead)."""
    manifest_path = project_root / "data" / "catalog" / "Catalog_PDS.manifest.json"
    if not manifest_path.exists():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        return payload if payload.get("catalog_key") == "pds" else None
    except Exception:
        return None


def local_raw_release(project_root: Path) -> dict[str, Any] | None:
    """RAW-catalog counterpart of `local_pds_release`."""
    manifest_path = project_root / "data" / "catalog" / "Catalog_RawArch.manifest.json"
    if not manifest_path.exists():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        return payload if payload.get("catalog_key") == "raw" else None
    except Exception:
        return None


def install_remote_pds_release(
    project_root: Path,
    progress: ProgressCallback | None = None,
    *,
    timeout: int = 120,
    target_dir: Path | None = None,
    _remote_manifest: dict[str, Any] | None = None,
    _download_impl: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Download and install the official PDS catalog release, verifying it end-to-end against `config/pds_release_manifest_schema.json`/`pds_catalog_schema.json` before and after the atomic swap into place.

    Skips the download entirely if `target_dir`'s existing parquet already
    matches the remote manifest's SHA-256 (registering the manifest alongside
    it if that's the only thing missing). On any validation or swap failure,
    restores the previous parquet+manifest so a bad download never leaves the
    catalog half-installed. `target_dir`/`_remote_manifest`/`_download_impl`
    are test-only overrides -- production callers use the defaults.
    """
    project_root = project_root.resolve()
    runtime_target = (project_root / "data" / "catalog").resolve()
    test_root = (project_root / "data" / "catalog_json_rebuild").resolve()
    target_dir = (target_dir or runtime_target).resolve()
    if target_dir != runtime_target and test_root not in target_dir.parents:
        raise RuntimeError("Unsafe catalog installation target")
    target_dir.mkdir(parents=True, exist_ok=True)
    config = load_distribution_config(project_root)["pds"]
    schema = project_root / "config" / "pds_release_manifest_schema.json"
    data_schema = project_root / "config" / "pds_catalog_schema.json"

    remote_manifest = _remote_manifest or fetch_remote_pds_manifest(project_root, timeout=timeout)
    download_impl = _download_impl or _download_file
    expected_hash = str(remote_manifest["parquet"]["sha256"])
    target_parquet = target_dir / "Catalog_PDS.parquet"
    target_manifest = target_dir / "Catalog_PDS.manifest.json"
    if target_parquet.exists() and _file_sha256(target_parquet) == expected_hash:
        if target_manifest.exists():
            return {"status": "already_current", "manifest": remote_manifest, "installed_path": str(target_parquet)}
        with tempfile.TemporaryDirectory(prefix=".pds-register-", dir=target_dir) as temporary:
            staged_manifest = Path(temporary) / "Catalog_PDS.manifest.json"
            staged_manifest.write_text(json.dumps(remote_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            errors = validate_release(target_parquet, staged_manifest, schema, data_schema)
            if errors:
                raise RuntimeError("Existing PDS catalog does not match the official release: " + "; ".join(errors))
            os.replace(staged_manifest, target_manifest)
        return {"status": "registered_existing", "manifest": remote_manifest, "installed_path": str(target_parquet)}

    with tempfile.TemporaryDirectory(prefix=".pds-release-", dir=target_dir) as temporary:
        staging = Path(temporary)
        staged_manifest = staging / "Catalog_PDS.manifest.json"
        staged_parquet = staging / "Catalog_PDS.parquet"
        staged_manifest.write_text(json.dumps(remote_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        download_impl(str(config["parquet"]["download_url"]), staged_parquet, progress, timeout=timeout)
        errors = validate_release(staged_parquet, staged_manifest, schema, data_schema)
        if errors:
            raise RuntimeError("Downloaded PDS release rejected: " + "; ".join(errors))

        previous_parquet = staging / "previous-Catalog_PDS.parquet"
        previous_manifest = staging / "previous-Catalog_PDS.manifest.json"
        try:
            if target_parquet.exists():
                os.replace(target_parquet, previous_parquet)
            if target_manifest.exists():
                os.replace(target_manifest, previous_manifest)
            os.replace(staged_parquet, target_parquet)
            os.replace(staged_manifest, target_manifest)
            final_errors = validate_release(target_parquet, target_manifest, schema, data_schema)
            if final_errors:
                raise RuntimeError("Installed PDS release failed final validation: " + "; ".join(final_errors))
        except Exception:
            if previous_parquet.exists():
                if target_parquet.exists():
                    target_parquet.unlink()
                os.replace(previous_parquet, target_parquet)
            if previous_manifest.exists():
                if target_manifest.exists():
                    target_manifest.unlink()
                os.replace(previous_manifest, target_manifest)
            raise

    return {"status": "installed", "manifest": remote_manifest, "installed_path": str(target_parquet)}


def install_remote_raw_release(
    project_root: Path,
    progress: ProgressCallback | None = None,
    *,
    timeout: int = 120,
    target_dir: Path | None = None,
    _remote_manifest: dict[str, Any] | None = None,
    _download_impl: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """RAW-catalog counterpart of `install_remote_pds_release` -- same download/verify/atomic-swap/rollback sequence, against `config/raw_catalog_schema.json`."""
    project_root = project_root.resolve()
    runtime_target = (project_root / "data" / "catalog").resolve()
    test_root = (project_root / "data" / "catalog_json_rebuild").resolve()
    target_dir = (target_dir or runtime_target).resolve()
    if target_dir != runtime_target and test_root not in target_dir.parents:
        raise RuntimeError("Unsafe catalog installation target")
    target_dir.mkdir(parents=True, exist_ok=True)
    config = load_distribution_config(project_root)["raw"]
    data_schema = project_root / "config" / "raw_catalog_schema.json"
    remote_manifest = _remote_manifest or fetch_remote_raw_manifest(project_root, timeout=timeout)
    download_impl = _download_impl or _download_file
    expected_hash = str(remote_manifest["parquet"]["sha256"])
    target_parquet = target_dir / "Catalog_RawArch.parquet"
    target_manifest = target_dir / "Catalog_RawArch.manifest.json"

    if target_parquet.exists() and _file_sha256(target_parquet) == expected_hash:
        if target_manifest.exists() and local_raw_release(project_root):
            return {"status": "already_current", "manifest": remote_manifest, "installed_path": str(target_parquet)}
        with tempfile.TemporaryDirectory(prefix=".raw-register-", dir=target_dir) as temporary:
            staged_manifest = Path(temporary) / "Catalog_RawArch.manifest.json"
            staged_manifest.write_text(json.dumps(remote_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            errors = validate_raw_release(target_parquet, staged_manifest, data_schema)
            if errors:
                raise RuntimeError("Existing RAW catalog does not match the official release: " + "; ".join(errors))
            os.replace(staged_manifest, target_manifest)
        return {"status": "registered_existing", "manifest": remote_manifest, "installed_path": str(target_parquet)}

    with tempfile.TemporaryDirectory(prefix=".raw-release-", dir=target_dir) as temporary:
        staging = Path(temporary)
        staged_manifest = staging / "Catalog_RawArch.manifest.json"
        staged_parquet = staging / "Catalog_RawArch.parquet"
        staged_manifest.write_text(json.dumps(remote_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        download_impl(str(config["parquet"]["download_url"]), staged_parquet, progress, timeout=timeout)
        errors = validate_raw_release(staged_parquet, staged_manifest, data_schema)
        if errors:
            raise RuntimeError("Downloaded RAW release rejected: " + "; ".join(errors))

        previous_parquet = staging / "previous-Catalog_RawArch.parquet"
        previous_manifest = staging / "previous-Catalog_RawArch.manifest.json"
        try:
            if target_parquet.exists():
                os.replace(target_parquet, previous_parquet)
            if target_manifest.exists():
                os.replace(target_manifest, previous_manifest)
            os.replace(staged_parquet, target_parquet)
            os.replace(staged_manifest, target_manifest)
            final_errors = validate_raw_release(target_parquet, target_manifest, data_schema)
            if final_errors:
                raise RuntimeError("Installed RAW release failed final validation: " + "; ".join(final_errors))
        except Exception:
            if previous_parquet.exists():
                target_parquet.unlink(missing_ok=True)
                os.replace(previous_parquet, target_parquet)
            if previous_manifest.exists():
                target_manifest.unlink(missing_ok=True)
                os.replace(previous_manifest, target_manifest)
            raise
    return {"status": "installed", "manifest": remote_manifest, "installed_path": str(target_parquet)}
