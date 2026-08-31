"""Censimento in sola lettura dei tipi di prodotto MSL pubblicati nel PDS NASA.

Lo script visita solamente le directory HTML: non scarica IMG, TIF o LBL e non
modifica i cataloghi dell'applicazione.  Conserva firme strutturali, combinazioni
osservate ed esempi, senza scartare a priori codici sconosciuti.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

STANDARD_CAMERAS = ("mastcam", "mahli", "navcam", "hazcam", "mardi")
ALL_CAMERAS = (*STANDARD_CAMERAS, "chemcam")
IMAGE_EXTENSIONS = {".IMG", ".TIF", ".TIFF"}
KNOWN_MMM_SUFFIXES = {"DXXX", "DRXX", "DRCX", "DRLX", "DRCL"}
CHEMCAM_RDR_DATA_URL = (
    "https://pds-geosciences.wustl.edu/msl/"
    "msl-m-chemcam-libs-4_5-rdr-v1/mslccm_1xxx/data/"
)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        href = next((value for name, value in attrs if name.casefold() == "href"), None)
        if href:
            self.hrefs.append(unquote(href.strip()))


class HttpClient:
    def __init__(self, timeout: int, retries: int) -> None:
        self.timeout = timeout
        self.retries = retries

    def get_text(self, url: str) -> str:
        last_error: BaseException | None = None
        for attempt in range(self.retries + 1):
            try:
                request = Request(url, headers={"User-Agent": "MSL-PDS-product-census/1.0"})
                with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                    return response.read().decode("utf-8", errors="replace")
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(4.0, 0.5 * (2**attempt)))
        raise RuntimeError(f"GET fallita per {url}: {last_error}")


def _hrefs(html: str) -> list[str]:
    parser = _LinkParser()
    parser.feed(html)
    return parser.hrefs


def _parse_sol(href: str) -> int | None:
    name = Path(urlparse(href).path.rstrip("/")).name
    match = re.fullmatch(r"(?:SOL)?0*(\d+)", name, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _discover_collections(client: HttpClient, base_url: str, token: str) -> list[str]:
    return sorted({href for href in _hrefs(client.get_text(base_url)) if href.endswith("/") and token in href})


def _discover_sol_urls(client: HttpClient, root_url: str) -> dict[int, str]:
    result: dict[int, str] = {}
    for href in _hrefs(client.get_text(root_url)):
        sol = _parse_sol(href)
        if sol is not None:
            result[sol] = urljoin(root_url, href.rstrip("/") + "/")
    return result


def _normalised_template(product_id: str) -> str:
    """Rende visibili le parti alfabetiche senza creare migliaia di firme."""
    return re.sub(r"\d+", "#", product_id.upper())


def _alpha_tokens(product_id: str) -> list[str]:
    return sorted(set(re.findall(r"[A-Z][A-Z_]{1,}", product_id.upper())))


def _structural_fields(camera: str, product_id: str) -> dict[str, str]:
    upper = product_id.upper()
    first = upper.split("_", 1)[0]
    fields = {
        "camera_prefix": first[:3] if len(first) >= 3 else first,
        "template": _normalised_template(upper),
    }
    if camera in {"mastcam", "mahli", "mardi"}:
        descriptor = first[-3:] if len(first) >= 25 else first[-2:]
        fields["descriptor"] = descriptor
        fields["product_type"] = descriptor[0] if descriptor else ""
        suffix = upper.rsplit("_", 1)[-1]
        fields["processing_suffix"] = suffix
        fields["known_mmm_suffix"] = "yes" if suffix in KNOWN_MMM_SUFFIXES else "no"
    else:
        # Engineering cameras: PPP_<SCLK><5-character product code>...
        # Esempi: NLB_694975792EDR_F... oppure FLB_694614126ILTLF...
        match = re.match(r"^[A-Z0-9]{3}_\d+([A-Z0-9_]{5})", upper)
        fields["product_code"] = match.group(1) if match else ""
        fields["underscore_tokens"] = "|".join(_alpha_tokens(upper))
    return fields


class Inventory:
    def __init__(self, examples_per_combination: int) -> None:
        self.examples_per_combination = examples_per_combination
        self.lock = threading.Lock()
        self.counts: Counter[tuple[str, str, str, str, str]] = Counter()
        self.examples: dict[tuple[str, str, str, str, str], list[str]] = defaultdict(list)
        self.combination_sols: dict[tuple[str, str, str, str, str], set[int]] = defaultdict(set)
        self.camera_totals: Counter[str] = Counter()
        self.sols: dict[str, set[int]] = defaultdict(set)
        self.errors: list[dict[str, str]] = []

    def add(self, camera: str, sol: int, product_id: str, extension: str) -> None:
        fields = _structural_fields(camera, product_id)
        key = (
            camera,
            fields.get("camera_prefix", ""),
            fields.get("descriptor") or fields.get("product_code") or fields.get("underscore_tokens", ""),
            fields.get("processing_suffix", ""),
            extension.upper(),
        )
        with self.lock:
            self.counts[key] += 1
            self.combination_sols[key].add(sol)
            self.camera_totals[camera] += 1
            self.sols[camera].add(sol)
            samples = self.examples[key]
            if len(samples) < self.examples_per_combination and product_id not in samples:
                samples.append(product_id)

    def error(self, camera: str, url: str, exc: BaseException) -> None:
        with self.lock:
            self.errors.append({"camera": camera, "url": url, "error": f"{type(exc).__name__}: {exc}"})


def _scan_listing(client: HttpClient, inventory: Inventory, camera: str, sol: int, url: str) -> None:
    try:
        html = client.get_text(url)
        for href in _hrefs(html):
            href = href.strip()
            if not href or href.endswith("/"):
                continue
            path = Path(href)
            extension = path.suffix.upper()
            if extension in IMAGE_EXTENSIONS:
                inventory.add(camera, sol, path.stem, extension.lstrip("."))
    except Exception as exc:  # noqa: BLE001
        inventory.error(camera, url, exc)


def _locations(
    client: HttpClient,
    config: dict[str, Any],
    cameras: Iterable[str],
    sol_start: int | None,
    sol_end: int | None,
    workers: int,
    sample_step: int,
    window_radius: int,
    full_scan: bool,
) -> list[tuple[str, int, str]]:
    base_url = str(config["base_url"])
    camera_config = config["camera_config"]
    discovered: list[tuple[str, int, str]] = []
    discovery_tasks: list[tuple[str, str]] = []
    for camera in cameras:
        if camera == "chemcam":
            for sol, url in _discover_sol_urls(client, CHEMCAM_RDR_DATA_URL).items():
                if (sol_start is None or sol >= sol_start) and (sol_end is None or sol <= sol_end):
                    discovered.append((camera, sol, url))
            continue
        rule = camera_config[camera]
        collections = _discover_collections(client, base_url, str(rule["collection_token"]))
        print(f"[{camera}] collezioni trovate: {len(collections)}", flush=True)
        for collection in collections:
            for data_root in rule["data_roots"]:
                root_url = urljoin(base_url, f"{collection}{data_root}")
                discovery_tasks.append((camera, root_url))

    seen: set[str] = set()
    completed = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(_discover_sol_urls, client, root_url): (camera, root_url)
            for camera, root_url in discovery_tasks
        }
        for future in as_completed(futures):
            camera, root_url = futures[future]
            completed += 1
            try:
                sols = future.result()
            except Exception as exc:  # noqa: BLE001
                print(f"[{camera}] directory non accessibile: {root_url} | {exc}", flush=True)
                continue
            if completed == 1 or completed % 25 == 0 or completed == len(futures):
                print(f"[scoperta {completed}/{len(futures)}]", flush=True)
            for sol, sol_url in sols.items():
                if sol_start is not None and sol < sol_start:
                    continue
                if sol_end is not None and sol > sol_end:
                    continue
                if sol_url not in seen:
                    seen.add(sol_url)
                    discovered.append((camera, sol, sol_url))

    if full_scan:
        return discovered

    origin = sol_start or 0

    def sampled(sol: int) -> bool:
        if sol < origin:
            return False
        offset = (sol - origin) % sample_step
        distance = min(offset, sample_step - offset)
        return distance <= window_radius

    return [location for location in discovered if sampled(location[1])]


def _write_outputs(
    inventory: Inventory,
    output_dir: Path,
    elapsed: float,
    directories: int,
    sampling: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for key, count in sorted(inventory.counts.items()):
        camera, prefix, descriptor_or_tokens, suffix, extension = key
        combination_sols = inventory.combination_sols[key]
        rows.append(
            {
                "camera": camera,
                "camera_prefix": prefix,
                "descriptor_or_tokens": descriptor_or_tokens,
                "processing_suffix": suffix,
                "extension": extension,
                "count": count,
                "first_sampled_sol": min(combination_sols),
                "last_sampled_sol": max(combination_sols),
                "sampled_sols_with_products": len(combination_sols),
                "examples": inventory.examples[key],
            }
        )
    cameras: dict[str, dict[str, Any]] = {}
    for camera in sorted(inventory.camera_totals):
        camera_rows = [row for row in rows if row["camera"] == camera]
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in camera_rows:
            family = str(row["camera_prefix"] or "unknown")
            grouped[family].append(
                {
                    "descriptor_or_product_code": row["descriptor_or_tokens"],
                    "processing_suffix": row["processing_suffix"],
                    "extension": row["extension"],
                    "count": row["count"],
                    "first_sampled_sol": row["first_sampled_sol"],
                    "last_sampled_sol": row["last_sampled_sol"],
                    "sampled_sols_with_products": row["sampled_sols_with_products"],
                    "examples": row["examples"],
                }
            )
        cameras[camera] = {
            "total_products_observed": inventory.camera_totals[camera],
            "sampled_sol_range_with_products": {
                "min": min(inventory.sols[camera]),
                "max": max(inventory.sols[camera]),
                "count": len(inventory.sols[camera]),
            },
            "families": dict(sorted(grouped.items())),
        }
    payload = {
        "generated_at_unix": time.time(),
        "elapsed_seconds": round(elapsed, 3),
        "directories_scanned": directories,
        "products_found": sum(inventory.camera_totals.values()),
        "sampling": sampling,
        "cameras": cameras,
        "camera_totals": dict(sorted(inventory.camera_totals.items())),
        "sol_ranges": {
            camera: {"min": min(sols), "max": max(sols), "count": len(sols)}
            for camera, sols in sorted(inventory.sols.items()) if sols
        },
        "combinations": rows,
        "errors": inventory.errors,
    }
    (output_dir / "pds_product_census.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with (output_dir / "pds_product_census.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("camera", "camera_prefix", "descriptor_or_tokens", "processing_suffix", "extension", "count", "first_sampled_sol", "last_sampled_sol", "sampled_sols_with_products", "examples"),
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "examples": " | ".join(row["examples"])})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cameras", nargs="+", choices=ALL_CAMERAS, default=list(ALL_CAMERAS))
    parser.add_argument("--sol-start", type=int)
    parser.add_argument("--sol-end", type=int)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--examples", type=int, default=3)
    parser.add_argument("--sample-step", type=int, default=250, help="Distanza tra i Sol centrali campionati")
    parser.add_argument("--window-radius", type=int, default=5, help="Sol inclusi prima e dopo ogni centro")
    parser.add_argument("--full-scan", action="store_true", help="Analizza ogni Sol invece del campionamento")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "analysis_output" / "pds_product_census")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.sol_start is not None and args.sol_end is not None and args.sol_start > args.sol_end:
        raise SystemExit("--sol-start non può essere maggiore di --sol-end")
    if args.sample_step < 1 or args.window_radius < 0:
        raise SystemExit("--sample-step deve essere positivo e --window-radius non negativo")
    config = json.loads((PROJECT_ROOT / "config" / "msl_catalog_config.json").read_text(encoding="utf-8"))
    client = HttpClient(timeout=args.timeout, retries=args.retries)
    started = time.monotonic()
    locations = _locations(
        client, config, args.cameras, args.sol_start, args.sol_end, args.workers,
        args.sample_step, args.window_radius, args.full_scan,
    )
    print(f"Directory da analizzare: {len(locations)}", flush=True)
    inventory = Inventory(max(1, args.examples))
    completed = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [executor.submit(_scan_listing, client, inventory, *location) for location in locations]
        for future in as_completed(futures):
            future.result()
            completed += 1
            if completed == 1 or completed % 50 == 0 or completed == len(locations):
                print(
                    f"[{completed}/{len(locations)}] prodotti={sum(inventory.camera_totals.values())} "
                    f"errori={len(inventory.errors)}",
                    flush=True,
                )
    elapsed = time.monotonic() - started
    sampled_sols = sorted({sol for _, sol, _ in locations})
    sampling = {
        "mode": "full_scan" if args.full_scan else "periodic_windows",
        "step": None if args.full_scan else args.sample_step,
        "window_radius": None if args.full_scan else args.window_radius,
        "requested_sol_start": args.sol_start,
        "requested_sol_end": args.sol_end,
        "sampled_sol_count": len(sampled_sols),
        "sampled_sols": sampled_sols,
        "note": "Inventario dei prodotti osservati nel campionamento; non garantisce la presenza di prodotti rari fuori dalle finestre.",
    }
    _write_outputs(inventory, args.output_dir.resolve(), elapsed, len(locations), sampling)
    print(f"Censimento completato in {elapsed:.1f} s", flush=True)
    print(f"JSON: {(args.output_dir / 'pds_product_census.json').resolve()}", flush=True)
    print(f"CSV:  {(args.output_dir / 'pds_product_census.csv').resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
