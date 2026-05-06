from __future__ import annotations

import argparse
import compileall
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"


def _fail(msg: str) -> None:
    raise SystemExit(f"[FAIL] {msg}")


def _ok(msg: str) -> None:
    print(f"[OK] {msg}")


def _warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        _fail(f"Invalid JSON: {path} ({exc})")


def _validate_json_tree(paths: list[Path]) -> None:
    json_files: list[Path] = []
    for base in paths:
        if not base.exists():
            continue
        json_files.extend(sorted(base.rglob("*.json")))

    if not json_files:
        _warn("No JSON files found to validate.")
        return

    for path in json_files:
        _read_json(path)
    _ok(f"JSON valid ({len(json_files)} files)")


def _compile_tree(paths: list[Path]) -> None:
    ok = True
    for p in paths:
        if not p.exists():
            continue
        ok = compileall.compile_dir(str(p), quiet=1) and ok
    if not ok:
        _fail("Python compile failed")
    _ok("Python compile (compileall)")


def _bootstrap_imports() -> None:
    # Make top-level imports match the way the app is normally run from `cd app`.
    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    if str(CORE_DIR) not in sys.path:
        sys.path.insert(0, str(CORE_DIR))
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))


def _check_runtime_paths() -> dict[str, Any]:
    cfg_path = PROJECT_ROOT / "config" / "runtime_paths.json"
    if not cfg_path.exists():
        _fail(f"Missing runtime paths: {cfg_path}")
    cfg = _read_json(cfg_path)
    if not isinstance(cfg, dict):
        _fail(f"runtime_paths.json is not an object: {cfg_path}")

    required = ["catalog_parquet", "catalog_parquet_raw", "intent_config"]
    for k in required:
        if not cfg.get(k):
            _fail(f"runtime_paths.json missing key `{k}`")

    # Resolve and check existence for the core runtime inputs.
    missing: list[str] = []
    for k in required + ["catalog_json"]:
        rel = cfg.get(k)
        if not rel:
            continue
        p = (PROJECT_ROOT / str(rel)).resolve()
        if not p.exists():
            missing.append(f"{k} -> {p}")

    if missing:
        # catalog_json is allowed to be absent depending on the current policy.
        hard_missing = [m for m in missing if not m.startswith("catalog_json -> ")]
        if hard_missing:
            _fail("Missing runtime path(s): " + "; ".join(hard_missing))
        _warn("Optional runtime path missing: " + "; ".join(missing))

    _ok("runtime_paths.json sanity")
    return cfg


def _check_catalog_parquet(path: Path, expect_cols: set[str]) -> None:
    import pandas as pd
    import pyarrow.parquet as pq

    if not path.exists():
        _fail(f"Missing parquet: {path}")

    schema = pq.read_schema(path)
    cols = set(schema.names)
    missing = sorted(expect_cols - cols)
    if missing:
        _fail(f"Parquet schema missing columns in {path.name}: {missing}")

    # Minimal read to ensure the file is readable and non-empty.
    df = pd.read_parquet(path, columns=sorted(expect_cols))
    if df.empty:
        _fail(f"Parquet is empty: {path}")
    _ok(f"Parquet readable: {path.name} ({len(df)} rows sampled cols={len(expect_cols)})")


def _check_camera_rules_compile() -> None:
    import catalog

    compiled = catalog.load_compiled_camera_rules()
    items = compiled.get("items") if isinstance(compiled, dict) else None
    if not isinstance(items, list) or not items:
        _fail("camera rules compilation produced no items")

    # Ensure hazcam/navcam have constraints for PDS (mask pairing logic depends on this pipeline).
    keys = {it.get("camera_key") for it in items if isinstance(it, dict)}
    for required in ("hazcam", "navcam"):
        if required not in keys:
            _warn(f"camera_rules missing expected camera `{required}` (compiled keys={sorted(k for k in keys if k)})")

    _ok("camera_rules compiled")


def _check_imports() -> None:
    # These imports should succeed when sys.path is bootstrapped like `cd app`.
    import runtime  # noqa: F401
    import catalog  # noqa: F401
    import actions  # noqa: F401
    import services.action_dataframe_preparer  # noqa: F401
    import services.output_organizer  # noqa: F401
    _ok("core imports (app modules)")


def _check_mastcam_bayer_pipeline() -> None:
    try:
        import actions  # type: ignore

        pipe, cfg_path = actions._load_mastcam_bayer_pipeline()  # type: ignore[attr-defined]
        if pipe is None or cfg_path is None:
            err = getattr(actions, "_MASTCAM_BAYER_PIPELINE_ERROR", None)
            if err:
                _warn(f"Mastcam Bayer pipeline unavailable ({err})")
            else:
                _warn("Mastcam Bayer pipeline unavailable")
            return
        _ok(f"Mastcam Bayer pipeline available (cfg={cfg_path.name})")
    except Exception as exc:
        _warn(f"Mastcam Bayer pipeline check failed ({type(exc).__name__}: {exc})")


def main() -> int:
    parser = argparse.ArgumentParser(description="DWNAPP pre-publish smoke checks (no UI).")
    parser.add_argument("--skip-catalog", action="store_true", help="Skip reading catalog parquet files.")
    args = parser.parse_args()

    _compile_tree([APP_DIR, CORE_DIR, PROJECT_ROOT / "scripts"])
    _validate_json_tree([PROJECT_ROOT / "config", APP_DIR])

    _bootstrap_imports()
    _check_imports()
    _check_camera_rules_compile()
    _check_mastcam_bayer_pipeline()

    cfg = _check_runtime_paths()
    if not args.skip_catalog:
        pds = (PROJECT_ROOT / str(cfg["catalog_parquet"])).resolve()
        raw = (PROJECT_ROOT / str(cfg["catalog_parquet_raw"])).resolve()
        expect = {"product_id", "sol", "img_url", "img_name"}
        _check_catalog_parquet(pds, expect_cols=expect)
        _check_catalog_parquet(raw, expect_cols=expect)

    print("[DONE] Smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
