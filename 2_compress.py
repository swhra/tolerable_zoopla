#!/usr/bin/env python3

import argparse
import csv
import json
import os
import re
import struct
import sys
from dataclasses import dataclass
from typing import Any, Dict, List

MAGIC = b"PIF1"
VERSION = 1

HEADER = struct.Struct("<4sBBHiiii")
RECORD = struct.Struct("<IHHHBHB")

RECORD_SIZE = RECORD.size
HEADER_SIZE = HEADER.size

MAX_U16 = 65535

@dataclass
class Bounds:
    min_lat: float
    max_lat: float
    min_lng: float
    max_lng: float

def quantise(value: float, minimum: float, maximum: float) -> int:
    if maximum <= minimum:
        return 0
    ratio = (value - minimum) / (maximum - minimum)
    ratio = max(0.0, min(1.0, ratio))
    return int(round(ratio * MAX_U16))

def dequantise(value: int, minimum: float, maximum: float) -> float:
    if maximum <= minimum:
        return minimum
    return minimum + (value / MAX_U16) * (maximum - minimum)

def to_microdegrees(value: float) -> int:
    return int(round(value * 1_000_000))

def from_microdegrees(value: int) -> float:
    return value / 1_000_000

def write_header(file, bounds: Bounds):
    file.write(HEADER.pack(
        MAGIC, VERSION, 0, 0,
        to_microdegrees(bounds.min_lat),
        to_microdegrees(bounds.max_lat),
        to_microdegrees(bounds.min_lng),
        to_microdegrees(bounds.max_lng)
    ))

def read_header(data: bytes) -> Bounds:
    magic, version, flags, _, min_lat, max_lat, min_lng, max_lng = HEADER.unpack_from(data, 0)
    if magic != MAGIC:
        raise ValueError("Invalid PIF file")
    return Bounds(
        from_microdegrees(min_lat), from_microdegrees(max_lat),
        from_microdegrees(min_lng), from_microdegrees(max_lng)
    )

def pack_record(row: Dict[str, Any], bounds: Bounds) -> bytes:
    lat_value = quantise(row.get("lat", 0), bounds.min_lat, bounds.max_lat)
    lng_value = quantise(row.get("lng", 0), bounds.min_lng, bounds.max_lng)
    price_value = min(int(row.get("price", 0)) // 5, MAX_U16)
    beds = min(int(row.get("beds", 0)), 15)
    baths = min(int(row.get("baths", 0)), 15)
    beds_baths = (beds << 4) | baths
    area = min(int(row.get("sqft") or 0), MAX_U16)
    
    meta = 0
    meta |= (int(row.get("flags", 0)) & 0x0F)
    meta |= (int(row.get("furnished", 0)) & 0x03) << 4
    meta |= (int(row.get("type", 0)) & 0x03) << 6

    return RECORD.pack(int(row.get("id", 0)), lat_value, lng_value, price_value, beds_baths, area, meta)

def unpack_record(data: bytes, bounds: Bounds) -> Dict[str, Any]:
    listing_id, lat_val, lng_val, price_val, beds_baths, area, meta = RECORD.unpack(data)
    return {
        "id": listing_id,
        "lat": dequantise(lat_val, bounds.min_lat, bounds.max_lat),
        "lng": dequantise(lng_val, bounds.min_lng, bounds.max_lng),
        "price": price_val * 5,
        "beds": (beds_baths >> 4) & 0x0F,
        "baths": beds_baths & 0x0F,
        "sqft": area,
        "flags": meta & 0x0F,
        "furnished": (meta >> 4) & 0x03,
        "type": (meta >> 6) & 0x03
    }

def encode_command(args):
    bounds = Bounds(args.min_lat, args.max_lat, args.min_lng, args.max_lng)

    with open(args.json, "r", encoding="utf-8") as f:
        content = f.read().strip()

    if content.startswith("["):
        rows = json.loads(content)
    else:
        rows = [json.loads(line) for line in content.splitlines() if line.strip()]

    # Open file if requested, otherwise use stdout binary buffer
    out = open(args.pif, "wb") if args.pif else sys.stdout.buffer

    try:
        write_header(out, bounds)
        for row in rows:
            if "pos" in row:
                price_str = row.get("price") or ""
                price_match = re.search(r'£([\d,]+)', price_str)
                price = int(price_match.group(1).replace(',', '')) if price_match else 0
                
                beds = baths = furnished = 0
                for f in (row.get("features") or []):
                    icon = f.get("iconId")
                    if icon == "bed": beds = f.get("content", 0)
                    elif icon == "bath": baths = f.get("content", 0)
                    elif icon == "chair": furnished = 1

                ptype = (row.get("propertyType") or "").lower()
                prop_type = 1 if ptype in ("flat", "studio", "maisonette") else (2 if "house" in ptype else 0)

                mapped = {
                    "id": int(row.get("listingId") or 0),
                    "lat": row["pos"].get("lat", 0),
                    "lng": row["pos"].get("lng", 0),
                    "price": price, "beds": beds, "baths": baths,
                    "sqft": row.get("sizeSqft") or 0, "flags": 0,
                    "furnished": furnished, "type": prop_type
                }
                out.write(pack_record(mapped, bounds))
            else:
                out.write(pack_record(row, bounds))
    finally:
        if args.file:
            out.close()
            # Only print status if we aren't polluting stdout with binary data
            print(f"Wrote {args.pif} ({os.path.getsize(args.pif)} bytes)", file=sys.stderr)

def decode_command(args):
    data = open(args.file, "rb").read()
    bounds = read_header(data)
    offset, rows = HEADER_SIZE, []

    while offset + RECORD_SIZE <= len(data):
        rows.append(unpack_record(data[offset:offset + RECORD_SIZE], bounds))
        offset += RECORD_SIZE

    # Default to stdout for CSV if no path provided
    out_f = open(args.csv, "w", newline="", encoding="utf-8") if args.csv else sys.stdout
    try:
        if rows:
            writer = csv.DictWriter(out_f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    finally:
        if args.csv: out_f.close()

def main():
    parser = argparse.ArgumentParser(prog="compress")
    sub = parser.add_subparsers(dest="cmd", required=True)

    enc = sub.add_parser("encode")
    enc.add_argument("json")
    enc.add_argument("--pif", help="Output file path (default: stdout)")
    enc.add_argument("--min-lat", type=float, default=51.44)
    enc.add_argument("--max-lat", type=float, default=51.62)
    enc.add_argument("--min-lng", type=float, default=-0.283)
    enc.add_argument("--max-lng", type=float, default=0.019)
    enc.set_defaults(func=encode_command)

    dec = sub.add_parser("decode")
    dec.add_argument("pif")
    dec.add_argument("--csv", help="Output file path (default: stdout)")
    dec.set_defaults(func=decode_command)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()