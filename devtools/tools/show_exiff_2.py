#!/usr/bin/env python3
import argparse
from pathlib import Path

from PIL import Image, ExifTags

try:
    import piexif
except ImportError:
    piexif = None


def print_pillow_exif(im):
    raw = im.getexif()
    if not raw:
        print("\n[Pillow EXIF] none")
        return

    print(f"\n[Pillow EXIF] tag count: {len(raw)}")
    print("-" * 80)

    for tag_id, value in raw.items():
        tag_name = ExifTags.TAGS.get(tag_id, f"Tag_{tag_id}")
        print(f"Tag ID   : {tag_id}")
        print(f"Tag Name : {tag_name}")
        print(f"Py Type  : {type(value)}")
        print(f"repr()   : {repr(value)}")
        print("-" * 80)


def print_piexif_ifd(ifd_name, ifd_dict, tag_map):
    if not ifd_dict:
        print(f"\n[piexif {ifd_name}] none")
        return

    print(f"\n[piexif {ifd_name}] tag count: {len(ifd_dict)}")
    print("-" * 80)

    for tag_id, value in ifd_dict.items():
        tag_info = tag_map.get(tag_id)
        tag_name = tag_info["name"] if tag_info else f"Tag_{tag_id}"
        print(f"Tag ID   : {tag_id}")
        print(f"Tag Name : {tag_name}")
        print(f"Py Type  : {type(value)}")
        print(f"repr()   : {repr(value)}")
        print("-" * 80)


def print_piexif_exif(path):
    if piexif is None:
        print("\n[piexif] non disponibile. Installa con: pip install piexif")
        return

    try:
        exif_dict = piexif.load(str(path))
    except Exception as e:
        print(f"\n[piexif] errore nel leggere EXIF: {e}")
        return

    print_piexif_ifd("0th", exif_dict.get("0th", {}), piexif.TAGS["0th"])
    print_piexif_ifd("Exif", exif_dict.get("Exif", {}), piexif.TAGS["Exif"])
    print_piexif_ifd("GPS", exif_dict.get("GPS", {}), piexif.TAGS["GPS"])
    print_piexif_ifd("1st", exif_dict.get("1st", {}), piexif.TAGS["1st"])

    thumb = exif_dict.get("thumbnail")
    print("\n[piexif thumbnail]")
    print(repr(thumb if thumb is not None else None))


def main():
    ap = argparse.ArgumentParser(description="Dump EXIF details with Pillow and piexif")
    ap.add_argument("image", help="Path to image file")
    args = ap.parse_args()

    p = Path(args.image).expanduser()
    if not p.exists():
        raise SystemExit(f"File not found: {p}")

    with Image.open(p) as im:
        print(f"File: {p}")
        print(f"Format: {im.format}  Size: {im.size}  Mode: {im.mode}")
        print_pillow_exif(im)

    print_piexif_exif(p)


if __name__ == "__main__":
    main()

