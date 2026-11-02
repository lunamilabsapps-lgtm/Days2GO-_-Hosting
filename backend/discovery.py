import re
import asyncio
import httpx
from rapidfuzz import fuzz
from core import (db, uid, iso, log, USER_AGENT, get_settings, norm_name, norm_phone, norm_domain,
                  haversine_m, activity, audit)

CATEGORY_TAGS = {
    "butchers": ['["shop"="butcher"]'],
    "bakeries": ['["shop"="bakery"]', '["shop"="pastry"]'],
    "cafes": ['["amenity"="cafe"]'],
    "restaurants": ['["amenity"="restaurant"]'],
    "florists": ['["shop"="florist"]'],
    "garden centres": ['["shop"="garden_centre"]'],
    "mechanics": ['["shop"="car_repair"]'],
    "panel beaters": ['["shop"="car_repair"]["name"~"panel|smash|body|collision",i]', '["craft"="panel_beater"]'],
    "hairdressers": ['["shop"="hairdresser"]'],
    "barbers": ['["shop"="hairdresser"]["hairdresser"="barber"]', '["shop"="hairdresser"]["name"~"barber",i]'],
    "beauty salons": ['["shop"="beauty"]'],
    "plumbers": ['["craft"="plumber"]', '["shop"="plumber"]'],
    "electricians": ['["craft"="electrician"]', '["shop"="electrical"]'],
    "independent retailers": ['["shop"~"^(gift|clothes|books|hardware|variety_store|toys|shoes|houseware|stationery)$"]'],
    "pet shops": ['["shop"="pet"]', '["shop"="pet_grooming"]'],
    "specialty food stores": ['["shop"~"^(deli|cheese|greengrocer|seafood|confectionery|wine|spices|tea|coffee)$"]'],
    "accommodation businesses": ['["tourism"~"^(hotel|motel|guest_house|hostel|apartment)$"]'],
}
NOMINATIM = "https://nominatim.openstreetmap.org"


def category_filters(category, subcategory=None):
    key = (category or "").strip().lower()
    filters = CATEGORY_TAGS.get(key)
    if not filters:
        word = re.escape(key.rstrip("s")) or "shop"
        filters = [f'["shop"]["name"~"{word}",i]', f'["craft"]["name"~"{word}",i]',
                   f'["amenity"]["name"~"{word}",i]', f'["shop"~"{word}",i]', f'["craft"~"{word}",i]']
    if subcategory:
        sub = re.escape(subcategory.strip())
        filters = [f + f'["name"~"{sub}",i]' for f in filters]
    return filters


async def overpass(query):
    s = await get_settings()
    last = None
    for ep in s["overpass_endpoints"]:
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(75, connect=8), headers={"User-Agent": USER_AGENT}) as c:
                    r = await c.post(ep, data={"data": query})
                if r.status_code == 200:
                    return r.json(), ep
                last = f"{ep} HTTP {r.status_code}"
                if r.status_code not in (429, 502, 503, 504):
                    break
            except (httpx.ConnectError, httpx.ConnectTimeout):
                last = f"{ep} unreachable"
                break
            except Exception as e:
                last = f"{ep} {type(e).__name__}"
            await asyncio.sleep(3 * 2 ** attempt)
    raise RuntimeError(f"All Overpass endpoints failed: {last}")


async def geocode(city, state, country):
    q = ", ".join([x for x in (city, state, country) if x])
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": USER_AGENT}) as c:
        r = await c.get(f"{NOMINATIM}/search", params={"q": q, "format": "json", "limit": 1})
    r.raise_for_status()
    data = r.json()
    if not data:
        raise ValueError(f"Could not find location '{q}'")
    return data[0]


async def resolve_region(country, state, city, radius_km):
    key = f"{city}|{state}|{country}|{int(radius_km)}".lower()
    region = await db.regions.find_one({"key": key}, {"_id": 0})
    if region:
        return region, False
    g = await geocode(city, state, country)
    lat, lon = float(g["lat"]), float(g["lon"])
    q = f'[out:json][timeout:80];node["place"~"^(suburb|town|village|city)$"](around:{int(radius_km * 1000)},{lat},{lon});out;'
    data, ep = await overpass(q)
    region = {"id": uid(), "key": key, "name": city, "state": state, "country": country, "lat": lat, "lon": lon,
              "radius_km": radius_km, "display_name": g.get("display_name"), "source": "OpenStreetMap Nominatim + Overpass",
              "created_at": iso()}
    await db.regions.insert_one(dict(region))
    seen = set()
    for el in data.get("elements", []):
        name = el.get("tags", {}).get("name")
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        z = {"id": uid(), "region_id": region["id"], "name": name, "lat": el["lat"], "lon": el["lon"],
             "kind": el["tags"].get("place"), "osm_id": f"node/{el['id']}",
             "distance_km": round(haversine_m(lat, lon, el["lat"], el["lon"]) / 1000, 2)}
        try:
            await db.zones.insert_one(z)
        except Exception:
            pass
    await audit("region_resolved", "region", region["id"], {"key": key, "zones": len(seen)})
    return region, True


def filter_zones(zones, region, direction):
    if not direction or direction == "all":
        return zones
    out = []
    for z in zones:
        dlat, dlon = z["lat"] - region["lat"], z["lon"] - region["lon"]
        ok = {"north": dlat > 0.02, "south": dlat < -0.02, "east": dlon > 0.03, "west": dlon < -0.03,
              "inner": z.get("distance_km", 99) <= 10}.get(direction, True)
        if ok:
            out.append(z)
    return out


def _addr(t):
    parts = [" ".join(x for x in [t.get("addr:housenumber"), t.get("addr:street")] if x), t.get("addr:suburb") or t.get("addr:city"),
             t.get("addr:state"), t.get("addr:postcode")]
    return ", ".join(p for p in parts if p)


def osm_to_candidate(el, zone, region, category):
    t = el.get("tags", {})
    lat = el.get("lat") or (el.get("center") or {}).get("lat")
    lon = el.get("lon") or (el.get("center") or {}).get("lon")
    website = t.get("website") or t.get("contact:website") or t.get("url") or ""
    if website and not website.startswith("http"):
        website = "https://" + website
    phone = t.get("phone") or t.get("contact:phone") or ""
    email = t.get("email") or t.get("contact:email") or ""
    socials = {k: t[k] for k in ("contact:facebook", "contact:instagram", "facebook", "instagram") if t.get(k)}
    return {
        "name": t.get("name", "").strip(), "category": category, "address": _addr(t),
        "suburb": t.get("addr:suburb") or zone["name"], "city": region["name"], "state": region["state"],
        "country": region["country"], "lat": lat, "lon": lon, "phone": phone, "website": website, "osm_email": email,
        "socials": socials, "brand": t.get("brand") or t.get("operator") or "",
        "source": "openstreetmap", "source_key": f"osm:{el['type']}/{el['id']}",
        "source_url": f"https://www.openstreetmap.org/{el['type']}/{el['id']}", "opening_hours": t.get("opening_hours", ""),
    }


async def find_duplicate(c):
    """Returns (existing, reason, is_location_sibling)."""
    ex = await db.businesses.find_one({"source_key": c["source_key"]}, {"_id": 0})
    if ex:
        return ex, "same source record", False
    dom = norm_domain(c["website"])
    social = dom in ("facebook.com", "instagram.com", "linktr.ee", "")
    if dom and not social:
        for ex in await db.businesses.find({"domain": dom}, {"_id": 0}).to_list(50):
            if haversine_m(ex.get("lat"), ex.get("lon"), c["lat"], c["lon"]) < 300:
                return ex, "same website domain at same location", False
        sib = await db.businesses.find_one({"domain": dom}, {"_id": 0})
        if sib:
            return sib, "same website domain, different location", True
    pn = norm_phone(c["phone"])
    if pn and len(pn) >= 8:
        for ex in await db.businesses.find({"phone_norm": pn}, {"_id": 0}).to_list(50):
            if haversine_m(ex.get("lat"), ex.get("lon"), c["lat"], c["lon"]) < 300:
                return ex, "same phone number", False
    nn = norm_name(c["name"])
    if c["lat"] is not None:
        d = 0.003
        near = await db.businesses.find({"lat": {"$gt": c["lat"] - d, "$lt": c["lat"] + d},
                                         "lon": {"$gt": c["lon"] - d, "$lt": c["lon"] + d}}, {"_id": 0}).to_list(200)
        for ex in near:
            if fuzz.token_sort_ratio(nn, ex.get("name_norm", "")) >= 88 and haversine_m(ex["lat"], ex["lon"], c["lat"], c["lon"]) < 200:
                return ex, "fuzzy name match nearby", False
    if c["address"]:
        ex = await db.businesses.find_one({"name_norm": nn, "address": c["address"]}, {"_id": 0})
        if ex:
            return ex, "same name and street address", False
    return None, None, False


async def ingest_candidate(c, search, zone, slot=0):
    """Dedupe + insert. Returns 'new' | 'duplicate' | 'skipped'."""
    if not c["name"]:
        return "skipped"
    await activity("dedupe", f"Checking database for duplicates: {c['name']}", c, search["id"], slot=slot)
    ex, reason, sibling = await find_duplicate(c)
    ev = {"id": uid(), "search_id": search["id"], "zone_id": zone["id"], "source": c["source"],
          "source_key": c["source_key"], "name": c["name"], "created_at": iso()}
    if ex and not sibling:
        await db.businesses.update_one({"id": ex["id"]}, {"$addToSet": {"search_ids": search["id"], "categories": c["category"]},
                                                         "$set": {"last_seen_at": iso()}})
        await db.discovery_events.insert_one({**ev, "result": "duplicate", "business_id": ex["id"], "reason": reason})
        await activity("duplicate", f"Duplicate skipped: {c['name']} ({reason})", ex, search["id"], slot=slot)
        return "duplicate"
    b = {**c, "id": uid(), "name_norm": norm_name(c["name"]), "phone_norm": norm_phone(c["phone"]),
         "domain": norm_domain(c["website"]), "categories": [c["category"]], "search_ids": [search["id"]],
         "region_id": search["region_id"], "zone_id": zone["id"], "research_status": "pending",
         "website_status": "unknown" if c["website"] else "no_website_listed", "email_status": "none",
         "reply_status": "none", "follow_up_status": "none", "excluded": False, "notes": "",
         "score": None, "grade": None, "parent_group": None, "discovered_at": iso(), "last_seen_at": iso()}
    if sibling:
        b["parent_group"] = ex.get("parent_group") or ex["id"]
        await db.businesses.update_one({"id": ex["id"]}, {"$set": {"parent_group": b["parent_group"]}})
    try:
        await db.businesses.insert_one(dict(b))
    except Exception:
        return "duplicate"
    await db.discovery_events.insert_one({**ev, "result": "new", "business_id": b["id"],
                                          "reason": "additional location of existing business" if sibling else None})
    await audit("business_discovered", "business", b["id"], {"name": b["name"], "source": b["source_key"]})
    await activity("accepted", f"New prospect accepted: {b['name']}" + (" (additional location)" if sibling else ""),
                   b, search["id"], data={"suburb": b["suburb"], "website": b["website"]}, slot=slot)
    return "new"


async def search_zone(search, zone, radius_m, slot=0):
    filters = category_filters(search["category"], search.get("subcategory"))
    body = "".join(f'nwr{f}(around:{radius_m},{zone["lat"]},{zone["lon"]});' for f in filters)
    q = f"[out:json][timeout:60];({body});out tags center;"
    data, ep = await overpass(q)
    els = [e for e in data.get("elements", []) if e.get("tags", {}).get("name")]
    return els, ep, q
