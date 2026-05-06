from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional


EventCallback = Callable[[dict[str, Any]], None]


@dataclass
class CatalogUpdateOptions:
    config_path: str | Path
    cameras: Optional[list[str]] = None
    sol_start: Optional[int] = None
    sol_end: Optional[int] = None
    workers: Optional[int] = None
    min_img_size_bytes_for_lbl: Optional[int] = None
    checkpoint_every_products: Optional[int] = None
    checkpoint_write_parquet: bool = False
    refresh_sol_index: bool = False
    quiet: bool = False
    output: Optional[str | Path] = None


def _emit(cb: Optional[EventCallback], stage: str, message: str, **payload: Any) -> None:
    if cb is None:
        return
    cb({"stage": stage, "message": message, **payload})


def build_catalog_update_command(
    *,
    script_path: str | Path,
    options: CatalogUpdateOptions,
    python_executable: Optional[str] = None,
) -> list[str]:
    cmd: list[str] = [python_executable or sys.executable, str(Path(script_path).resolve())]
    cmd += ["--config", str(Path(options.config_path).expanduser())]

    if options.cameras:
        cmd += ["--cameras", *[str(c) for c in options.cameras]]
    if options.sol_start is not None:
        cmd += ["--sol-start", str(int(options.sol_start))]
    if options.sol_end is not None:
        cmd += ["--sol-end", str(int(options.sol_end))]
    if options.workers is not None:
        cmd += ["--workers", str(int(options.workers))]
    if options.min_img_size_bytes_for_lbl is not None:
        cmd += ["--min-img-size-bytes-for-lbl", str(int(options.min_img_size_bytes_for_lbl))]
    if options.checkpoint_every_products is not None:
        cmd += ["--checkpoint-every-products", str(int(options.checkpoint_every_products))]
    if options.checkpoint_write_parquet:
        cmd += ["--checkpoint-write-parquet"]
    if options.refresh_sol_index:
        cmd += ["--refresh-sol-index"]
    if options.quiet:
        cmd += ["--quiet"]
    if options.output is not None:
        cmd += ["--output", str(Path(options.output).expanduser())]

    return cmd


def run_catalog_update(
    *,
    project_root: str | Path,
    options: CatalogUpdateOptions,
    event_callback: Optional[EventCallback] = None,
    python_executable: Optional[str] = None,
) -> dict[str, Any]:
    """
    Run `make_msl_catalog.py` as a subprocess and stream stdout lines as events.

    Designed to be called from dashboards so catalog update can be triggered
    from UI controls without duplicating CLI logic.
    """
    root = Path(project_root).expanduser().resolve()
    script_path = root / "core" / "make_msl_catalog.py"
    if not script_path.exists():
        raise FileNotFoundError(f"core/make_msl_catalog.py not found in: {root}")

    cmd = build_catalog_update_command(
        script_path=script_path,
        options=options,
        python_executable=python_executable,
    )

    _emit(event_callback, "catalog_update_start", "Starting catalog update process", command=cmd)

    proc = subprocess.Popen(
        cmd,
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )

    lines: list[str] = []
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip("\n")
        lines.append(line)
        _emit(event_callback, "catalog_update_log", line, line=line)

    return_code = proc.wait()
    ok = return_code == 0
    _emit(
        event_callback,
        "catalog_update_done",
        "Catalog update finished" if ok else "Catalog update failed",
        return_code=return_code,
        ok=ok,
    )
    return {"ok": ok, "return_code": return_code, "command": cmd, "log_lines": lines}
