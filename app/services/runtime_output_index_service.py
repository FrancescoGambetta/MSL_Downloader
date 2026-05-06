from __future__ import annotations

import heapq
import os
from pathlib import Path
from typing import Any, Callable, Optional
from datetime import datetime


class RuntimeOutputIndexService:
    def __init__(
        self,
        *,
        normalize_text: Callable[[Any], str],
        display_image_name_from_output_file: Callable[[str], str],
        now: Callable[[], datetime],
    ) -> None:
        self._normalize_text = normalize_text
        self._display_image_name_from_output_file = display_image_name_from_output_file
        self._now = now

    def refresh_saved_output_files(self, state: dict[str, Any], *, limit: int = 400) -> None:
        path = self._normalize_text(state.get("download_path", ""))
        if not path:
            state["saved_output_files"] = []
            return
        out = Path(path).expanduser()
        if not out.exists() or not out.is_dir():
            state["saved_output_files"] = []
            return

        # Only index final/previewable outputs; PDS .IMG/.LBL can be huge and are not useful in the UI list.
        accepted = {".jpg", ".jpeg", ".png"}

        # Prefer scanning well-known buckets to avoid recursively traversing the entire download folder.
        roots: list[Path] = []
        pds = out / "PDS"
        raw = out / "RAW_PHOTOS"
        if pds.exists() and pds.is_dir():
            roots.append(pds)
        if raw.exists() and raw.is_dir():
            roots.append(raw)
        if not roots:
            roots = [out]

        # Scan budget to prevent UI freezes on large folders.
        max_dirs = 5000
        max_files = 50000
        dirs_scanned = 0
        files_scanned = 0

        # Keep only the N most-recent files without sorting the full directory listing.
        # Heap stores (mtime, filename).
        heap: list[tuple[float, str]] = []

        def consider(mtime: float, name: str) -> None:
            nonlocal heap
            if not name:
                return
            if len(heap) < max(1, int(limit)):
                heapq.heappush(heap, (mtime, name))
                return
            if heap and mtime > heap[0][0]:
                heapq.heapreplace(heap, (mtime, name))

        def scan_root(root: Path, recursive: bool) -> None:
            nonlocal dirs_scanned, files_scanned
            stack: list[str] = [str(root)]
            while stack:
                if dirs_scanned >= max_dirs or files_scanned >= max_files:
                    return
                cur = stack.pop()
                dirs_scanned += 1
                try:
                    with os.scandir(cur) as it:
                        for ent in it:
                            try:
                                if ent.is_dir(follow_symlinks=False):
                                    if recursive:
                                        stack.append(ent.path)
                                    continue
                                if not ent.is_file(follow_symlinks=False):
                                    continue
                                name = ent.name
                                low = name.lower()
                                suf = Path(name).suffix.lower()
                                if suf not in accepted and not low.endswith(".meta.json"):
                                    continue
                                st = ent.stat()
                                consider(float(st.st_mtime), name)
                                files_scanned += 1
                                if files_scanned >= max_files:
                                    return
                            except Exception:
                                continue
                except Exception:
                    continue

        for r in roots:
            # If we're scanning the overall output root (no buckets present), avoid recursion by default.
            scan_root(r, recursive=(r.resolve() != out.resolve()))

        # Sort only the small heap.
        heap.sort(key=lambda t: t[0], reverse=True)
        names: list[str] = []
        seen: set[str] = set()
        for _, fname in heap:
            display = self._display_image_name_from_output_file(fname)
            if not display or display in seen:
                continue
            seen.add(display)
            names.append(display)
            if len(names) >= int(limit):
                break
        state["saved_output_files"] = names

    def output_bucket_roots(self, out: Path) -> list[Path]:
        roots: list[Path] = []
        pds = out / "PDS"
        raw = out / "RAW_PHOTOS"
        if pds.exists() and pds.is_dir():
            roots.append(pds)
        if raw.exists() and raw.is_dir():
            roots.append(raw)
        if not roots:
            roots = [out]
        return roots

    def output_index_base_name(self, filename: str) -> str:
        name = self._normalize_text(filename)
        if not name:
            return ""
        low = name.lower()
        if low.endswith(".meta.json"):
            return name[: -len(".meta.json")]
        return Path(name).stem

    def ensure_output_file_index(
        self,
        state: dict[str, Any],
        out: Path,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Build/return an in-memory index for local outputs so we can resolve product files
        without doing expensive rglob() scans.
        """
        key = "_output_file_index_state"
        cur = state.get(key)
        root = str(out.resolve())
        if (
            not force
            and isinstance(cur, dict)
            and self._normalize_text(cur.get("root")) == root
            and isinstance(cur.get("index"), dict)
        ):
            return cur

        accepted = {".jpg", ".jpeg", ".png"}
        max_dirs = 8000
        max_files = 120000
        dirs_scanned = 0
        files_scanned = 0

        # index[base] = {"image": (prio, mtime, path), "meta": (mtime, path)}
        index: dict[str, dict[str, Any]] = {}
        img_prio = {".png": 3, ".jpg": 2, ".jpeg": 1}

        def consider_file(full_path: str, name: str, mtime: float) -> None:
            base = self.output_index_base_name(name)
            if not base:
                return
            entry = index.get(base)
            if entry is None:
                entry = {}
                index[base] = entry
            low = name.lower()
            if low.endswith(".meta.json"):
                prev = entry.get("meta")
                if not isinstance(prev, tuple) or mtime >= float(prev[0]):
                    entry["meta"] = (float(mtime), full_path)
                return
            suf = Path(name).suffix.lower()
            pr = int(img_prio.get(suf, 0))
            if pr <= 0:
                return
            prev = entry.get("image")
            if not isinstance(prev, tuple):
                entry["image"] = (pr, float(mtime), full_path)
                return
            prev_pr, prev_mt, _ = prev
            if pr > int(prev_pr) or (pr == int(prev_pr) and float(mtime) >= float(prev_mt)):
                entry["image"] = (pr, float(mtime), full_path)

        def scan_root(root_dir: Path, *, recursive: bool) -> None:
            nonlocal dirs_scanned, files_scanned
            stack: list[str] = [str(root_dir)]
            while stack:
                if dirs_scanned >= max_dirs or files_scanned >= max_files:
                    return
                cur_dir = stack.pop()
                dirs_scanned += 1
                try:
                    with os.scandir(cur_dir) as it:
                        for ent in it:
                            try:
                                if ent.is_dir(follow_symlinks=False):
                                    if recursive:
                                        stack.append(ent.path)
                                    continue
                                if not ent.is_file(follow_symlinks=False):
                                    continue
                                name = ent.name
                                low = name.lower()
                                suf = Path(name).suffix.lower()
                                if suf not in accepted and not low.endswith(".meta.json"):
                                    continue
                                stinfo = ent.stat()
                                consider_file(ent.path, name, float(stinfo.st_mtime))
                                files_scanned += 1
                                if files_scanned >= max_files:
                                    return
                            except Exception:
                                continue
                except Exception:
                    continue

        roots = self.output_bucket_roots(out)
        for r in roots:
            scan_root(r, recursive=True)

        out_state = {
            "root": root,
            "built_at": self._now().isoformat(timespec="seconds"),
            "dirs_scanned": int(dirs_scanned),
            "files_scanned": int(files_scanned),
            "index": index,
        }
        state[key] = out_state
        return out_state

    def index_note_new_file(self, state: dict[str, Any], out: Path, file_path: Path) -> None:
        state_obj = self.ensure_output_file_index(state, out, force=False)
        index = state_obj.get("index")
        if not isinstance(index, dict):
            return
        name = file_path.name
        base = self.output_index_base_name(name)
        if not base:
            return
        try:
            mtime = float(file_path.stat().st_mtime)
        except Exception:
            mtime = 0.0

        entry = index.get(base)
        if entry is None:
            entry = {}
            index[base] = entry
        low = name.lower()
        if low.endswith(".meta.json"):
            prev = entry.get("meta")
            if not isinstance(prev, tuple) or mtime >= float(prev[0]):
                entry["meta"] = (mtime, str(file_path))
            return
        suf = file_path.suffix.lower()
        img_prio = {".png": 3, ".jpg": 2, ".jpeg": 1}
        pr = int(img_prio.get(suf, 0))
        if pr <= 0:
            return
        prev = entry.get("image")
        if not isinstance(prev, tuple):
            entry["image"] = (pr, mtime, str(file_path))
            return
        prev_pr, prev_mt, _ = prev
        if pr > int(prev_pr) or (pr == int(prev_pr) and float(mtime) >= float(prev_mt)):
            entry["image"] = (pr, mtime, str(file_path))

    def find_file_by_exact_name(self, out: Path, filename: str, *, max_dirs: int = 12000) -> Optional[Path]:
        """
        Cheap exact-name search (no glob patterns). Stops early when found.
        Used as a fallback when the index budget didn't include a folder yet.
        """
        target = self._normalize_text(filename)
        if not target:
            return None
        roots = self.output_bucket_roots(out)
        dirs_scanned = 0
        for root in roots:
            stack: list[str] = [str(root)]
            while stack and dirs_scanned < int(max_dirs):
                cur = stack.pop()
                dirs_scanned += 1
                try:
                    with os.scandir(cur) as it:
                        for ent in it:
                            try:
                                if ent.is_dir(follow_symlinks=False):
                                    stack.append(ent.path)
                                    continue
                                if ent.is_file(follow_symlinks=False) and ent.name == target:
                                    return Path(ent.path)
                            except Exception:
                                continue
                except Exception:
                    continue
        return None

    def track_saved_output_file(self, state: dict[str, Any], filename: str) -> None:
        display = self._display_image_name_from_output_file(filename)
        if not display:
            return
        current = state.get("saved_output_files", []) or []
        if display in current:
            return
        current = [display, *current]
        state["saved_output_files"] = current[:400]

        # Incremental index update (best effort).
        path = self._normalize_text(state.get("download_path", ""))
        if not path:
            return
        out = Path(path).expanduser()
        if not out.exists() or not out.is_dir():
            return
        candidate = out / self._normalize_text(filename)
        if candidate.exists() and candidate.is_file():
            self.index_note_new_file(state, out, candidate)

    def resolve_output_files_for_product(self, state: dict[str, Any], product_name: str) -> tuple[Optional[Path], Optional[Path]]:
        path = self._normalize_text(state.get("download_path", ""))
        if not path:
            return None, None
        out = Path(path).expanduser()
        if not out.exists() or not out.is_dir():
            return None, None

        base = self._normalize_text(product_name)
        if not base:
            return None, None

        image_candidates = [out / f"{base}.png", out / f"{base}.jpg", out / f"{base}.jpeg"]
        meta_candidate = out / f"{base}.meta.json"

        image_path = next((p for p in image_candidates if p.exists() and p.is_file()), None)
        meta_path = meta_candidate if meta_candidate.exists() and meta_candidate.is_file() else None

        if image_path is None or meta_path is None:
            state_obj = self.ensure_output_file_index(state, out, force=False)
            index = state_obj.get("index") if isinstance(state_obj, dict) else None
            entry = index.get(base) if isinstance(index, dict) else None
            if isinstance(entry, dict):
                if image_path is None and isinstance(entry.get("image"), tuple) and len(entry["image"]) >= 3:
                    try:
                        image_path = Path(str(entry["image"][2]))
                    except Exception:
                        image_path = None
                if meta_path is None and isinstance(entry.get("meta"), tuple) and len(entry["meta"]) >= 2:
                    try:
                        meta_path = Path(str(entry["meta"][1]))
                    except Exception:
                        meta_path = None

        # Final fallback: exact-name directory walk (no rglob).
        if image_path is None:
            for ext in ("png", "jpg", "jpeg"):
                found = self.find_file_by_exact_name(out, f"{base}.{ext}")
                if found is not None:
                    image_path = found
                    self.index_note_new_file(state, out, found)
                    break
        if meta_path is None:
            found = self.find_file_by_exact_name(out, f"{base}.meta.json")
            if found is not None:
                meta_path = found
                self.index_note_new_file(state, out, found)
        return image_path, meta_path
