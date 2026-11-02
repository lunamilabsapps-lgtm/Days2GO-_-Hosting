import re
import time
import json
import hashlib
import asyncio
from datetime import datetime, timedelta, timezone
from urllib import robotparser
from urllib.parse import urljoin, urlparse
import httpx
from bs4 import BeautifulSoup
from core import (db, uid, iso, log, USER_AGENT, SCREENSHOT_DIR, get_settings, activity, audit, notify,
                  set_current, is_suppressed, norm_domain)
from ai import call_ai, parse_json, AIError

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
SOCIAL = ("facebook.com", "instagram.com", "linktr.ee", "tiktok.com")
BUILDERS = ("wordpress", "wix", "squarespace", "shopify", "weebly", "godaddy", "webflow", "joomla", "duda")
BOOKING = ("book now", "book online", "booking", "appointment", "reserve", "reservation", "fresha", "timely",
           "calendly", "opentable", "setmore", "square appointments")
ORDERING = ("order online", "add to cart", "add-to-cart", "checkout", "shop now", "woocommerce", "cart",
            "ubereats", "doordash", "menulog", "online store")
FREE_MAIL = ("gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "bigpond.com", "icloud.com", "live.com",
             "optusnet.com.au", "bigpond.net.au", "yahoo.com.au", "outlook.com.au")
ROLE_PREFIX = ("info", "hello", "sales", "contact", "enquiries", "enquiry", "admin", "office", "orders", "shop",
               "bookings", "reception", "team", "mail", "service", "accounts", "support")
NO_SPAM = re.compile(r"(no (unsolicited|marketing|spam|commercial)|do not (send|email) (unsolicited|marketing))", re.I)


async def robots_allowed(url):
    p = urlparse(url)
    rp = robotparser.RobotFileParser()
    try:
        async with httpx.AsyncClient(timeout=10, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as c:
            r = await c.get(f"{p.scheme}://{p.netloc}/robots.txt")
        if r.status_code >= 400:
            return True
        rp.parse(r.text.splitlines())
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        return True


async def fetch(url):
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": USER_AGENT}, follow_redirects=True,
                                 verify=False) as c:
        r = await c.get(url)
    return r, int((time.monotonic() - t0) * 1000)


def extract(html, url):
    soup = BeautifulSoup(html, "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    low = (html or "").lower()
    ltext = text.lower()
    links = [a.get("href", "") for a in soup.find_all("a")]
    meta = lambda n: (soup.find("meta", attrs={"name": n}) or {}).get("content", "") if soup.find("meta", attrs={"name": n}) else ""
    years = [int(y) for y in re.findall(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?(20\d{2}|19\d{2})", low)]
    forms = soup.find_all("form")
    emails = set(EMAIL_RE.findall(" ".join(l[7:] for l in links if l.lower().startswith("mailto:"))))
    emails |= set(EMAIL_RE.findall(text))
    emails = {e.strip(".").lower() for e in emails if not re.search(r"\.(png|jpe?g|gif|webp|svg)$", e, re.I)
              and "example" not in e and "sentry" not in e and "wixpress" not in e}
    return {
        "title": (soup.title.string or "").strip()[:200] if soup.title and soup.title.string else "",
        "meta_description": meta("description")[:300],
        "has_viewport_meta": bool(soup.find("meta", attrs={"name": "viewport"})),
        "h1": [h.get_text(" ", strip=True)[:120] for h in soup.find_all("h1")][:3],
        "word_count": len(text.split()),
        "images": len(soup.find_all("img")),
        "images_missing_alt": len([i for i in soup.find_all("img") if not i.get("alt")]),
        "forms": len(forms),
        "has_contact_form": any(f.find("textarea") for f in forms),
        "tel_links": len([l for l in links if l.lower().startswith("tel:")]),
        "mailto_links": len([l for l in links if l.lower().startswith("mailto:")]),
        "nav_links": len(soup.select("nav a")) or len(soup.select("header a")),
        "booking_signals": [k for k in BOOKING if k in ltext or k in low][:5],
        "ordering_signals": [k for k in ORDERING if k in ltext][:5],
        "social_links": sorted({s for s in SOCIAL for l in links if s in l.lower()}),
        "builder": next((b for b in BUILDERS if b in low), ""),
        "copyright_year": max(years) if years else None,
        "under_construction": bool(re.search(r"under construction|coming soon|site is being built", ltext)),
        "structured_data": "application/ld+json" in low,
        "open_graph": 'property="og:' in low,
        "uses_https": url.startswith("https://"),
        "no_commercial_email_statement": bool(NO_SPAM.search(text)),
        "contact_links": [urljoin(url, l) for l in links if re.search(r"contact|about", l or "", re.I)][:3],
        "emails": sorted(emails)[:10],
        "text_excerpt": text[:2500],
    }


async def screenshot(url, bid):
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None, None
    try:
        async with async_playwright() as p:
            br = await p.chromium.launch(args=["--no-sandbox"])
            pg = await br.new_page(viewport={"width": 1280, "height": 800}, user_agent=USER_AGENT)
            await pg.goto(url, timeout=25000, wait_until="domcontentloaded")
            await pg.wait_for_timeout(1500)
            path = SCREENSHOT_DIR / f"{bid}.jpg"
            await pg.screenshot(path=str(path), type="jpeg", quality=55)
            await pg.set_viewport_size({"width": 390, "height": 844})
            await pg.wait_for_timeout(800)
            m = await pg.evaluate("() => ({sw: document.documentElement.scrollWidth, iw: window.innerWidth})")
            await br.close()
            return f"{bid}.jpg", {"mobile_scroll_width": m["sw"], "mobile_viewport_width": m["iw"],
                                  "mobile_horizontal_overflow": m["sw"] > m["iw"] + 5}
    except Exception as e:
        log.info("screenshot failed %s %s", url, e)
        return None, None


def is_personal(email, business):
    local, _, dom = email.partition("@")
    if local in ROLE_PREFIX or any(local.startswith(r) for r in ROLE_PREFIX):
        return False
    if dom in FREE_MAIL:
        return True
    return bool(re.match(r"^[a-z]+(\.[a-z]+)?$", local)) and local not in norm_domain(business.get("website", ""))


async def save_contacts(b, emails_with_src):
    out = []
    for email, src in emails_with_src:
        dom = email.split("@")[-1]
        biz_dom = b.get("domain") or ""
        c = {"id": uid(), "business_id": b["id"], "type": "email", "value": email, "source_url": src,
             "verified_on_source": True, "role_based": not is_personal(email, b),
             "personal": is_personal(email, b), "matches_business_domain": bool(biz_dom) and dom.endswith(biz_dom),
             "found_at": iso()}
        try:
            await db.contacts.insert_one(dict(c))
        except Exception:
            c = await db.contacts.find_one({"business_id": b["id"], "value": email}, {"_id": 0})
        out.append(c)
    if b.get("phone"):
        try:
            await db.contacts.insert_one({"id": uid(), "business_id": b["id"], "type": "phone", "value": b["phone"],
                                          "source_url": b["source_url"], "verified_on_source": True, "found_at": iso()})
        except Exception:
            pass
    return out


async def services_catalogue():
    return await db.services.find({"approved": True, "active": True}, {"_id": 0}).to_list(100)


ASSESS_SYSTEM = """You are a careful website auditor for Bright Coda, an Australian AI software engineering company.
You assess small local business websites using ONLY the evidence provided (extracted page data). Never invent problems.
A 'verified_issue' must cite concrete evidence from the data. Anything uncertain goes in 'potential_improvements'.
Match opportunities only to the provided approved service catalogue (use service ids). Do not pitch expensive custom
software to a small business that only needs a website. Respond with JSON only."""


def assess_prompt(b, f, cat, extra):
    svc = [{"id": s["id"], "name": s["name"], "description": s.get("description", "")} for s in cat]
    data = {k: v for k, v in f.items() if k not in ("contact_links",)}
    return f"""Business: {b['name']} ({b['category']}) in {b['suburb']}, {b['city']}.
Website: {b['website']}
Extracted page data (homepage): {json.dumps(data)[:6000]}
Technical checks: {json.dumps(extra)}
Approved services: {json.dumps(svc)}

Return JSON:
{{"summary": "2 sentences plain English",
 "quality": {{"visual_design": {{"rating":1-10,"evidence":""}}, "mobile_responsiveness": {{...}}, "loading_performance": {{...}},
   "navigation": {{...}}, "contact_information": {{...}}, "products_services": {{...}}, "calls_to_action": {{...}},
   "booking_enquiry": {{...}}, "online_ordering": {{...}}, "content_quality": {{...}}, "seo_fundamentals": {{...}}, "trust_signals": {{...}}}},
 "verified_issues": [{{"issue":"", "evidence":"", "commercial_impact":""}}],
 "potential_improvements": [{{"improvement":"", "reason":""}}],
 "opportunities": [{{"service_id":"", "service_name":"", "reason":"", "strength":0-100}}],
 "business_fit": 0-100, "commercial_value": 0-100, "confidence": 0-100}}
Use rating null with evidence "not determinable" when the data cannot support a rating.
Be concise: each evidence/reason under 25 words; at most 5 verified_issues, 4 potential_improvements, 3 opportunities.
Output valid compact JSON only, no markdown."""


def presence_from(b, r, f):
    if not b.get("website"):
        return "no_website"
    if norm_domain(b["website"]) in SOCIAL:
        return "social_media_only"
    if r is None or r.status_code >= 400:
        return "website_unavailable"
    if f and (f["under_construction"] or f["word_count"] < 40):
        return "under_construction"
    return "website_exists"


def compute_score(weights, b, a, contacts):
    pres = a["presence"]
    q = [v.get("rating") for v in (a.get("quality") or {}).values() if isinstance(v, dict) and isinstance(v.get("rating"), (int, float))]
    avg_q = sum(q) / len(q) if q else None
    gap = {"no_website": 80, "social_media_only": 85, "website_unavailable": 75, "under_construction": 85}.get(
        pres, round(100 - (avg_q or 5) * 10))
    opp = max([o.get("strength", 0) for o in a.get("opportunities", [])] or [0])
    rel = 100 if any(o.get("service_id") for o in a.get("opportunities", [])) else 30
    emails = [c for c in contacts if c.get("type") == "email"]
    contact = 100 if any(c["role_based"] for c in emails) else 60 if emails else 25 if b.get("phone") else 0
    factors = {"business_fit": a.get("business_fit", 60), "website_gap": gap, "opportunity": opp, "relevance": rel,
               "commercial_value": a.get("commercial_value", 50), "contact": contact, "confidence": a.get("confidence", 50)}
    tw = sum(weights.values()) or 1
    score = round(sum(factors[k] * weights.get(k, 0) for k in factors) / tw)
    score = max(1, min(100, score))
    grade = "A" if score >= 80 else "B" if score >= 65 else "C" if score >= 45 else "D"
    return score, grade, factors


def no_site_assessment(b, pres, note):
    opp = [{"service_id": None, "service_name": "New business website",
            "reason": "No working website was found for this business.", "strength": 60 if pres == "no_website" else 75}]
    return {"summary": note, "quality": {}, "verified_issues": [
        {"issue": {"no_website": "No website listed in the discovery source record",
                   "website_unavailable": "Listed website could not be loaded",
                   "social_media_only": "Business relies on a social media page instead of a website",
                   "under_construction": "Website appears to be under construction or nearly empty"}[pres],
         "evidence": note, "commercial_impact": "Customers searching online may not find key details or be able to enquire easily."}],
        "potential_improvements": [], "opportunities": opp, "business_fit": 65, "commercial_value": 55,
        "confidence": 35 if pres == "no_website" else 60}


async def assess_business(b, search, slot):
    s = await get_settings()
    stage = lambda st, **kw: set_current(slot, stage=st, business=b, search_id=search["id"] if search else None, **kw)
    await stage("opening_website", findings=[], contact_status="pending", score=None, grade=None, email_status="pending", screenshot=None)
    await activity("opening", f"Opening website: {b.get('website') or 'no website listed'}", b, b.get("_sid"), slot=slot)
    r, f, load_ms, extra, shot = None, None, None, {}, None
    pres_note = ""
    if b.get("website") and norm_domain(b["website"]) not in SOCIAL:
        if not await robots_allowed(b["website"]):
            pres_note = "robots.txt disallows automated access; assessment limited to listing data."
            await activity("robots", f"robots.txt disallows access to {b['website']} — respecting it", b, b.get("_sid"), "warn", slot=slot)
        else:
            try:
                r, load_ms = await fetch(b["website"])
                if r.status_code < 400:
                    f = extract(r.text, str(r.url))
                    extra = {"http_status": r.status_code, "load_ms": load_ms, "final_url": str(r.url),
                             "page_kb": round(len(r.content) / 1024)}
                    if s["research"]["screenshots"]:
                        shot, mobile = await screenshot(str(r.url), b["id"])
                        if mobile:
                            extra.update(mobile)
                        await stage("analysing_website", screenshot=shot)
                else:
                    pres_note = f"Website returned HTTP {r.status_code}."
            except Exception as e:
                pres_note = f"Website could not be loaded ({type(e).__name__})."
    pres = presence_from(b, r if f else None, f)
    if pres == "website_exists" and not f:
        pres = "website_unavailable"
    if not pres_note and pres == "no_website":
        pres_note = "The discovery source (OpenStreetMap) lists no website for this business."
    if not pres_note and pres == "social_media_only":
        pres_note = f"Listed web presence is a social media page: {b['website']}"
    # contacts: homepage + contact page
    emails = []
    if f:
        emails += [(e, extra["final_url"]) for e in f["emails"]]
        for cl in f["contact_links"][:1]:
            try:
                if norm_domain(cl) == norm_domain(extra["final_url"]) and await robots_allowed(cl):
                    cr, _ = await fetch(cl)
                    if cr.status_code < 400:
                        cf = extract(cr.text, cl)
                        emails += [(e, cl) for e in cf["emails"]]
                        f["contact_page_has_form"] = cf["has_contact_form"]
                        f["no_commercial_email_statement"] = f["no_commercial_email_statement"] or cf["no_commercial_email_statement"]
            except Exception:
                pass
    if b.get("osm_email"):
        emails.append((b["osm_email"].lower(), b["source_url"]))
    seen, uniq = set(), []
    for e, src in emails:
        if e not in seen:
            seen.add(e)
            uniq.append((e, src))
    await activity("analysing", f"Analysing website ({pres.replace('_', ' ')})", b, b.get("_sid"), slot=slot,
                   data={"load_ms": load_ms, "builder": (f or {}).get("builder")})
    await stage("identifying_opportunities")
    cat = await services_catalogue()
    if f and pres == "website_exists":
        await activity("opportunities", "Identifying opportunities with AI", b, b.get("_sid"), slot=slot)
        a = parse_json(await call_ai("assessment", ASSESS_SYSTEM, assess_prompt(b, f, cat, extra), b["id"], 6000))
    else:
        a = no_site_assessment(b, pres, pres_note)
        ws = next((x for x in cat if "new" in x["name"].lower() and "website" in x["name"].lower()), None)
        if ws:
            a["opportunities"][0].update({"service_id": ws["id"], "service_name": ws["name"]})
    a.update({"id": uid(), "business_id": b["id"], "url": b.get("website") or None,
              "final_url": extra.get("final_url"), "presence": pres, "presence_note": pres_note,
              "http_status": extra.get("http_status"), "load_ms": load_ms, "technical": extra,
              "features": {k: v for k, v in (f or {}).items() if k != "text_excerpt"} if f else None,
              "content_hash": hashlib.sha256((f or {}).get("text_excerpt", "").encode()).hexdigest() if f else None,
              "screenshot": shot, "assessed_at": iso(), "model": s["research"]["ai_model"] if f else None})
    await stage("finding_contacts", findings=[i.get("issue") for i in a.get("verified_issues", [])][:5])
    await activity("contacts", f"Finding contact details: {len(uniq)} email(s) found on public sources", b, b.get("_sid"), slot=slot)
    contacts = await save_contacts(b, uniq)
    contacts = await db.contacts.find({"business_id": b["id"]}, {"_id": 0}).to_list(50)
    score, grade, factors = compute_score(s["scoring"]["weights"], b, a, contacts)
    a.update({"score": score, "grade": grade, "score_factors": factors})
    prev = await db.assessments.find_one({"business_id": b["id"]}, {"_id": 0, "content_hash": 1}, sort=[("assessed_at", -1)])
    a["website_changed"] = bool(prev and prev.get("content_hash") and prev["content_hash"] != a["content_hash"])
    await db.assessments.insert_one(dict(a))
    await db.lead_scores.insert_one({"id": uid(), "business_id": b["id"], "assessment_id": a["id"], "score": score,
                                     "grade": grade, "factors": factors, "weights": s["scoring"]["weights"], "created_at": iso()})
    await db.businesses.update_one({"id": b["id"]}, {"$set": {
        "research_status": "assessed", "website_status": pres, "assessment_id": a["id"], "score": score, "grade": grade,
        "last_assessed_at": iso(), "primary_email": next((c["value"] for c in contacts if c.get("type") == "email" and c.get("role_based")),
                                                         next((c["value"] for c in contacts if c.get("type") == "email"), None))}})
    await audit("website_assessed", "business", b["id"], {"presence": pres, "score": score, "grade": grade})
    email_contacts = [c for c in contacts if c.get("type") == "email"]
    await stage("scoring", score=score, grade=grade,
                contact_status=f"{len(email_contacts)} verified email(s)" if email_contacts else "no public email found")
    await activity("scored", f"Lead score {score} (grade {grade})", b, b.get("_sid"), slot=slot, data={"score": score, "grade": grade})
    if grade == "A":
        await notify("high_quality_prospect", f"Grade A prospect: {b['name']}", f"Score {score} — {b['suburb']}", link=f"/prospects/{b['id']}")
    b = await db.businesses.find_one({"id": b["id"]}, {"_id": 0})
    order = "ABCD"
    if order.index(grade) <= order.index(s["scoring"]["min_grade_for_email"]) and email_contacts:
        await stage("generating_email")
        await activity("email", "Generating personalised email", b, b.get("_sid"), slot=slot)
        d = await generate_draft(b, a, email_contacts, s, cat)
        await stage("checking_eligibility", email_status=d["status"])
        await activity("eligibility", f"Outreach eligibility: {'eligible' if d['eligible'] else 'not eligible'}"
                       + ("" if d["eligible"] else f" ({'; '.join(d['ineligible_reasons'])})"), b, b.get("_sid"), slot=slot)
        mode = (search or {}).get("mode", "research")
        await activity("hold", "Holding email for approval" + (" (research & draft mode)" if mode == "research" else ""),
                       b, b.get("_sid"), slot=slot)
    else:
        reason = "no public business email found" if not email_contacts else f"grade {grade} below threshold"
        await db.businesses.update_one({"id": b["id"]}, {"$set": {"email_status": "no_contact" if not email_contacts else "not_qualified"}})
        await stage("skipping_email", email_status=reason)
        await activity("skip_email", f"No email prepared: {reason}", b, b.get("_sid"), slot=slot)
    return a


EMAIL_SYSTEM = """You write short, genuine outreach emails for Bright Coda (an Australian AI software engineering company
that builds websites and practical software for local businesses). Conversational Australian English, warm, plain
language, no jargon, no hype, no exclamation-mark spam. 100-160 words. Reference ONE specific, verified finding from the
assessment, explain simply why it matters commercially, suggest ONE matching approved service, and end with a friendly
low-pressure call to action. Use only the approved service information provided; never mention prices unless given.
Never invent facts about the business. Do not include an unsubscribe line or signature block (added automatically).
Respond as JSON: {"subject": "", "body": "", "finding_used": "", "service_id": ""}"""


async def generate_draft(b, a, email_contacts, s, cat):
    best = sorted(email_contacts, key=lambda c: (not c.get("role_based"), not c.get("matches_business_domain")))[0]
    prompt = f"""Business: {b['name']} ({b['category']}), {b['suburb']}, {b['city']}.
Website: {b.get('website') or 'none found'} | Presence: {a['presence']}
Assessment summary: {a.get('summary')}
Verified issues: {json.dumps(a.get('verified_issues', []))}
Opportunities: {json.dumps(a.get('opportunities', []))}
Approved services: {json.dumps([{k: x.get(k) for k in ('id','name','description','features','pricing','delivery_scope')} for x in cat])}
Sender first name for sign-off: {s['sender'].get('signature_name') or s['sender']['name']}"""
    out = parse_json(await call_ai("email", EMAIL_SYSTEM, prompt, b["id"], 1200))
    body = out.get("body", "").strip()
    elig, reasons, consent = await check_eligibility(b, best, a, s)
    d = {"id": uid(), "business_id": b["id"], "business_name": b["name"], "assessment_id": a["id"],
         "subject": out.get("subject", "").strip(), "body": body, "finding_used": out.get("finding_used"),
         "service_id": out.get("service_id"), "recipient": best["value"], "contact_id": best["id"],
         "word_count": len(body.split()), "eligible": elig, "ineligible_reasons": reasons, "consent_id": consent,
         "status": "pending_approval" if elig else "ineligible", "campaign_id": None, "created_at": iso(),
         "approved_at": None, "edited": False, "history": []}
    await db.drafts.update_many({"business_id": b["id"], "status": {"$in": ["pending_approval", "ineligible"]}},
                                {"$set": {"status": "superseded"}})
    await db.drafts.insert_one(dict(d))
    await db.businesses.update_one({"id": b["id"]}, {"$set": {"email_status": "draft", "draft_id": d["id"]}})
    await audit("email_drafted", "draft", d["id"], {"business_id": b["id"], "eligible": elig})
    return d


async def check_eligibility(b, contact, a, s):
    reasons = []
    if b.get("excluded"):
        reasons.append("business is on the exclusion list")
    sup = await is_suppressed(contact["value"], b)
    if sup:
        reasons.append(f"suppressed ({sup['reason']})")
    if not contact.get("verified_on_source"):
        reasons.append("email address not verified from a public source")
    if contact.get("personal") and not s["compliance"]["allow_personal_addresses"]:
        reasons.append("address looks personal, not a business role address")
    if (a.get("features") or {}).get("no_commercial_email_statement"):
        reasons.append("website states it does not want unsolicited commercial email")
    if b.get("reply_status") == "replied":
        reasons.append("business has already replied")
    consent_id = None
    if not reasons:
        consent_id = uid()
        await db.consent_records.insert_one({
            "id": consent_id, "business_id": b["id"], "email": contact["value"],
            "basis": s["compliance"]["default_basis"], "source_url": contact["source_url"],
            "evidence": "Address conspicuously published on the business's own public source; message relates to the "
                        "business's role (website/online presence); no statement refusing commercial email found.",
            "recorded_at": iso()})
    return not reasons, reasons, consent_id


def needs_reassessment(b, days):
    if b.get("research_status") != "assessed" or not b.get("last_assessed_at"):
        return True
    return datetime.fromisoformat(b["last_assessed_at"]) < datetime.now(timezone.utc) - timedelta(days=days)
