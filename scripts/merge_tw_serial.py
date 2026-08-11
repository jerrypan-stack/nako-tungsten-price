#!/usr/bin/env python3
"""Serial re-fetch of priority TW pages; merge in-stock ≤1/2oz into existing outputs."""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

import scrape_all as s

TARGETS = [
    (
        "https://www.tacklewarehouse.com/Omega_Tungsten_Flip_Weights/descpage-OTF.html",
        "Omega",
        "Omega Tungsten Flip Weights",
    ),
    (
        "https://www.tacklewarehouse.com/Queen_Tackle_Tungsten_Flipping_Weights/descpage-JHSDFHD.html",
        "Queen Tackle",
        "Queen Tackle Tungsten Flipping Weights",
    ),
    (
        "https://www.tacklewarehouse.com/Evolution_Tungsten_Worm_Weights/descpage-EVWW.html",
        "Evolution",
        "Evolution Tungsten Worm Weights",
    ),
    (
        "https://www.tacklewarehouse.com/Evolution_Tungsten_Flipping_Weights/descpage-EVFW.html",
        "Evolution",
        "Evolution Tungsten Flipping Weights",
    ),
    (
        "https://www.tacklewarehouse.com/Gamakatsu_G-Shield_Tungsten_Worm_Weights/descpage-GTWM.html",
        "Gamakatsu",
        "Gamakatsu G-Shield Tungsten Worm Weights",
    ),
    (
        "https://www.tacklewarehouse.com/Strike_King_Tour_Grade_Tungsten_Weights/descpage-SKTGT.html",
        "Strike King",
        "Strike King Tour Grade Tungsten Weights",
    ),
]

DELAY_S = 2.5


def row_from_dict(d: dict) -> s.Row:
    return s.Row(
        brand=d["brand"],
        channel=d["channel"],
        cat=d["cat"],
        size=d["size"],
        g=d["g"],
        qty=d["qty"],
        packUsd=d["packUsd"],
        unitCny=d["unitCny"],
        yg=d["yg"],
        url=d.get("url", ""),
        color=d.get("color", ""),
        title=d.get("title", ""),
        source=d.get("source", ""),
    )


def oos_from_dict(d: dict) -> s.RawVariant:
    size = d["size"]
    oz = s.SIZE_FRAC.get(size.replace(" oz", ""), 0.0)
    return s.RawVariant(
        brand=d["brand"],
        channel=d["channel"],
        cat=d["cat"],
        size=size,
        oz=oz,
        qty=int(d.get("qty") or 0) or 1,
        pack_usd=float(d.get("packUsd") or 0),
        in_stock=False,
        color=d.get("color", ""),
        title=d.get("title", ""),
        url=d.get("url", ""),
        source="tacklewarehouse.com",
    )


def merge_rows(existing: list[s.Row], new_rows: list[s.Row]) -> list[s.Row]:
    by_key: dict[tuple, s.Row] = {}
    for r in existing:
        by_key[(r.brand, r.channel, r.cat, r.size)] = r
    for r in new_rows:
        key = (r.brand, r.channel, r.cat, r.size)
        prev = by_key.get(key)
        if prev is None or r.yg < prev.yg:
            by_key[key] = r
    out = list(by_key.values())
    out.sort(key=lambda r: (s.SIZE_ORDER.index(r.size) if r.size in s.SIZE_ORDER else 99, r.yg, r.brand))
    return out


def main() -> None:
    share_data = Path(s.SHARE / "data.json")
    payload = json.loads(share_data.read_text(encoding="utf-8"))
    existing = [row_from_dict(r) for r in payload["rows"]]
    existing_oos = [oos_from_dict(r) for r in payload.get("oos", [])]

    print(f"Existing instock rows: {len(existing)}")
    all_raw: list[s.RawVariant] = []
    notes: list[str] = []

    for i, (url, brand, name) in enumerate(TARGETS):
        if i:
            time.sleep(DELAY_S)
        print(f"Fetching ({i+1}/{len(TARGETS)}) {url}")
        rows = s.scrape_tw_product(url, brand, name)
        stocked = [r for r in rows if r.in_stock]
        print(f"  parsed={len(rows)} in_stock≤1/2oz={len(stocked)}")
        for r in stocked:
            print(f"    + {r.brand} {r.cat} {r.size} qty={r.qty} ${r.pack_usd} {r.color}")
        if not rows:
            notes.append(f"no parseable ≤1/2oz rows (or missing qty): {url}")
        elif not stocked:
            notes.append(f"parsed but all OOS / no in-stock ≤1/2oz: {url}")
        all_raw.extend(rows)

    new_instock, new_oos = s.prefer_color_rows(all_raw)
    print(f"New preferred in-stock: {len(new_instock)}")
    for r in new_instock:
        print(f"  MERGE {r.brand} {r.channel} {r.cat} {r.size} qty={r.qty} ${r.packUsd} ¥/g={r.yg}")

    merged = merge_rows(existing, new_instock)

    # OOS: keep existing + new OOS groups, dedupe by brand/channel/cat/size
    oos_by: dict[tuple, s.RawVariant] = {}
    for r in existing_oos + new_oos:
        key = (r.brand, r.channel, r.cat, r.size)
        oos_by[key] = r
    # drop OOS keys that now have in-stock
    in_keys = {(r.brand, r.channel, r.cat, r.size) for r in merged}
    oos_final = [v for k, v in oos_by.items() if k not in in_keys]

    # update STATUS note
    s.STATUS["ok"]["tw_serial_patch"] = {
        "pages": len(TARGETS),
        "raw": len(all_raw),
        "new_instock": len(new_instock),
        "merged_total": len(merged),
    }
    s.STATUS["notes"] = notes
    # preserve prior scrapeStatus ok/fail lightly
    prior_ok = (payload.get("meta") or {}).get("scrapeStatus", {}).get("ok", {})
    if isinstance(prior_ok, dict):
        s.STATUS["ok"] = {**prior_ok, **s.STATUS["ok"]}

    print(f"Writing outputs: instock={len(merged)} oos={len(oos_final)}")
    out_payload = s.write_outputs(merged, oos_final)
    s.patch_static_and_canvas(out_payload)
    (s.OUT / "merge_tw_serial.json").write_text(
        json.dumps(
            {
                "notes": notes,
                "new_instock": [asdict(r) for r in new_instock],
                "merged_count": len(merged),
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print("DONE")


if __name__ == "__main__":
    main()
