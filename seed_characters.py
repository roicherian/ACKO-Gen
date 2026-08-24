#!/usr/bin/env python3
"""
One-off script: seeds the character reference library with the 24 real
reference photos provided, replacing the old fictional placeholder library.

Run once, manually, from the project root, against whichever DATA_DIR the
target acko_gen.db lives in (matches how that DB is normally created):

    python3 seed_characters.py /path/to/24/source/images

Not part of the request-handling code path — safe to leave in the repo as a
documented one-off, or delete after running.
"""
import sys
import os
from io import BytesIO

from PIL import Image

import character_store

# (source filename, character name, age bracket) — filename order matches the
# chronological order the 24 source images were generated in; name mapping was
# visually confirmed against a contact sheet (gender/age/regional fit), no
# stated location/role provided, so those fields are left blank rather than
# invented.
SEED = [
    ("magnific_cinematic-photorealistic-_rgwKAWLxtc.png", "Karthik Srinivasan", "20-30"),
    ("magnific_photorealistic-reference-_gO4LcXASXO.png", "Rahul Verma", "20-30"),
    ("magnific_photorealistic-reference-_huHIU2AvqL.png", "Vikram Chatterjee", "30-40"),
    ("magnific_cinematic-photorealistic-_YMeGuPOWeC.png", "Riya Sen", "20-30"),
    ("magnific_photorealistic-reference-_0eBYHANTfW.png", "Sneha Reddy", "30-40"),
    ("magnific_photorealistic-reference-_MBI050CDCm.png", "Anjali Deshmukh", "30-40"),
    ("magnific_photorealistic-reference-_p8mV1I4ehw.png", "Naveen Kumar", "20-30"),
    ("magnific_cinematic-photorealistic-_s7yxWSdl8e.png", "Abhishek Mishra", "20-30"),
    ("magnific_photorealistic-reference-_lJPjcNigv9.png", "Gurpreet Singh", "40-50"),
    ("magnific_cinematic-photorealistic-_9ZGyoVRNYZ.png", "Tanvi Mehta", "20-30"),
    ("magnific_photorealistic-reference-_dtvDxkJXSL.png", "Meenakshi Iyer", "40-50"),
    ("magnific_photorealistic-reference-_WDdzFHocXe.png", "Priya Mukherjee", "30-40"),
    ("magnific_cinematic-photorealistic-_ksSb2Wm16B.png", "Vijay Patil", "50-60"),
    ("magnific_photorealistic-reference-_rgwKGMfxtc.png", "K. Venkatesh", "40-50"),
    ("magnific_photorealistic-reference-_bxsF3VT5Y2.png", "Professor Ramachandran", "50-60"),
    ("magnific_cinematic-photorealistic-_Sy9sTfIUb8.png", "Shruti Hegde", "40-50"),
    ("magnific_photorealistic-reference-_JN3UpLzOq4.png", "Deepa Nair", "40-50"),
    ("magnific_cinematic-photorealistic-_eIhMreadqL.png", "Hari Prasad", "50-60"),
    ("magnific_photorealistic-reference-_WDdzFA7cXe.png", "Sunita Sharma", "50-60"),
    ("magnific_photorealistic-reference-_ksSbAS416B.png", "Sanjay Joshi", "50-60"),
    ("magnific_photorealistic-reference-_ksSbALJ16B.png", "Rajesh Pillai", "50-60"),
    ("magnific_cinematic-photorealistic-_tCQoUbdmZJ.png", "Lakshmi Devi", "50-60"),
    ("magnific_photorealistic-reference-_UPNlM07wny.png", "Radha Krishnan", "50-60"),
    ("magnific_photorealistic-reference-_rgwKzNExtc.png", "Saraswathi Amma", "50-60"),
]

TARGET_BYTES = 350 * 1024  # same reference-image budget the client-side path enforces
MAX_EDGE = 1400


def compress_to_jpeg(path, target_bytes=TARGET_BYTES, max_edge=MAX_EDGE):
    img = Image.open(path).convert("RGB")
    if max(img.size) > max_edge:
        ratio = max_edge / max(img.size)
        img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
    for quality in (85, 75, 65, 55, 45):
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        if buf.tell() <= target_bytes:
            return buf.getvalue()
    return buf.getvalue()  # smallest attempted, even if still over budget


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 seed_characters.py /path/to/24/source/images")
        sys.exit(1)
    src_dir = sys.argv[1]

    character_store.init_db()

    existing = {c["name"] for c in character_store.list_characters()}
    created, skipped = 0, 0
    for filename, name, age in SEED:
        if name in existing:
            print(f"skip (already exists): {name}")
            skipped += 1
            continue
        path = os.path.join(src_dir, filename)
        if not os.path.isfile(path):
            print(f"MISSING source file, skipping: {path}")
            continue
        raw = compress_to_jpeg(path)
        rec = character_store.create_character(
            name, raw, "image/jpeg", role="", location="", age=age, created_by="system:seed",
        )
        print(f"created {rec['id']}: {rec['name']} ({len(raw)//1024}KB, age {age})")
        created += 1

    print(f"\nDone. {created} created, {skipped} already present.")


if __name__ == "__main__":
    main()
