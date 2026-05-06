#!/usr/bin/env python3
import argparse
from pathlib import Path

from PIL import Image
import piexif


def parse_args():
    ap = argparse.ArgumentParser(
        description="Convert PNG to JPG and write standard EXIF tags for Metashape"
    )
    ap.add_argument("input_png", help="Path to input PNG")
    ap.add_argument(
        "-o",
        "--output",
        help="Path to output JPG. If omitted, creates *_fixed.jpg next to input file",
    )
    ap.add_argument(
        "--focal-length",
        type=float,
        default=34.0,
        help="Focal length in mm, default: 34.0",
    )
    ap.add_argument(
        "--fp-xres",
        type=float,
        default=1351.3513513513512,
        help="FocalPlaneXResolution, default: 1351.3513513513512",
    )
    ap.add_argument(
        "--fp-yres",
        type=float,
        default=1351.3513513513512,
        help="FocalPlaneYResolution, default: 1351.3513513513512",
    )
    ap.add_argument(
        "--fp-unit",
        type=int,
        default=3,
        help="FocalPlaneResolutionUnit EXIF code, default: 3 (cm)",
    )
    ap.add_argument(
        "--quality",
        type=int,
        default=95,
        help="JPEG quality, default: 95",
    )
    return ap.parse_args()


def to_rational(value, scale=1000000):
    num = int(round(value * scale))
    den = scale
    return (num, den)


def main():
    args = parse_args()

    input_path = Path(args.input_png).expanduser()
    if not input_path.exists():
        raise SystemExit(f"File not found: {input_path}")

    if args.output:
        output_path = Path(args.output).expanduser()
    else:
        output_path = input_path.with_name(input_path.stem + "_fixed.jpg")

    with Image.open(input_path) as img:
        img = img.convert("RGB")

        exif_dict = {
            "0th": {},
            "Exif": {
                piexif.ExifIFD.FocalLength: to_rational(args.focal_length),
                piexif.ExifIFD.FocalPlaneXResolution: to_rational(args.fp_xres),
                piexif.ExifIFD.FocalPlaneYResolution: to_rational(args.fp_yres),
                piexif.ExifIFD.FocalPlaneResolutionUnit: args.fp_unit,
            },
            "GPS": {},
            "1st": {},
            "thumbnail": None,
        }

        exif_bytes = piexif.dump(exif_dict)
        img.save(output_path, "jpeg", quality=args.quality, exif=exif_bytes)

    print(f"Input : {input_path}")
    print(f"Output: {output_path}")
    print("EXIF written:")
    print(f"  FocalLength              = {args.focal_length} mm")
    print(f"  FocalPlaneXResolution    = {args.fp_xres}")
    print(f"  FocalPlaneYResolution    = {args.fp_yres}")
    print(f"  FocalPlaneResolutionUnit = {args.fp_unit}")


if __name__ == "__main__":
    main()

