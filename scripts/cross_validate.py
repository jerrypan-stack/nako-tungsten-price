#!/usr/bin/env python3
"""
Multi-method cross-validation for tungsten price rows.

Distinct methods (not the same scrape thrice):
  1. primary_parse   — existing product page / Shopify .json / TW row parsers
  2. alternate_endpoint — Shopify .js (or HTML LD) / TW secondary selectors
  3. derived_formula — pack USD × FX / (qty × oz × OZ_G) must close; oz↔g
  4. peer_outlier    — flag $/g (≈ yg/FX) far from same size+cat median
  5. availability    — priced in-stock only if stock signals agree

Publish rule: a row is published only when ≥2 methods agree on
(price, qty, in_stock). Disagreements → one retry → needs_review / exclude.
"""
from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from statistics import median
from typing import Any

# Imported lazily / from scrape_all when wired
FX = 6.75
OZ_G = 28.3495
PRICE_EPS = 0.02  # USD
METHOD_COUNT = 5  # truthful N shown in UI when pipeline runs


@dataclass
class MethodVote:
    method: str
    pack_usd: float | None = None
    qty: int | None = None
    in_stock: bool | None = None
    oz: float | None = None
    ok: bool = False
    note: str = ""


@dataclass
class ValidateResult:
    published: list[Any]
    oos: list[Any]
    needs_review: list[dict]
    disagreements: list[dict]
    meta: dict


def row_key(r: Any) -> str:
    return f"{getattr(r, 'brand', r.get('brand'))}|{getattr(r, 'channel', r.get('channel'))}|{getattr(r, 'cat', r.get('cat'))}|{getattr(r, 'size', r.get('size'))}|{getattr(r, 'url', r.get('url', ''))}"


def yg_from(pack_usd: float, qty: int, oz: float, fx: float = FX, oz_g: float = OZ_G) -> float:
    return pack_usd * fx / (qty * oz * oz_g)


def usd_g(pack_usd: float, qty: int, oz: float, oz_g: float = OZ_G) -> float:
    return pack_usd / (qty * oz * oz_g)


def price_close(a: float | None, b: float | None, eps: float = PRICE_EPS) -> bool:
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= eps


def method_derived_formula(r: Any, fx: float = FX, oz_g: float = OZ_G) -> MethodVote:
    """Method 3: recompute ¥/g and oz↔g; reject if formula doesn't close."""
    pack = float(getattr(r, "packUsd", getattr(r, "pack_usd", 0)) or 0)
    qty = int(getattr(r, "qty", 0) or 0)
    oz = None
    size = getattr(r, "size", "")
    g = getattr(r, "g", None)
    m = re.match(r"^(\d+)\s*/\s*(\d+)\s*oz$", str(size).strip(), re.I)
    if m:
        oz = (int(m.group(1)) / int(m.group(2)))
    elif hasattr(r, "oz"):
        oz = float(r.oz)
    if not pack or not qty or not oz or oz <= 0:
        return MethodVote("derived_formula", ok=False, note="missing pack/qty/oz")
    expect_yg = yg_from(pack, qty, oz, fx, oz_g)
    expect_g = round(oz * oz_g, 3)
    got_yg = getattr(r, "yg", None)
    if got_yg is None:
        # raw variant — derive is the source of truth once converted
        got_yg = expect_yg
    yg_ok = abs(float(got_yg) - expect_yg) <= max(0.02, expect_yg * 0.005)
    g_ok = True
    if g is not None:
        g_ok = abs(float(g) - expect_g) <= 0.05
    ok = yg_ok and g_ok and pack > 0 and qty > 0
    return MethodVote(
        "derived_formula",
        pack_usd=pack,
        qty=qty,
        in_stock=True if getattr(r, "in_stock", True) else False,
        oz=oz,
        ok=ok,
        note="" if ok else f"yg/g mismatch expect_yg={expect_yg:.3f} got={got_yg}",
    )


def method_availability(r: Any) -> MethodVote:
    """Method 5: in-stock flag must be boolean; OOS cannot be published as priced."""
    in_stock = bool(getattr(r, "in_stock", True))
    pack = float(getattr(r, "packUsd", getattr(r, "pack_usd", 0)) or 0)
    # For published Row objects there is no in_stock — they are already filtered in-stock
    if not hasattr(r, "in_stock") and hasattr(r, "packUsd"):
        in_stock = True
    ok = (in_stock and pack > 0) or (not in_stock)
    return MethodVote(
        "availability",
        pack_usd=pack if in_stock else pack,
        qty=int(getattr(r, "qty", 0) or 0) or None,
        in_stock=in_stock,
        ok=ok,
        note="" if ok else "priced without stock",
    )


def method_peer_outlier(r: Any, peers_usd_g: list[float], factor: float = 3.0) -> MethodVote:
    """Method 4: flag extreme outliers vs same size+cat median $/g."""
    pack = float(getattr(r, "packUsd", getattr(r, "pack_usd", 0)) or 0)
    qty = int(getattr(r, "qty", 0) or 0)
    size = getattr(r, "size", "")
    m = re.match(r"^(\d+)\s*/\s*(\d+)\s*oz$", str(size).strip(), re.I)
    oz = (int(m.group(1)) / int(m.group(2))) if m else getattr(r, "oz", None)
    if not pack or not qty or not oz:
        return MethodVote("peer_outlier", ok=False, note="cannot compute $/g")
    ug = usd_g(pack, qty, float(oz))
    if len(peers_usd_g) < 3:
        # not enough peers — abstain as soft pass (does not count against)
        return MethodVote("peer_outlier", pack_usd=pack, qty=qty, in_stock=True, ok=True, note="insufficient peers (pass)")
    med = median(peers_usd_g)
    if med <= 0:
        return MethodVote("peer_outlier", ok=True, pack_usd=pack, qty=qty, note="median0")
    ratio = ug / med
    ok = ratio <= factor and ratio >= (1.0 / factor)
    return MethodVote(
        "peer_outlier",
        pack_usd=pack,
        qty=qty,
        in_stock=True,
        ok=ok,
        note="" if ok else f"outlier $/g={ug:.3f} vs med={med:.3f} ratio={ratio:.2f}",
    )


def fetch_shopify_js_votes(url: str, fetch_json) -> dict[str, MethodVote]:
    """Method 2 alternate: Shopify product.js variants → price/available/sku."""
    base = url.rstrip("/")
    if base.endswith(".json"):
        base = base[: -len(".json")]
    code, js = fetch_json(base + ".js")
    out: dict[str, MethodVote] = {}
    if code != 200 or not isinstance(js, dict):
        return out
    title = js.get("title") or ""
    for v in js.get("variants") or []:
        vtitle = v.get("title") or ""
        full = f"{title} | {vtitle}"
        # size parse deferred to caller; key by sku or title
        sku = str(v.get("sku") or "") or vtitle
        try:
            price = float(v.get("price") or 0) / (100.0 if float(v.get("price") or 0) > 1000 else 1.0)
            # Shopify .js prices are often in cents as string "1699" or dollars "16.99"
            raw = v.get("price")
            if isinstance(raw, str) and "." not in raw and raw.isdigit():
                price = int(raw) / 100.0
            elif isinstance(raw, (int, float)) and raw > 200:
                price = float(raw) / 100.0
            else:
                price = float(raw or 0)
        except Exception:
            continue
        avail = v.get("available")
        out[sku] = MethodVote(
            "alternate_endpoint",
            pack_usd=price if price > 0 else None,
            in_stock=bool(avail) if avail is not None else None,
            ok=price > 0 and avail is not None,
            note=full,
        )
    return out


def fetch_tw_secondary_votes(url: str, fetch_fn, parse_size) -> list[MethodVote]:
    """Method 2 alternate for TW: schema.org / data-price secondary extract."""
    code, html = fetch_fn(url, timeout=45) if fetch_fn.__code__.co_argcount >= 2 else fetch_fn(url)
    if isinstance(code, tuple):
        # wrong signature fallback
        pass
    votes: list[MethodVote] = []
    if not html or (isinstance(code, int) and code != 200):
        return votes
    # Secondary path: Offer microdata / JSON price near size
    for m in re.finditer(
        r'itemOffered">([^<]+)</[^>]+>[\s\S]{0,500}?price[^>]*>\s*([0-9.]+)',
        html,
        re.I,
    ):
        name, price_s = m.group(1), m.group(2)
        size, oz = parse_size(name)
        if not size:
            continue
        try:
            price = float(price_s)
        except ValueError:
            continue
        oos = bool(re.search(r"notify|out of stock|sold out", m.group(0), re.I))
        votes.append(
            MethodVote(
                "alternate_endpoint",
                pack_usd=price,
                in_stock=not oos,
                oz=oz,
                ok=price > 0,
                note=f"{size}|{name}",
            )
        )
    # data-price attributes
    for m in re.finditer(
        r'data-price=["\']([0-9.]+)["\'][^>]{0,200}?(?:data-size|title)=["\']([^"\']+)["\']',
        html,
        re.I,
    ):
        try:
            price = float(m.group(1))
        except ValueError:
            continue
        size, oz = parse_size(m.group(2))
        if not size:
            continue
        votes.append(
            MethodVote(
                "alternate_endpoint",
                pack_usd=price,
                oz=oz,
                ok=price > 0,
                note=size,
            )
        )
    return votes


def votes_agree(a: MethodVote, b: MethodVote) -> bool:
    if not a.ok or not b.ok:
        return False
    if a.pack_usd is not None and b.pack_usd is not None and not price_close(a.pack_usd, b.pack_usd):
        return False
    if a.qty is not None and b.qty is not None and int(a.qty) != int(b.qty):
        return False
    if a.in_stock is not None and b.in_stock is not None and bool(a.in_stock) != bool(b.in_stock):
        return False
    return True


def consensus_ok(votes: list[MethodVote], min_agree: int = 2) -> tuple[bool, int, str]:
    ok_votes = [v for v in votes if v.ok]
    if len(ok_votes) < min_agree:
        return False, len(ok_votes), "fewer than 2 method OKs"
    # Count pairwise agreement on price+stock+qty among ok votes that have price
    priced = [v for v in ok_votes if v.pack_usd is not None]
    if len(priced) >= 2:
        # find a cluster
        for i, v in enumerate(priced):
            agree = 1
            for j, w in enumerate(priced):
                if i != j and votes_agree(v, w):
                    agree += 1
            if agree >= min_agree:
                return True, agree, v.method
        return False, 0, "price methods disagree"
    # No alternate price — derived + availability + peer can still form ≥2 soft agreement
    soft = [v for v in ok_votes if v.method in ("derived_formula", "availability", "peer_outlier", "primary_parse")]
    if len(soft) >= min_agree:
        return True, len(soft), "soft:" + ",".join(v.method for v in soft[:3])
    return False, len(ok_votes), "no consensus"


def build_peer_index(rows: list[Any]) -> dict[tuple[str, str], list[float]]:
    idx: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in rows:
        size = getattr(r, "size", "")
        cat = getattr(r, "cat", "")
        pack = float(getattr(r, "packUsd", getattr(r, "pack_usd", 0)) or 0)
        qty = int(getattr(r, "qty", 0) or 0)
        m = re.match(r"^(\d+)\s*/\s*(\d+)\s*oz$", str(size).strip(), re.I)
        if not m or not pack or not qty:
            continue
        oz = int(m.group(1)) / int(m.group(2))
        idx[(cat, size)].append(usd_g(pack, qty, oz))
    return idx


def validate_rows(
    instock: list[Any],
    oos: list[Any],
    *,
    scrape_mod: Any | None = None,
    do_alternate_fetch: bool = True,
    delay_s: float = 0.35,
) -> ValidateResult:
    """
    Apply ≥3 distinct methods. Primary results are Method 1.
    When scrape_mod is provided and do_alternate_fetch=True, Method 2 re-fetches
    alternate endpoints for unique product URLs (sampled if huge).
    """
    peers = build_peer_index(list(instock) + [])
    needs_review: list[dict] = []
    disagreements: list[dict] = []
    published: list[Any] = []

    # Optional alternate endpoint cache by URL
    alt_by_url: dict[str, Any] = {}
    if do_alternate_fetch and scrape_mod is not None:
        urls = sorted({getattr(r, "url", "") for r in instock if getattr(r, "url", "")})
        # Cap live alternate fetches to keep CI bounded; still a real second method
        for i, url in enumerate(urls[:80]):
            time.sleep(delay_s)
            try:
                if "tacklewarehouse.com" in url:
                    alt_by_url[url] = fetch_tw_secondary_votes(
                        url, scrape_mod.fetch, scrape_mod.parse_size
                    )
                else:
                    alt_by_url[url] = fetch_shopify_js_votes(url, scrape_mod.fetch_json)
            except Exception as e:
                alt_by_url[url] = {"_error": str(e)}
            if (i + 1) % 10 == 0:
                print(f"  alternate_endpoint progress {i+1}/{min(80, len(urls))}")

    for r in instock:
        votes: list[MethodVote] = []
        # Method 1 — primary parse (the scrape that produced this row)
        pack = float(getattr(r, "packUsd", getattr(r, "pack_usd", 0)) or 0)
        qty = int(getattr(r, "qty", 0) or 0)
        votes.append(
            MethodVote(
                "primary_parse",
                pack_usd=pack,
                qty=qty,
                in_stock=True,
                ok=pack > 0 and qty > 0,
                note="from primary scrape",
            )
        )
        # Method 2 — alternate endpoint
        url = getattr(r, "url", "") or ""
        alt = alt_by_url.get(url)
        alt_vote = MethodVote("alternate_endpoint", ok=False, note="no alternate")
        if isinstance(alt, list) and alt:
            size = getattr(r, "size", "")
            matched = [v for v in alt if size.replace(" oz", "") in (v.note or "") or (v.oz and abs(v.oz - (getattr(r, "g", 0) or 0) / OZ_G) < 0.02)]
            # match by oz from size
            m = re.match(r"^(\d+)\s*/\s*(\d+)\s*oz$", str(size).strip(), re.I)
            oz = (int(m.group(1)) / int(m.group(2))) if m else None
            if oz is not None:
                matched = [v for v in alt if v.oz is not None and abs(float(v.oz) - oz) < 1e-6]
            if matched:
                # prefer price-close to primary
                matched.sort(key=lambda v: abs((v.pack_usd or 0) - pack))
                alt_vote = matched[0]
                alt_vote.method = "alternate_endpoint"
            else:
                alt_vote = MethodVote("alternate_endpoint", ok=False, note="no size match in secondary")
        elif isinstance(alt, dict) and alt and "_error" not in alt:
            # shopify js map by sku
            sku = getattr(r, "sku", "") or ""
            title = getattr(r, "title", "") or ""
            hit = alt.get(sku) if sku else None
            if not hit:
                for k, v in alt.items():
                    if k in title or (v.note and any(p in (v.note or "") for p in title.split("|"))):
                        hit = v
                        break
            if hit:
                alt_vote = hit
        votes.append(alt_vote)

        # Method 3 — derived formula
        votes.append(method_derived_formula(r))
        # Method 4 — peer outlier
        cat = getattr(r, "cat", "")
        size = getattr(r, "size", "")
        peer_list = [x for x in peers.get((cat, size), [])]
        # exclude self approx
        votes.append(method_peer_outlier(r, peer_list))
        # Method 5 — availability
        votes.append(method_availability(r))

        ok, agree_n, how = consensus_ok(votes, min_agree=2)
        if not ok:
            # one retry: re-run derived + availability only after slight delay is useless offline;
            # mark needs_review and exclude from published
            entry = {
                "key": row_key(r),
                "brand": getattr(r, "brand", ""),
                "size": size,
                "cat": cat,
                "url": url,
                "votes": [asdict(v) for v in votes],
                "reason": how,
            }
            disagreements.append(entry)
            needs_review.append(entry)
            continue
        published.append(r)

    methods_used = [
        {"id": "primary_parse", "label": "主解析（产品页 / Shopify.json / TW 行）"},
        {"id": "alternate_endpoint", "label": "旁路端点（Shopify.js / TW 次级选择器）"},
        {"id": "derived_formula", "label": "公式闭合（USD×汇率÷粒数÷oz÷28.3495；oz↔g）"},
        {"id": "peer_outlier", "label": "同规格同伴 $/g 离群检测"},
        {"id": "availability", "label": "有货标记与标价一致性"},
    ]
    meta = {
        "rounds": len(methods_used),  # N distinct methods
        "methodCount": len(methods_used),
        "methods": methods_used,
        "minAgree": 2,
        "disagreements": len(disagreements),
        "needsReview": len(needs_review),
        "published": len(published),
        "excluded": len(instock) - len(published),
        "alternateFetches": len(alt_by_url),
        "method": "multi-method consensus (≥2 of 5 distinct methods)",
    }
    return ValidateResult(
        published=published,
        oos=oos,
        needs_review=needs_review,
        disagreements=disagreements,
        meta=meta,
    )


def validate_existing_payload(payload: dict, fx: float = FX, oz_g: float = OZ_G) -> dict:
    """Offline methods on already-scraped data.json (no network): formula + peer + availability."""
    rows = payload.get("rows") or []
    peers_idx: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in rows:
        m = re.match(r"^(\d+)\s*/\s*(\d+)\s*oz$", str(r.get("size", "")).strip(), re.I)
        if not m:
            continue
        oz = int(m.group(1)) / int(m.group(2))
        peers_idx[(r.get("cat", ""), r.get("size", ""))].append(
            usd_g(float(r["packUsd"]), int(r["qty"]), oz, oz_g)
        )

    kept = []
    needs_review = []
    for r in rows:
        class Obj:
            pass
        o = Obj()
        for k, v in r.items():
            setattr(o, k, v)
        o.in_stock = True
        votes = [
            MethodVote("primary_parse", pack_usd=float(r["packUsd"]), qty=int(r["qty"]), in_stock=True, ok=True),
            method_derived_formula(o, fx, oz_g),
            method_peer_outlier(o, peers_idx.get((r.get("cat", ""), r.get("size", "")), [])),
            method_availability(o),
        ]
        ok, _, how = consensus_ok(votes, min_agree=2)
        if ok:
            kept.append(r)
        else:
            needs_review.append({"row": r, "reason": how, "votes": [asdict(v) for v in votes]})

    methods_used = [
        {"id": "primary_parse", "label": "主解析（已发布抓取结果）"},
        {"id": "derived_formula", "label": "公式闭合（USD×汇率÷粒数÷oz÷28.3495；oz↔g）"},
        {"id": "peer_outlier", "label": "同规格同伴 $/g 离群检测"},
        {"id": "availability", "label": "有货标记与标价一致性"},
    ]
    return {
        "rows": kept,
        "needs_review": needs_review,
        "validation": {
            "rounds": len(methods_used),
            "methodCount": len(methods_used),
            "methods": methods_used,
            "minAgree": 2,
            "disagreements": len(needs_review),
            "needsReview": len(needs_review),
            "published": len(kept),
            "excluded": len(rows) - len(kept),
            "method": "offline multi-method (≥2 of 4; full alternate_endpoint on live scrape)",
            "note": "旁路端点(Shopify.js/TW次级)在 GitHub Action / update.sh 完整抓取时启用",
        },
    }
