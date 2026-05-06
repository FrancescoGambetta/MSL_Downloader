#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np


BAYER_PATTERNS = ("RGGB", "BGGR", "GRBG", "GBRG")
DEBAYER_PROFILES = ("auto", "ea", "std", "bggr_ea_hard", "superpixel", "superpixel_mean")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "mastcam_bayer_config.json"


@dataclass
class MastcamConfig:
    best_pattern: str = "BGGR"
    final_sigma: float = 0.16
    wb_strength: float = 0.10
    flat_threshold: float = 6.0
    chroma_sigma: float = 1.8
    chroma_blend: float = 0.94
    color_replace_sigma: float = 6.0
    green_neutralize: float = 0.45
    clahe_clip: float = 1.0
    clahe_grid: tuple[int, int] = (8, 8)
    gamma: float = 1.0
    debayer_profile: str = "ea"
    superpixel_upscale: bool = True


class MastcamBayerPipeline:
    def __init__(self, cfg: MastcamConfig):
        self.cfg = cfg

    def load_raw_as_gray(self, path: Path) -> np.ndarray:
        arr = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if arr is None:
            raise ValueError(f"Impossibile leggere: {path}")
        if arr.ndim == 3:
            arr = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
        if arr.dtype != np.uint8:
            a = arr.astype(np.float32)
            mn, mx = float(a.min()), float(a.max())
            arr = np.zeros_like(a, dtype=np.uint8) if mx <= mn else ((a - mn) / (mx - mn) * 255.0).astype(np.uint8)
        return arr

    def _ea_code(self, pattern: str) -> int | None:
        m = {
            "RGGB": getattr(cv2, "COLOR_BayerRG2RGB_EA", None),
            "BGGR": getattr(cv2, "COLOR_BayerBG2RGB_EA", None),
            "GRBG": getattr(cv2, "COLOR_BayerGR2RGB_EA", None),
            "GBRG": getattr(cv2, "COLOR_BayerGB2RGB_EA", None),
        }
        return m.get(pattern)

    def _std_code(self, pattern: str) -> int:
        m = {
            "RGGB": cv2.COLOR_BayerRG2RGB,
            "BGGR": cv2.COLOR_BayerBG2RGB,
            "GRBG": cv2.COLOR_BayerGR2RGB,
            "GBRG": cv2.COLOR_BayerGB2RGB,
        }
        return m[pattern]

    def _debayer_superpixel(self, raw: np.ndarray, pattern: str) -> np.ndarray:
        h, w = raw.shape
        h2, w2 = h - (h % 2), w - (w % 2)
        x00 = raw[0:h2:2, 0:w2:2].astype(np.float32)
        x01 = raw[0:h2:2, 1:w2:2].astype(np.float32)
        x10 = raw[1:h2:2, 0:w2:2].astype(np.float32)
        x11 = raw[1:h2:2, 1:w2:2].astype(np.float32)

        if pattern == "BGGR":
            b = x00
            g = 0.5 * (x01 + x10)
            r = x11
        elif pattern == "RGGB":
            r = x00
            g = 0.5 * (x01 + x10)
            b = x11
        elif pattern == "GRBG":
            g = 0.5 * (x00 + x11)
            r = x01
            b = x10
        elif pattern == "GBRG":
            g = 0.5 * (x00 + x11)
            b = x01
            r = x10
        else:
            raise ValueError(f"Pattern non supportato: {pattern}")

        out = np.clip(np.dstack([r, g, b]), 0, 255).astype(np.uint8)
        if self.cfg.superpixel_upscale:
            return cv2.resize(out, (w, h), interpolation=cv2.INTER_LANCZOS4)
        return out

    def debayer(self, raw_gray: np.ndarray, pattern: str) -> np.ndarray:
        profile = self.cfg.debayer_profile

        if profile in {"superpixel", "superpixel_mean"}:
            return self._debayer_superpixel(raw_gray, pattern)

        if profile == "bggr_ea_hard":
            code = self._ea_code("BGGR")
            if code is None:
                code = self._std_code("BGGR")
            return cv2.cvtColor(raw_gray, code)

        if profile == "std":
            return cv2.cvtColor(raw_gray, self._std_code(pattern))

        if profile == "ea":
            code = self._ea_code(pattern)
            if code is None:
                code = self._std_code(pattern)
            return cv2.cvtColor(raw_gray, code)

        # auto
        code = self._ea_code(pattern)
        if code is None:
            code = self._std_code(pattern)
        return cv2.cvtColor(raw_gray, code)

    def partial_white_balance(self, rgb: np.ndarray) -> np.ndarray:
        s = self.cfg.wb_strength
        rgb_f = rgb.astype(np.float32) + 1e-6
        means = rgb_f.reshape(-1, 3).mean(axis=0)
        target = float(means.mean())
        gains = target / means
        gains = 1.0 + s * (gains - 1.0)
        return np.clip(rgb_f * gains, 0.0, 255.0).astype(np.uint8)

    def chroma_grid_reduction(self, rgb: np.ndarray) -> np.ndarray:
        ycc = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
        y, cr, cb = cv2.split(ycc)

        y_blur = cv2.GaussianBlur(y, (0, 0), 1.2)
        hf = cv2.absdiff(y, y_blur)
        flat = (hf < self.cfg.flat_threshold).astype(np.float32)
        flat = cv2.GaussianBlur(flat, (0, 0), 1.0)

        cr_lp = cv2.GaussianBlur(cr, (0, 0), self.cfg.chroma_sigma)
        cb_lp = cv2.GaussianBlur(cb, (0, 0), self.cfg.chroma_sigma)
        cr2 = cv2.addWeighted(cr, 1.0 - self.cfg.chroma_blend, cr_lp, self.cfg.chroma_blend, 0)
        cb2 = cv2.addWeighted(cb, 1.0 - self.cfg.chroma_blend, cb_lp, self.cfg.chroma_blend, 0)

        cr3 = np.clip(cr.astype(np.float32) * (1.0 - flat) + cr2.astype(np.float32) * flat, 0, 255).astype(np.uint8)
        cb3 = np.clip(cb.astype(np.float32) * (1.0 - flat) + cb2.astype(np.float32) * flat, 0, 255).astype(np.uint8)

        if self.cfg.color_replace_sigma > 0:
            cr_wide = cv2.GaussianBlur(cr3, (0, 0), self.cfg.color_replace_sigma)
            cb_wide = cv2.GaussianBlur(cb3, (0, 0), self.cfg.color_replace_sigma)
            cr3 = np.clip(cr3.astype(np.float32) * (1.0 - flat) + cr_wide.astype(np.float32) * flat, 0, 255).astype(np.uint8)
            cb3 = np.clip(cb3.astype(np.float32) * (1.0 - flat) + cb_wide.astype(np.float32) * flat, 0, 255).astype(np.uint8)

        rgb2 = cv2.cvtColor(cv2.merge([y, cr3, cb3]), cv2.COLOR_YCrCb2RGB)
        if self.cfg.green_neutralize <= 0:
            return rgb2

        lab = cv2.cvtColor(rgb2, cv2.COLOR_RGB2LAB)
        l, a, b = cv2.split(lab)
        a_f = a.astype(np.float32)
        a_fix = a_f + self.cfg.green_neutralize * flat * (128.0 - a_f)
        a_fix = np.clip(a_fix, 0, 255).astype(np.uint8)
        return cv2.cvtColor(cv2.merge([l, a_fix, b]), cv2.COLOR_LAB2RGB)

    def micro_contrast(self, rgb: np.ndarray) -> np.ndarray:
        l, a, b = cv2.split(cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB))
        l = cv2.createCLAHE(clipLimit=self.cfg.clahe_clip, tileGridSize=self.cfg.clahe_grid).apply(l)
        return cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2RGB)

    def gamma_correct(self, rgb: np.ndarray) -> np.ndarray:
        f = np.clip(rgb.astype(np.float32) / 255.0, 0.0, 1.0)
        f = np.power(f, max(1e-3, self.cfg.gamma))
        return np.clip(f * 255.0, 0.0, 255.0).astype(np.uint8)

    def process(self, raw_gray: np.ndarray) -> np.ndarray:
        raw_f = cv2.GaussianBlur(raw_gray, (0, 0), self.cfg.final_sigma) if self.cfg.final_sigma > 0 else raw_gray.copy()
        rgb = self.debayer(raw_f, self.cfg.best_pattern)
        rgb = self.partial_white_balance(rgb)
        rgb = self.chroma_grid_reduction(rgb)
        rgb = self.micro_contrast(rgb)
        return self.gamma_correct(rgb)

    def pattern_grid(self, raw_gray: np.ndarray, out_path: Path) -> None:
        patterns = list(BAYER_PATTERNS)
        tiles = []
        for p in patterns:
            rgb = self.debayer(raw_gray, p)
            label = p
            tile = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            cv2.putText(tile, label, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2, cv2.LINE_AA)
            tiles.append(tile)
        top = np.hstack([tiles[0], tiles[1]])
        bot = np.hstack([tiles[2], tiles[3]])
        grid = np.vstack([top, bot])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out_path), grid)

    def sigma_grid(self, raw_gray: np.ndarray, sigmas: Iterable[float], out_path: Path) -> None:
        tiles = []
        for s in sigmas:
            raw_s = cv2.GaussianBlur(raw_gray, (0, 0), s) if s > 0 else raw_gray.copy()
            rgb = self.debayer(raw_s, self.cfg.best_pattern)
            tile = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            cv2.putText(tile, f"sigma={s:.2f}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
            tiles.append(tile)

        while len(tiles) < 4:
            tiles.append(tiles[-1].copy())
        top = np.hstack([tiles[0], tiles[1]])
        bot = np.hstack([tiles[2], tiles[3]])
        grid = np.vstack([top, bot])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out_path), grid)


def parse_grid(value: str) -> tuple[int, int]:
    value = value.lower().replace("x", ",")
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("Usa formato WxH, es: 8x8")
    try:
        w, h = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("CLAHE grid deve essere interi, es: 8x8") from exc
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError("CLAHE grid deve essere > 0")
    return (w, h)


def parse_sigmas(value: str) -> list[float]:
    out = []
    for p in value.split(","):
        p = p.strip()
        if not p:
            continue
        out.append(float(p))
    if not out:
        raise argparse.ArgumentTypeError("Lista sigma vuota")
    return out


def load_json(path: Path, default: dict[str, object]) -> dict[str, object]:
    if not path.exists():
        return dict(default)
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(default)
    return parsed if isinstance(parsed, dict) else dict(default)


def _as_grid(value: object, default: tuple[int, int]) -> tuple[int, int]:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            a = int(value[0])
            b = int(value[1])
            if a > 0 and b > 0:
                return (a, b)
        except Exception:
            return default
    return default


def resolve_config(raw_cfg: dict[str, object], args: argparse.Namespace) -> MastcamConfig:
    base = MastcamConfig()

    def pick(name: str, cli_value: object) -> object:
        if cli_value is not None:
            return cli_value
        if name in raw_cfg:
            return raw_cfg[name]
        return getattr(base, name)

    best_pattern = str(pick("best_pattern", args.best_pattern)).upper()
    if best_pattern not in BAYER_PATTERNS:
        raise ValueError(f"best_pattern non valido: {best_pattern} (attesi: {BAYER_PATTERNS})")

    debayer_profile = str(pick("debayer_profile", args.debayer_profile)).lower()
    if debayer_profile not in DEBAYER_PROFILES:
        raise ValueError(f"debayer_profile non valido: {debayer_profile} (attesi: {DEBAYER_PROFILES})")

    return MastcamConfig(
        best_pattern=best_pattern,
        final_sigma=float(pick("final_sigma", args.final_sigma)),
        wb_strength=float(pick("wb_strength", args.wb_strength)),
        flat_threshold=float(pick("flat_threshold", args.flat_threshold)),
        chroma_sigma=float(pick("chroma_sigma", args.chroma_sigma)),
        chroma_blend=float(pick("chroma_blend", args.chroma_blend)),
        color_replace_sigma=float(pick("color_replace_sigma", args.color_replace_sigma)),
        green_neutralize=float(pick("green_neutralize", args.green_neutralize)),
        clahe_clip=float(pick("clahe_clip", args.clahe_clip)),
        clahe_grid=_as_grid(pick("clahe_grid", args.clahe_grid), base.clahe_grid),
        gamma=float(pick("gamma", args.gamma)),
        debayer_profile=debayer_profile,
        superpixel_upscale=bool(pick("superpixel_upscale", args.superpixel_upscale)),
    )


def build_parser() -> argparse.ArgumentParser:
    epilog = """
ESEMPI RAPIDI
  1) Output finale (pipeline step-by-step):
     python mastcam_bayer_cli.py --input "in.jpg" --output "out.png"

  2) Usa profilo debayer edge-aware forzato:
     python mastcam_bayer_cli.py --input in.jpg --output out.png --debayer-profile ea --best-pattern RGGB

  3) Profilo robusto contro checkerboard (Bayer in JPEG):
     python mastcam_bayer_cli.py --input in.jpg --output out.png --debayer-profile superpixel

  4) Superpixel "onesto" senza riallargare:
     python mastcam_bayer_cli.py --input in.jpg --output out.png --debayer-profile superpixel_mean --no-superpixel-upscale

  5) Crea griglia confronto pattern e sigma:
     python mastcam_bayer_cli.py --input in.jpg --output out.png --dump-pattern-grid patterns.jpg --dump-sigma-grid sigmas.jpg --sigmas 0,0.4,0.6,0.9

  6) Sostituzione colore nelle zone piatte + neutralizzazione verde:
     python mastcam_bayer_cli.py --input in.jpg --output out.png --color-replace-sigma 6 --green-neutralize 0.45

GUIDA TUNING
  - Meno griglia verde nel cielo:
    aumenta --chroma-blend (0.82 -> 0.88) e/o --flat-threshold (4.0 -> 4.6)
  - Foschia verde nella valle:
    prova --color-replace-sigma 4..8 e --green-neutralize 0.25..0.55
  - Piu dettaglio (meno effetto morbido):
    riduci --final-sigma (0.25 -> 0.15) e/o --chroma-sigma (0.9 -> 0.7)
  - Colori troppo strani:
    riduci --wb-strength (0.18 -> 0.10)
  - Contrasto locale:
    aumenta --clahe-clip (1.2 -> 1.6), ma evita valori troppo alti

PROFILI DEBAYER
  - auto: usa EA se disponibile, altrimenti standard
  - ea: edge-aware sul pattern scelto
  - std: OpenCV standard
  - bggr_ea_hard: replica la scelta hardcoded BGGR_EA dello step-by-step
  - superpixel: 2x2 robusto per Bayer compresso, meno artefatti ma meno risoluzione reale
  - superpixel_mean: stessa idea del superpixel, esplicita che R/B vengono presi dal 2x2 e G e' la media dei due verdi
""".strip("\n")

    p = argparse.ArgumentParser(
        description="Pipeline classe/CLI per Mastcam Bayer-in-JPEG (basata sul notebook step-by-step)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )

    p.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path config JSON con i default del processing.")
    p.add_argument("--input", required=True, help="Path file input oppure cartella input (JPEG/PNG/TIFF/BMP).")
    p.add_argument("--output", required=True, help="Path output file (se input file) oppure cartella output (se input cartella).")

    p.add_argument("--best-pattern", default=None, choices=BAYER_PATTERNS, help="Pattern Bayer da usare (override config).")
    p.add_argument("--final-sigma", type=float, default=None, help="Gaussian pre-debayer (override config).")
    p.add_argument("--wb-strength", type=float, default=None, help="White balance parziale (override config).")
    p.add_argument("--flat-threshold", type=float, default=None, help="Soglia aree piatte per pulizia croma (override config).")
    p.add_argument("--chroma-sigma", type=float, default=None, help="Blur croma (override config).")
    p.add_argument("--chroma-blend", type=float, default=None, help="Blend croma originale/filtrato (override config).")
    p.add_argument("--color-replace-sigma", type=float, default=None, help="Blur largo per sostituzione colore (override config).")
    p.add_argument("--green-neutralize", type=float, default=None, help="Neutralizzazione verde LAB (override config).")
    p.add_argument("--clahe-clip", type=float, default=None, help="CLAHE clip limit su L (override config).")
    p.add_argument("--clahe-grid", type=parse_grid, default=None, help="CLAHE tile grid WxH (override config).")
    p.add_argument("--gamma", type=float, default=None, help="Gamma finale (override config).")

    p.add_argument("--debayer-profile", default=None, choices=DEBAYER_PROFILES, help="Profilo debayer (override config).")
    sup = p.add_mutually_exclusive_group()
    sup.add_argument("--superpixel-upscale", dest="superpixel_upscale", action="store_true", help="Forza upscale output superpixel.")
    sup.add_argument("--no-superpixel-upscale", dest="superpixel_upscale", action="store_false", help="Disattiva upscale output superpixel.")
    p.set_defaults(superpixel_upscale=None)

    p.add_argument("--dump-pattern-grid", default="", help="Opzionale: salva confronto 4 pattern.")
    p.add_argument("--dump-sigma-grid", default="", help="Opzionale: salva confronto sigma sul pattern scelto.")
    p.add_argument("--sigmas", type=parse_sigmas, default=[0.0, 0.4, 0.6, 0.9], help="Lista sigma csv per dump-sigma-grid.")

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    cfg_path = Path(args.config).expanduser().resolve()
    raw_cfg = load_json(cfg_path, {})

    cfg = resolve_config(raw_cfg, args)

    pipe = MastcamBayerPipeline(cfg)
    in_path = Path(args.input).expanduser().resolve()
    out_path = Path(args.output).expanduser().resolve()

    if in_path.is_file():
        raw = pipe.load_raw_as_gray(in_path)
        rgb_out = pipe.process(raw)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out_path), cv2.cvtColor(rgb_out, cv2.COLOR_RGB2BGR))

        if args.dump_pattern_grid:
            pipe.pattern_grid(raw, Path(args.dump_pattern_grid).expanduser().resolve())
        if args.dump_sigma_grid:
            pipe.sigma_grid(raw, args.sigmas, Path(args.dump_sigma_grid).expanduser().resolve())

        print("Input:", in_path)
        print("Output:", out_path)
        print("Config:", cfg_path)
        print("Pattern:", cfg.best_pattern, "| Debayer profile:", cfg.debayer_profile)
        return 0

    if in_path.is_dir():
        if out_path.exists() and out_path.is_file():
            raise ValueError(f"--output deve essere una cartella quando --input e' una cartella: {out_path}")
        out_path.mkdir(parents=True, exist_ok=True)

        files = sorted([p for p in in_path.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS])
        if not files:
            raise ValueError(f"Nessuna immagine trovata in: {in_path}")

        done = 0
        for src in files:
            raw = pipe.load_raw_as_gray(src)
            rgb_out = pipe.process(raw)
            dst = out_path / f"{src.stem}_processed.png"
            cv2.imwrite(str(dst), cv2.cvtColor(rgb_out, cv2.COLOR_RGB2BGR))
            done += 1
            print(f"[{done}/{len(files)}] {src.name} -> {dst.name}")

        print("Input directory:", in_path)
        print("Output directory:", out_path)
        print("Config:", cfg_path)
        print("Files processed:", done)
        print("Pattern:", cfg.best_pattern, "| Debayer profile:", cfg.debayer_profile)
        return 0

    raise ValueError(f"Input non trovato: {in_path}")


if __name__ == "__main__":
    raise SystemExit(main())
