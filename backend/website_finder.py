import os
import re
import json
from datetime import datetime, timedelta, timezone
import httpx
from rapidfuzz import fuzz
from bs4 import BeautifulSoup
from core import db, uid, iso, log, get_settings, norm_name, norm_phone, norm_domain, activity, audit
from assess import fetch, robots_allowed, SOCIAL

SERPER = "https://google.serper.dev"
BRAVE = "https://api.search.brave.com/res/v1/web/search"
COST = {"serper": 0.001, "brave": 0.005}
BLOCKED = ("facebook.com", "instagram.com", "linktr.ee", "tiktok.com", "youtube.com", "x.com", "twitter.com", "linkedin.com",
           "pinterest.com", "yelp.com", "yelp.com.au", "yellowpages.com.au", "truelocal.com.au", "hotfrog.com.au",
           "localsearch.com.au", "startlocal.com.au", "tripadvisor.com", "tripadvisor.com.au", "google.com", "maps.google.com",
           "goo.gl", "g.page", "business.site", "wikipedia.org", "openstreetmap.org", "ubereats.com", "doordash.com",
           "menulog.com.au", "zomato.com", "broadsheet.com.au", "timeout.com", "agfg.com.au", "whitepages.com.au",
           "abr.business.gov.au", "abn.business.gov.au", "seek.com.au", "indeed.com", "gumtree.com.au", "productreview.com.au",
           "word-of-mouth.com.au", "oneflare.com.au", "hipages.com.au", "airtasker.com", "nearmap.com", "mapquest.com",
           "cylex.com.au", "aussieweb.com.au", "brownbook.net", "infobel.com", "waze.com", "apple.com", "bing.com",
           "realestate.com.au", "domain.com.au", "squareup.com", "fresha.com", "opentable.com.au", "opentable.com",
           "foursquare.com", "restaurantguru.com", "wanderlog.com", "groupon.com.au", "linktree.com",
           "theage.com.au", "smh.com.au", "heraldsun.com.au", "news.com.au", "abc.net.au", "theguardian.com",
           "concreteplayground.com", "urbanlist.com", "theurbanlist.com", "foodbyus.com.au", "wanderboat.ai",
           "poi-australia.com.au", "factoryoutletshopping.com.au", "au.trip.com", "trip.com", "mapcarta.com",
           "localfind.com.au", "yably.com.au", "finda.com.au", "dlook.com.au", "au.indeed.com", "jora.com",
           "glassdoor.com.au", "reddit.com", "whatsonmelbourne.com.au", "onlymelbourne.com.au", "visitmelbourne.com",
           "timeout.com.au", "gourmettraveller.com.au", "delicious.com.au", "goodfood.com.au", "mobi-order.com")
GENERIC = {"butchers", "butcher", "meats", "meat", "cafe", "café", "bakery", "bakers", "restaurant", "florist", "florists",
           "hair", "salon", "beauty", "barber", "barbers", "plumbing", "plumber", "electrical", "electrician", "and", "of",
           "free", "range", "quality", "family", "fresh", "shop", "store", "melbourne", "the", "co", "pty", "ltd", "kitchen"}
STATES = {"victoria": "VIC", "new south wales": "NSW", "queensland": "QLD", "south australia": "SA",
          "western australia": "WA", "tasmania": "TAS", "northern territory": "NT", "australian capital territory": "ACT"}


def keys():
    return os.environ.get("SERPER_API_KEY", ""), os.environ.get("BRAVE_API_KEY", "")


def blocked(dom):
    return not dom or any(dom == b or dom.endswith("." + b) for b in BLOCKED) or dom.endswith(".gov.au")


def core_tokens(name):
    return [t for t in norm_name(name).split() if len(t) > 2 and t not in GENERIC]


async def log_usage(provider, business_id, query):
    await db.api_usage.insert_one({"id": uid(), "provider": provider, "business_id": business_id, "query": query,
                                   "cost_usd_est": COST[provider], "created_at": iso()})


async def serper(path, q, bid):
    sk, _ = keys()
    async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5)) as c:
        r = await c.post(f"{SERPER}/{path}", headers={"X-API-KEY": sk, "Content-Type": "application/json"},
                         json={"q": q, "gl": "au", "hl": "en", "num": 10})
    await log_usage("serper", bid, q)
    r.raise_for_status()
    return r.json()


async def brave(q, bid):
    _, bk = keys()
    async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5)) as c:
        r = await c.get(BRAVE, headers={"X-Subscription-Token": bk, "Accept": "application/json"},
                        params={"q": q, "country": "AU", "search_lang": "en", "count": 10})
    await log_usage("brave", bid, q)
    r.raise_for_status()
    return r.json()


def add_candidate(cands, url, provider, **info):
    if not url:
        return
    if not url.startswith("http"):
        url = "https://" + url
    from urllib.parse import urlparse
    if provider != "google_maps_via_serper" and len([x for x in urlparse(url).path.split("/") if x]) >= 2:
        return  # deep article/listing pages are almost never the business's own homepage
    dom = norm_domain(url)
    if blocked(dom):
        return
    c = cands.setdefault(dom, {"domain": dom, "url": f"https://{dom}", "providers": [], "listing": None, "rank": 99})
    if provider not in c["providers"]:
        c["providers"].append(provider)
    if info.get("listing") and not c["listing"]:
        c["listing"] = info["listing"]
    c["rank"] = min(c["rank"], info.get("rank", 99))


def listing_matches(b, place):
    title_ratio = fuzz.token_set_ratio(norm_name(b["name"]), norm_name(place.get("title", "")))
    title_ok = title_ratio >= 80
    addr = (place.get("address") or "").lower()
    pc = re.search(r"\b(\d{4})\b", b.get("address") or "")
    street = (b.get("address") or "").split(",")[0].lower().strip()
    loc_ok = bool(b.get("suburb")) and b["suburb"].lower() in addr or bool(pc and pc.group(1) in addr) or bool(street and len(street) > 5 and street in addr)
    phone_ok = bool(norm_phone(b.get("phone"))) and norm_phone(b.get("phone")) == norm_phone(place.get("phoneNumber"))
    return title_ok, loc_ok, phone_ok, title_ratio >= 95


async def page_text(url):
    if not await robots_allowed(url):
        return None
    r, _ = await fetch(url)
    if r.status_code >= 400 or "html" not in r.headers.get("content-type", "html"):
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    ld = " ".join(s.get_text(" ") for s in soup.find_all("script", attrs={"type": "application/ld+json"}))
    links = [a.get("href", "") for a in soup.find_all("a")]
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    return {"final_url": str(r.url), "title": (soup.title.get_text(" ", strip=True) if soup.title else "")[:200],
            "h1": " ".join(h.get_text(" ", strip=True) for h in soup.find_all("h1"))[:300],
            "text": re.sub(r"\s+", " ", soup.get_text(" ")).lower()[:60000], "ld": ld.lower()[:20000],
            "html_digits": re.sub(r"\D", "", r.text), "links": links}


async def verify(b, cand):
    """Visit the candidate site and score how well it matches the prospect. Returns (score, signals, final_url)."""
    try:
        home = await page_text(cand["url"])
    except Exception as e:
        return 0, [f"site could not be loaded ({type(e).__name__})"], None
    if not home:
        return 0, ["site unavailable or blocked by robots.txt"], None
    final_dom = norm_domain(home["final_url"])
    if blocked(final_dom):
        return 0, [f"redirects to a directory/social site ({final_dom})"], None
    pages = [home]
    for l in home["links"]:
        if re.search(r"contact|location|store|find-us|about|visit", l or "", re.I):
            from urllib.parse import urljoin
            u = urljoin(home["final_url"], l)
            if norm_domain(u) == final_dom and u.rstrip("/") != home["final_url"].rstrip("/"):
                try:
                    p = await page_text(u)
                    if p:
                        pages.append(p)
                except Exception:
                    pass
                if len(pages) >= 3:
                    break
    text = " ".join(p["text"] for p in pages)
    digits = "".join(p["html_digits"] for p in pages)
    head = f"{home['title']} {home['h1']}".lower()
    signals, score = [], 0
    nm = norm_name(b["name"])
    toks = core_tokens(b["name"])
    name_ratio = fuzz.token_set_ratio(nm, norm_name(head))
    name_hit = name_ratio >= 80 or (len(toks) >= 2 and all(t in head for t in toks))
    if name_hit:
        score += 25
        signals.append("business name in page title/heading")
    elif len(toks) >= 2 and all(t in text for t in toks):
        score += 10
        signals.append("business name appears in page text")
    compact = final_dom.split(".")[0].replace("-", "")
    name_compact = re.sub(r"[^a-z0-9]", "", nm)
    dom_tok = next((t for t in toks if len(t) >= 4 and t in compact and (len(toks) >= 2 or compact.startswith(t))), None)
    if dom_tok or (name_compact and fuzz.ratio(name_compact, compact) >= 85):
        score += 15
        signals.append(f"domain matches the business name")
    pn = norm_phone(b.get("phone"))
    phone_hit = bool(pn) and len(pn) >= 8 and pn[-8:] in digits
    if phone_hit:
        score += 35
        signals.append("same phone number on the website")
    loc_hit = False
    if b.get("suburb") and b["suburb"].lower() not in ("melbourne", "sydney", "brisbane", "perth", "adelaide", "hobart", "darwin", "canberra") \
            and re.search(rf"\b{re.escape(b['suburb'].lower())}\b", text):
        score += 15
        loc_hit = True
        signals.append(f"suburb '{b['suburb']}' on the website")
    street = re.sub(r"^\d+[a-z]?\s+", "", (b.get("address") or "").split(",")[0].lower()).strip()
    if street and len(street) > 5 and street in text:
        score += 15
        loc_hit = True
        signals.append(f"street '{street}' on the website")
    pc = re.search(r"\b(\d{4})\b", b.get("address") or "")
    if pc and pc.group(1) in text:
        score += 5
        signals.append(f"postcode {pc.group(1)} on the website")
    if home["ld"] and nm and fuzz.partial_ratio(nm, home["ld"]) >= 90:
        score += 10
        signals.append("business name in the site's structured business data")
    lst = cand.get("listing")
    if lst:
        if lst["title_ok"] and (lst["loc_ok"] or lst["phone_ok"]):
            score += 25
            signals.append("linked from this business's Google Maps listing")
        elif lst["title_ok"] and lst.get("exact") and lst.get("top"):
            score += 20
            signals.append("top Google Maps result for this name and area links to this site")
        elif lst["title_ok"]:
            score += 10
            signals.append("linked from a Google Maps listing with the same name (different location)")
    strong_listing = bool(lst and lst.get("exact") and lst.get("top") and dom_tok and name_hit)
    if not (name_hit or phone_hit):
        score = min(score, 45)
        signals.append("held for review: neither the name nor the phone number clearly matches")
    elif not (phone_hit or loc_hit or strong_listing or (lst and (lst["loc_ok"] or lst["phone_ok"]))):
        score = min(score, 60)
        signals.append("held for review: name matches but this location or phone number isn't confirmed (possible chain or other business)")
    return min(score, 100), signals, home["final_url"]


async def find_website(b, force=False, slot=None):
    """Tiered website discovery. Returns the stored lookup document."""
    s = (await get_settings())["website_discovery"]
    sid = b.get("_sid")
    key = f"{norm_name(b['name'])}|{(b.get('suburb') or '').lower()}"
    prev = await db.website_lookups.find_one({"business_id": b["id"]}, {"_id": 0})
    if prev and prev["status"] == "rejected_by_user" and not force:
        return prev
    fresh = datetime.now(timezone.utc) - timedelta(days=s["cache_days"])
    if not force:
        cached = prev or await db.website_lookups.find_one({"key": key, "status": {"$in": ["found", "needs_review", "not_found"]}}, {"_id": 0})
        if cached and not cached.get("stale") and cached["status"] != "search_unavailable" and datetime.fromisoformat(cached["searched_at"]) > fresh:
            if cached.get("business_id") != b["id"]:
                cached = {**cached, "id": uid(), "business_id": b["id"], "reused_from": cached["business_id"]}
                await db.website_lookups.update_one({"business_id": b["id"]}, {"$set": cached}, upsert=True)
            await activity("website_search", f"Website search result reused from cache ({cached['status'].replace('_', ' ')})", b, sid, slot=slot)
            return cached
    sk, bk = keys()
    cands, tiers, queries, errors = {}, [], [], []
    rejected = set((prev or {}).get("rejected_domains", []))
    # tier 1: existing business data
    q1 = [{"name_norm": b.get("name_norm") or norm_name(b["name"])}]
    if b.get("phone_norm"):
        q1.append({"phone_norm": b["phone_norm"]})
    for ex in await db.businesses.find({"$or": q1, "id": {"$ne": b["id"]}, "domain": {"$nin": ["", None]}},
                                       {"_id": 0, "website": 1, "name": 1}).to_list(10):
        add_candidate(cands, ex["website"], "existing_scout_record")
    tiers.append("existing_data")
    state = STATES.get((b.get("state") or "").lower(), b.get("state") or "")
    loc = " ".join(x for x in (b.get("suburb"), state) if x)

    async def evaluate():
        out = []
        for c in sorted(cands.values(), key=lambda x: x["rank"]):
            if c["domain"] in rejected or c.get("checked"):
                continue
            c["checked"] = True
            await activity("website_check", f"Checking candidate website {c['domain']}", b, sid, slot=slot)
            c["score"], c["signals"], c["final_url"] = await verify(b, c)
            out.append(c)
            if c["score"] >= s["confirm_threshold"] or len([x for x in cands.values() if x.get("checked")]) >= 5:
                break
        return out

    best = lambda: max([c for c in cands.values() if c.get("checked")], key=lambda c: c["score"], default=None)
    await evaluate()
    # tier 2: Serper (Google Maps then Google web)
    if not (best() and best()["score"] >= s["confirm_threshold"]) and sk:
        tiers.append("serper")
        await activity("website_search", f"Searching Google for {b['name']}'s website", b, sid, slot=slot)
        try:
            q = f"{b['name']} {loc}".strip()
            queries.append(f"serper places: {q}")
            for i, p in enumerate((await serper("places", q, b["id"])).get("places", [])[:10]):
                t, l, ph, ex = listing_matches(b, p)
                if p.get("website") and t:
                    add_candidate(cands, p["website"], "google_maps_via_serper", rank=i,
                                  listing={"title": p.get("title"), "address": p.get("address"), "title_ok": t, "loc_ok": l, "phone_ok": ph, "exact": ex, "top": i == 0})
            await evaluate()
            if not (best() and best()["score"] >= s["confirm_threshold"]):
                queries.append(f"serper search: {q}")
                for i, o in enumerate((await serper("search", q, b["id"])).get("organic", [])[:10]):
                    add_candidate(cands, o.get("link"), "google_search_via_serper", rank=10 + i)
                await evaluate()
        except Exception as e:
            errors.append(f"Serper: {type(e).__name__} {str(e)[:120]}")
    # tier 3: Brave only when Serper failed to produce a confident answer
    if not (best() and best()["score"] >= s["confirm_threshold"]) and bk and (errors or not sk or not best()):
        tiers.append("brave")
        try:
            q = f"{b['name']} {loc}".strip()
            queries.append(f"brave: {q}")
            for i, r in enumerate((await brave(q, b["id"])).get("web", {}).get("results", [])[:10]):
                add_candidate(cands, r.get("url"), "brave_search", rank=20 + i)
            await evaluate()
        except Exception as e:
            errors.append(f"Brave: {type(e).__name__} {str(e)[:120]}")
    top = best()
    checked = sorted([c for c in cands.values() if c.get("checked")], key=lambda c: -c["score"])
    searched = "serper" in tiers or "brave" in tiers
    if top and top["score"] >= s["confirm_threshold"]:
        status = "found"
    elif top and top["score"] >= s["review_threshold"]:
        status = "needs_review"
    elif searched and not errors:
        status = "not_found"
    else:
        status = "search_unavailable"
    doc = {"id": (prev or {}).get("id") or uid(), "business_id": b["id"], "key": key, "status": status,
           "chosen_url": (top.get("final_url") or top["url"]) if status == "found" else None,
           "chosen_domain": top["domain"] if status == "found" else None,
           "confidence": top["score"] if top else 0,
           "source": ",".join(top["providers"]) if top else None,
           "candidates": [{k: c.get(k) for k in ("domain", "url", "final_url", "providers", "score", "signals", "listing")} for c in checked[:6]],
           "tiers": tiers, "queries": queries, "errors": errors, "rejected_domains": sorted(rejected), "stale": False,
           "searched_at": iso()}
    await db.website_lookups.update_one({"business_id": b["id"]}, {"$set": doc}, upsert=True)
    await audit("website_search", "business", b["id"], {"status": status, "domain": doc["chosen_domain"],
                                                        "confidence": doc["confidence"], "tiers": tiers})
    msg = {"found": f"Website found: {doc['chosen_domain']} (confidence {doc['confidence']})",
           "needs_review": f"Possible website {top['domain'] if top else ''} needs manual check (confidence {doc['confidence']})",
           "not_found": "No website found after searching Google" + (" and Brave" if "brave" in tiers else ""),
           "search_unavailable": "Website search unavailable" + (f": {errors[0]}" if errors else " (no search API key set)")}[status]
    await activity("website_search", msg, b, sid, "success" if status == "found" else "warn", slot=slot)
    return doc


async def apply_found(b, url, source, confidence, actor="agent"):
    dom = norm_domain(url)
    upd = {"website": url, "domain": dom, "website_source": source, "website_confidence": confidence,
           "website_found_at": iso()}
    sib = await db.businesses.find_one({"domain": dom, "id": {"$ne": b["id"]}}, {"_id": 0, "id": 1, "parent_group": 1})
    if sib:
        upd["parent_group"] = sib.get("parent_group") or sib["id"]
        await db.businesses.update_one({"id": sib["id"]}, {"$set": {"parent_group": upd["parent_group"]}})
    await db.businesses.update_one({"id": b["id"]}, {"$set": upd})
    await audit("website_assigned", "business", b["id"], {"url": url, "source": source, "confidence": confidence}, actor)
    b.update(upd)
    return b
