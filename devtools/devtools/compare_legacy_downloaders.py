from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, SoupStrainer


RAW_MANIFEST_URLS = (
    "http://mars.jpl.nasa.gov/msl-raw-images/image/image_manifest.json",
    "https://mars.jpl.nasa.gov/msl-raw-images/image/image_manifest.json",
)
PDS_BASE_URL = "https://planetarydata.jpl.nasa.gov/img/data/msl/"


def get_json(session: requests.Session, urls: tuple[str, ...]) -> tuple[dict, str]:
    errors: list[str] = []
    for url in urls:
        try:
            response = session.get(url, timeout=60)
            response.raise_for_status()
            return response.json(), response.url
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    raise RuntimeError("; ".join(errors))


def hrefs(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml", parse_only=SoupStrainer("a"))
    return [str(node.get("href")) for node in soup.find_all("a", href=True)]


def download(session: requests.Session, url: str, target: Path) -> dict[str, object]:
    started = time.perf_counter()
    result: dict[str, object] = {"url": url, "file": target.name}
    if target.exists() and target.stat().st_size > 0:
        result.update(status="skipped", size_bytes=target.stat().st_size, elapsed_seconds=0.0)
        return result
    try:
        response = session.get(url, stream=True, timeout=120)
        response.raise_for_status()
        temp = target.with_suffix(target.suffix + ".part")
        with temp.open("wb") as stream:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    stream.write(chunk)
        temp.replace(target)
        result.update(status="ok", size_bytes=target.stat().st_size)
    except Exception as exc:
        result.update(status="error", error=f"{type(exc).__name__}: {exc}")
    result["elapsed_seconds"] = round(time.perf_counter() - started, 6)
    return result


def raw_products(session: requests.Session, sol_start: int, sol_end: int, limit: int) -> tuple[list[dict], str]:
    root, manifest_url = get_json(session, RAW_MANIFEST_URLS)
    products: list[dict] = []
    for sol_item in root.get("sols", []):
        sol = int(sol_item.get("sol", -1))
        if not sol_start <= sol <= sol_end:
            continue
        catalog_url = str(sol_item.get("catalog_url", ""))
        if not catalog_url:
            continue
        response = session.get(catalog_url, timeout=60)
        response.raise_for_status()
        for item in response.json().get("images", []):
            instrument = str(item.get("instrument", ""))
            sample_type = str(item.get("sampleType", ""))
            url = str(item.get("urlList", ""))
            # Exact Mastcam rule from MSL_JSON_JPL.py.
            if "MAST" not in instrument or sample_type == "thumbnail":
                continue
            if "E01_" not in url and "E1_" not in url:
                continue
            products.append({"sol": sol, "url": url, "instrument": instrument, "sample_type": sample_type})
            if len(products) >= limit:
                return products, manifest_url
    return products, manifest_url


def discover_pds_products(session: requests.Session, sol_start: int, sol_end: int, limit: int) -> list[dict]:
    response = session.get(PDS_BASE_URL, timeout=60)
    response.raise_for_status()
    collections = sorted(
        urljoin(PDS_BASE_URL, link)
        for link in hrefs(response.text)
        if "MSLMST_" in link and ".txt" not in link
    )
    products: list[dict] = []
    seen: set[str] = set()
    for collection_url in collections:
        root_url = urljoin(collection_url, "DATA/RDR/SURFACE/")
        root_response = session.get(root_url, timeout=60)
        if root_response.status_code != 200:
            continue
        for sol_link in hrefs(root_response.text):
            clean = sol_link.rstrip("/")
            digits = "".join(ch for ch in clean if ch.isdigit())
            if len(digits) < 4:
                continue
            sol = int(digits[-4:])
            if not sol_start <= sol <= sol_end:
                continue
            sol_url = urljoin(root_url, sol_link)
            sol_response = session.get(sol_url, timeout=60)
            if sol_response.status_code != 200:
                continue
            names = hrefs(sol_response.text)
            img_names = sorted(
                name for name in names
                if name.upper().endswith(".IMG")
                and "DRCL" in name.upper()
                and any(token in name.upper() for token in ("E01_", "E1_", "C00_"))
            )
            name_set = {name.upper(): name for name in names}
            for img_name in img_names:
                product_id = Path(img_name).stem
                key = f"{sol}:{product_id}"
                if key in seen:
                    continue
                seen.add(key)
                lbl_lookup = f"{product_id}.LBL".upper()
                lbl_name = name_set.get(lbl_lookup)
                products.append(
                    {
                        "sol": sol,
                        "product_id": product_id,
                        "img_url": urljoin(sol_url, img_name),
                        "lbl_url": urljoin(sol_url, lbl_name) if lbl_name else None,
                        "collection_url": collection_url,
                    }
                )
                if len(products) >= limit:
                    return products
    return products


def write_manifest(folder: Path, payload: dict) -> None:
    (folder / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_raw(session: requests.Session, root: Path, start: int, end: int, limit: int) -> None:
    folder = root / "codice_1_raw_json"
    folder.mkdir(parents=True, exist_ok=True)
    products, source_url = raw_products(session, start, end, limit)
    results = [download(session, item["url"], folder / Path(item["url"]).name) for item in products]
    write_manifest(folder, {"code": "MSL_JSON_JPL.py", "source": source_url, "sol_range": [start, end], "limit": limit, "selection": products, "downloads": results})


def run_pds(session: requests.Session, root: Path, start: int, end: int, limit: int, *, parallel: bool) -> None:
    code = "codice_2_pds_parallel" if parallel else "codice_3_pds_2020"
    source = "MSL_PDS_parallelized.py" if parallel else "MSL_PDS_OK_2020.py"
    folder = root / code
    folder.mkdir(parents=True, exist_ok=True)
    products = discover_pds_products(session, start, end, limit)
    jobs: list[tuple[str, Path]] = []
    for item in products:
        jobs.append((item["img_url"], folder / Path(item["img_url"]).name))
        if item.get("lbl_url"):
            jobs.append((item["lbl_url"], folder / Path(item["lbl_url"]).name))
    if parallel:
        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=32) as executor:
            futures = {executor.submit(download, requests.Session(), url, target): url for url, target in jobs}
            for future in as_completed(futures):
                results.append(future.result())
        # Exact recovery policy from MSL_PDS_parallelized.py: retry every
        # failed URL sequentially after the concurrent pass.
        failed_names = {str(item.get("file")) for item in results if item.get("status") == "error"}
        for url, target in jobs:
            if target.name in failed_names:
                retry = download(session, url, target)
                retry["retry"] = "sequential_after_parallel_failure"
                results.append(retry)
    else:
        results = [download(session, url, target) for url, target in jobs]
    write_manifest(folder, {"code": source, "source": PDS_BASE_URL, "sol_range": [start, end], "limit": limit, "selection": products, "downloads": results})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sol-start", type=int, default=3347)
    parser.add_argument("--sol-end", type=int, default=3350)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--only", choices=("raw", "pds_parallel", "pds_2020", "all"), default="all")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with requests.Session() as session:
        if args.only in {"raw", "all"}:
            run_raw(session, args.output, args.sol_start, args.sol_end, args.limit)
        if args.only in {"pds_parallel", "all"}:
            run_pds(session, args.output, args.sol_start, args.sol_end, args.limit, parallel=True)
        if args.only in {"pds_2020", "all"}:
            run_pds(session, args.output, args.sol_start, args.sol_end, args.limit, parallel=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
