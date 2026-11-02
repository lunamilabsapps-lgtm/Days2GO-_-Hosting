import os
import io
import re
import csv
import json
import asyncio
import bcrypt
import jwt
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Query
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse, Response
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from svix.webhooks import Webhook, WebhookVerificationError
from core import (db, uid, iso, log, clean, get_settings, ensure_settings, create_indexes, audit, notify, activity,
                  encrypt, SECRET_FIELDS, SCREENSHOT_DIR, BACKUP_DIR, add_suppression, USER_AGENT, DEFAULT_SETTINGS)
from discovery import resolve_region, filter_zones, CATEGORY_TAGS, overpass, geocode
from ai import call_ai, parse_json, ai_configured, AIError
from assess import generate_draft, services_catalogue, check_eligibility
from mailer import mark_unsubscribed, process_webhook_event, imap_test, public_url, cancel_followups
from worker import start_worker, run_backup

app = FastAPI(title="Bright Coda Local Business Scout")
api = APIRouter(prefix="/api")
JWT_SECRET = os.environ["JWT_SECRET"]


# ---------- auth ----------
def make_token(email):
    return jwt.encode({"sub": email, "exp": datetime.now(timezone.utc) + timedelta(hours=12)}, JWT_SECRET, algorithm="HS256")


def decode_token(token):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired session")


async def require_admin(request: Request):
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else request.query_params.get("token", "")
    if not token:
        raise HTTPException(401, "Not signed in")
    email = decode_token(token)
    user = await db.users.find_one({"email": email}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(401, "Unknown user")
    return user


class LoginIn(BaseModel):
    email: str
    password: str


@api.post("/auth/login")
async def login(body: LoginIn, request: Request):
    email = body.email.lower().strip()
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "").split(",")[0]
    key = email
    att = await db.login_attempts.find_one({"_id": key}) or {}
    if att.get("locked_until") and att["locked_until"] > iso():
        raise HTTPException(429, "Too many failed attempts. Try again in 15 minutes.")
    user = await db.users.find_one({"email": email})
    if not user or not bcrypt.checkpw(body.password.encode(), user["password_hash"].encode()):
        n = att.get("count", 0) + 1
        upd = {"count": n}
        if n >= 5:
            upd = {"count": 0, "locked_until": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()}
        await db.login_attempts.update_one({"_id": key}, {"$set": upd}, upsert=True)
        raise HTTPException(401, "Incorrect email or password")
    await db.login_attempts.delete_one({"_id": key})
    await audit("login", "user", email, {"ip": ip}, email)
    return {"token": make_token(email), "user": {"email": email, "name": user.get("name")}}


@api.get("/auth/me")
async def me(user=Depends(require_admin)):
    return user


async def seed_admin():
    email = os.environ["ADMIN_EMAIL"].lower()
    pw = os.environ["ADMIN_PASSWORD"]
    u = await db.users.find_one({"email": email})
    if not u:
        await db.users.insert_one({"id": uid(), "email": email, "name": "Administrator", "role": "admin",
                                   "password_hash": bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode(), "created_at": iso()})
    elif not bcrypt.checkpw(pw.encode(), u["password_hash"].encode()):
        await db.users.update_one({"email": email}, {"$set": {"password_hash": bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()}})


CATALOGUE_V2 = [
    {"name": "Starter Website", "pricing": "$249 one-off build", "hosting": "$29/month",
     "description": "A professional, mobile-friendly website for a small business with no website or an outdated one.",
     "features": ["Up to 5 website pages", "Custom graphic design", "Existing logo refresh or update", "Contact form",
                  "Relevant business information", "Services and contact details", "Mobile-friendly design"],
     "delivery_scope": "Up to 5 pages", "terms": ""},
    {"name": "Business Website", "pricing": "$599 one-off build", "hosting": "$29/month",
     "description": "A larger website for businesses that need bookings, galleries and more detailed service pages. Includes everything in Starter.",
     "features": ["Everything in Starter", "Up to 10 website pages", "Additional website sections and pages", "Photo galleries and image sections",
                  "Online booking functionality", "Advanced enquiry forms", "Google Maps integration", "More comprehensive business information and service pages"],
     "delivery_scope": "Up to 10 pages. Larger websites must be quoted separately.", "terms": "Larger websites must be quoted separately."},
    {"name": "AI Business Website", "pricing": "From $1,299 one-off build (final price depends on the complexity of the AI implementation)", "hosting": "$49/month",
     "description": "A business website with an AI chatbot that answers common customer questions and collects enquiries.",
     "features": ["AI chatbot answering common business questions", "Customer enquiry collection", "Business-specific information, services and FAQs",
                  "Enquiry notifications to the business", "Website functionality and design appropriate to the business"],
     "delivery_scope": "Final pricing depends on the complexity of the AI implementation.", "terms": ""},
    {"name": "Ecommerce Website", "pricing": "From $1,999 one-off build (final price depends on the number of products and complexity of the store)",
     "hosting": "Monthly fee quoted according to store size",
     "description": "An online store for retail businesses that want to sell online.",
     "features": ["Online store", "Product listings", "Shopping cart", "Secure checkout", "Payment gateway integration", "Shipping configuration",
                  "Order management", "Mobile-friendly design"],
     "delivery_scope": "Final pricing depends on the number of products and complexity of the store.", "terms": ""},
]


async def ensure_catalogue_v2():
    if await db.services.find_one({"catalogue_version": 2}):
        return
    await db.services.update_many({"archived": {"$ne": True}}, {"$set": {"archived": True, "active": False, "approved": False, "archived_reason": "replaced by approved catalogue v2"}})
    for svc in CATALOGUE_V2:
        await db.services.insert_one({"id": uid(), **svc, "optional_extras": "", "maintenance": "", "approved": True, "active": True,
                                      "catalogue_version": 2, "created_at": iso()})
    await audit("service_catalogue_v2_installed", "service", None, {"count": len(CATALOGUE_V2)})


SEED_SERVICES = [
    ("New business website", "A professional, mobile-friendly website for a business that has no website or only a social media page.",
     ["Up to 5 pages", "Mobile-first design", "Contact details, map and opening hours", "Basic search engine setup"]),
    ("Website redesign", "A modern replacement for an outdated or hard-to-use website.", ["Fresh modern design", "Clearer navigation", "Faster loading"]),
    ("Mobile-friendly upgrade", "Make an existing website work properly on phones.", ["Responsive layout", "Tap-to-call", "Readable text on small screens"]),
    ("Product and service catalogue", "An online showcase of products or services with photos and descriptions.", ["Categorised listings", "Photos", "Easy updates"]),
    ("Online enquiry form", "A structured enquiry form so customers can get in touch any time.", ["Form with email notification", "Spam protection"]),
    ("Online booking", "Let customers book appointments or tables online.", ["Calendar booking", "Confirmation emails"]),
    ("Online ordering", "Let customers place orders online for pickup or delivery.", ["Order form or simple shop", "Order notifications"]),
    ("AI customer assistant", "A website chat assistant that answers common questions.", ["Answers FAQs", "Captures enquiries"]),
    ("Business automation", "Practical automation of repetitive admin tasks.", ["Workflow review", "Simple automations"]),
]


async def seed_services():
    if await db.services.count_documents({}) == 0:
        for name, desc, feats in SEED_SERVICES:
            await db.services.insert_one({"id": uid(), "name": name, "description": desc, "features": feats, "pricing": "",
                                          "delivery_scope": "", "optional_extras": "", "hosting": "", "maintenance": "",
                                          "terms": "", "approved": True, "active": True, "created_at": iso()})


# ---------- dashboard / agent ----------
@api.get("/stats")
async def stats(user=Depends(require_admin)):
    b = db.businesses
    out = await db.outbound.find({"test_mode": False}, {"_id": 0, "status": 1, "events": 1}).to_list(100000)
    cost = await db.ai_usage.aggregate([{"$group": {"_id": None, "c": {"$sum": "$cost_usd_est"}, "n": {"$sum": 1}}}]).to_list(1)
    qualified = await b.count_documents({"grade": {"$in": ["A", "B"]}})
    total_cost = round(cost[0]["c"], 4) if cost else 0
    grades = {g: await b.count_documents({"grade": g}) for g in "ABCD"}
    return {
        "discovered": await b.count_documents({}),
        "assessed": await b.count_documents({"research_status": "assessed"}),
        "with_website": await b.count_documents({"website_status": {"$in": ["website_exists", "under_construction", "website_unavailable"]}}),
        "without_website": await b.count_documents({"website_status": {"$in": ["no_website", "no_website_listed", "social_media_only"]}}),
        "qualified": qualified, "grades": grades,
        "emails_prepared": await db.drafts.count_documents({"status": {"$nin": ["superseded"]}}),
        "emails_sent": len([o for o in out if o["status"] != "test_dry_run"]),
        "emails_delivered": len([o for o in out if any(e["type"] == "delivered" for e in o.get("events", []))]),
        "replies": await db.inbound.count_documents({"kind": "reply"}),
        "unsubscribes": await db.suppressions.count_documents({"reason": "unsubscribed"}),
        "awaiting_review": await db.drafts.count_documents({"status": "pending_approval"}),
        "test_sends": await db.outbound.count_documents({"test_mode": True}),
        "zones_total": await db.zones.count_documents({}), "zones_searched": await db.coverage.count_documents({"status": "completed"}),
        "ai_cost_usd": total_cost, "ai_calls": cost[0]["n"] if cost else 0,
        "cost_per_qualified_lead": round(total_cost / qualified, 4) if qualified else None,
        "unread_notifications": await db.notifications.count_documents({"read": False}),
        "unhandled_replies": await db.inbound.count_documents({"kind": "reply", "handled": {"$ne": True}}),
    }


async def agent_state_doc():
    s = await get_settings()
    hb = await db.worker_health.find_one({"_id": "worker"}, {"_id": 0}) or {}
    alive = bool(hb.get("last_heartbeat")) and hb["last_heartbeat"] > (datetime.now(timezone.utc) - timedelta(seconds=40)).isoformat()
    cur = await db.agent_current.find({}, {"_id": 0}).to_list(10)
    active = await db.searches.count_documents({"status": "running"})
    return {"state": s["agent_state"], "worker_alive": alive, "worker": hb, "current": cur, "active_searches": active,
            "test_mode": s["sending"]["test_mode"]}


@api.get("/agent/state")
async def agent_state(user=Depends(require_admin)):
    return await agent_state_doc()


@api.post("/agent/{action}")
async def agent_control(action: str, user=Depends(require_admin)):
    m = {"pause": "paused", "resume": "running", "stop": "stopped"}
    if action not in m:
        raise HTTPException(400, "Unknown action")
    await db.settings.update_one({"_id": "app"}, {"$set": {"agent_state": m[action]}})
    if action == "stop":
        await db.searches.update_many({"status": {"$in": ["running", "paused"]}}, {"$set": {"status": "stopped"}})
    await activity("control", f"Agent {m[action]} by user", level="warn")
    await audit(f"agent_{action}", "agent", None, actor=user["email"])
    return await agent_state_doc()


@api.get("/activity")
async def get_activity(after: int = 0, limit: int = 100, search_id: Optional[str] = None, user=Depends(require_admin)):
    q = {"seq": {"$gt": after}}
    if search_id:
        q["search_id"] = search_id
    docs = await db.activity.find(q, {"_id": 0}).sort("seq", -1).limit(limit).to_list(limit)
    return list(reversed(docs))


@api.get("/stream")
async def stream(request: Request, token: str):
    decode_token(token)
    last = (await db.activity.find_one({}, {"seq": 1}, sort=[("seq", -1)]) or {}).get("seq", 0)

    async def gen():
        nonlocal last
        tick = 0
        while not await request.is_disconnected():
            evs = await db.activity.find({"seq": {"$gt": last}}, {"_id": 0}).sort("seq", 1).limit(100).to_list(100)
            for e in evs:
                last = e["seq"]
                yield f"event: activity\ndata: {json.dumps(e)}\n\n"
            if tick % 2 == 0:
                yield f"event: state\ndata: {json.dumps(await agent_state_doc())}\n\n"
            tick += 1
            await asyncio.sleep(1)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- searches ----------
class ParseIn(BaseModel):
    instruction: str


@api.post("/searches/parse")
async def parse_instruction(body: ParseIn, user=Depends(require_admin)):
    txt = body.instruction.strip()
    res = None
    if ai_configured():
        try:
            res = parse_json(await call_ai("parse", "Extract a business search request for Australia. JSON only.",
                f"""Instruction: "{txt}"
Known categories: {list(CATEGORY_TAGS)}
Return {{"category": "<known category or custom plural noun>", "subcategory": "", "city": "", "state": "<full Australian state name>",
"country": "Australia", "direction": "all|north|south|east|west|inner", "independent_only": false}}""", max_tokens=300))
        except AIError:
            res = None
    if not res:
        m = re.search(r"find\s+(?:all\s+)?(?:independent\s+)?(.+?)\s+in\s+(?:the\s+)?(.+)", txt, re.I)
        if not m:
            raise HTTPException(400, "Could not understand the instruction. Try: 'Find butchers in Melbourne'.")
        area = m.group(2).strip(" .")
        direction = next((d for d in ("north", "south", "east", "west", "inner") if d in area.lower()), "all")
        city = re.sub(r"(?i)^(northern|southern|eastern|western|inner|north|south|east|west)\s+suburbs\s+of\s+", "", area)
        res = {"category": m.group(1).lower(), "subcategory": "", "city": city.title(), "state": "", "country": "Australia", "direction": direction}
    return res


class ResolveIn(BaseModel):
    country: str = "Australia"
    state: str = ""
    city: str
    radius_km: float = 25
    direction: str = "all"


@api.post("/regions/resolve")
async def resolve(body: ResolveIn, user=Depends(require_admin)):
    try:
        region, created = await resolve_region(body.country, body.state, body.city, body.radius_km)
    except Exception as e:
        raise HTTPException(502, f"Could not resolve area: {e}")
    zones = await db.zones.find({"region_id": region["id"]}, {"_id": 0}).sort("distance_km", 1).to_list(5000)
    zones = filter_zones(zones, region, body.direction)
    return {"region": region, "zones": zones, "created": created}


@api.get("/categories")
async def categories(user=Depends(require_admin)):
    custom = await db.searches.distinct("category")
    return sorted(set(list(CATEGORY_TAGS) + [c.lower() for c in custom]))


class SearchIn(BaseModel):
    instruction: str = ""
    region_id: str
    zone_ids: List[str]
    category: str
    subcategory: str = ""
    max_businesses: int = 0
    mode: str = "research"
    force_refresh: bool = False


@api.post("/searches")
async def create_search(body: SearchIn, user=Depends(require_admin)):
    region = await db.regions.find_one({"id": body.region_id}, {"_id": 0})
    if not region or not body.zone_ids:
        raise HTTPException(400, "Resolve an area and select at least one suburb")
    sr = {"id": uid(), "instruction": body.instruction, "region_id": region["id"], "city": region["name"], "state": region["state"],
          "country": region["country"], "category": body.category.strip().lower(), "subcategory": body.subcategory.strip(),
          "zone_ids": body.zone_ids, "zones_done": [], "max_businesses": body.max_businesses, "mode": body.mode,
          "force_refresh": body.force_refresh, "status": "running", "discovery_status": "pending", "stage": "queued",
          "progress": {"zones_total": len(body.zone_ids), "zones_done": 0, "discovered": 0, "new": 0, "duplicates": 0,
                       "assessed": 0, "reused_zones": 0, "zone_errors": 0}, "created_at": iso()}
    await db.searches.insert_one(dict(sr))
    await audit("search_created", "search", sr["id"], {"category": sr["category"], "city": sr["city"], "zones": len(body.zone_ids)}, user["email"])
    await activity("search_started", f"New search queued: {sr['category']} in {sr['city']} ({len(body.zone_ids)} zones)", search_id=sr["id"])
    return sr


@api.get("/searches")
async def list_searches(user=Depends(require_admin)):
    docs = await db.searches.find({}, {"_id": 0, "zone_ids": 0, "zones_done": 0}).sort("created_at", -1).to_list(200)
    for d in docs:
        d["qualified"] = await db.businesses.count_documents({"search_ids": d["id"], "grade": {"$in": ["A", "B"]}})
        d["drafts"] = await db.drafts.count_documents({"business_id": {"$in": await db.businesses.distinct("id", {"search_ids": d["id"]})}, "status": {"$ne": "superseded"}})
    return docs


@api.post("/searches/{sid}/{action}")
async def search_action(sid: str, action: str, user=Depends(require_admin)):
    m = {"pause": {"status": "paused"}, "resume": {"status": "running"}, "stop": {"status": "stopped"},
         "rerun": {"status": "running", "zones_done": [], "discovery_status": "pending", "force_refresh": True,
                   "progress.zones_done": 0}}
    if action not in m:
        raise HTTPException(400, "Unknown action")
    r = await db.searches.update_one({"id": sid}, {"$set": m[action]})
    if not r.matched_count:
        raise HTTPException(404, "Not found")
    await audit(f"search_{action}", "search", sid, actor=user["email"])
    await activity("control", f"Search {action} by user", search_id=sid, level="warn")
    return clean(await db.searches.find_one({"id": sid}, {"zone_ids": 0, "zones_done": 0}))


# ---------- coverage ----------
@api.get("/regions")
async def list_regions(user=Depends(require_admin)):
    regs = await db.regions.find({}, {"_id": 0}).to_list(100)
    for r in regs:
        r["categories"] = sorted({c.split("|")[0] for c in await db.coverage.distinct("category", {"region_id": r["id"]})})
    return regs


@api.get("/coverage")
async def coverage(region_id: str, category: Optional[str] = None, user=Depends(require_admin)):
    s = await get_settings()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=s["research"]["rediscovery_days"])).isoformat()
    zones = await db.zones.find({"region_id": region_id}, {"_id": 0}).to_list(5000)
    cq = {"region_id": region_id}
    if category:
        cq["category"] = {"$regex": f"^{re.escape(category.lower())}"}
    covs = {}
    for c in await db.coverage.find(cq, {"_id": 0, "history": 0, "query": 0}).to_list(20000):
        covs.setdefault(c["zone_id"], []).append(c)
    bq = {"region_id": region_id}
    if category:
        bq["categories"] = category.lower()
    counts = {x["_id"]: x for x in await db.businesses.aggregate([{"$match": bq}, {"$group": {
        "_id": "$zone_id", "n": {"$sum": 1}, "q": {"$sum": {"$cond": [{"$in": ["$grade", ["A", "B"]]}, 1, 0]}}}}]).to_list(5000)}
    for z in zones:
        cs = covs.get(z["id"], [])
        st = "unsearched"
        if any(c["status"] == "searching" for c in cs):
            st = "searching"
        elif any(c["status"] == "needs_research" for c in cs):
            st = "needs_research"
        elif cs and all(c["status"] == "completed" for c in cs):
            st = "needs_research" if any(c.get("last_searched_at", "") < cutoff for c in cs) else "completed"
        z["status"] = st
        z["coverage"] = cs
        z["prospects"] = counts.get(z["id"], {}).get("n", 0)
        z["qualified"] = counts.get(z["id"], {}).get("q", 0)
    return zones


# ---------- prospects ----------
def prospect_query(q, category, city, suburb, website_status, grade, min_score, research_status, email_status, reply_status,
                   campaign_id, search_id, zone_id, discovered_from, discovered_to):
    f = {}
    if q:
        f["name"] = {"$regex": re.escape(q), "$options": "i"}
    if category:
        f["categories"] = category.lower()
    if city:
        f["city"] = {"$regex": f"^{re.escape(city)}$", "$options": "i"}
    if suburb:
        f["suburb"] = {"$regex": re.escape(suburb), "$options": "i"}
    for k, v in (("website_status", website_status), ("grade", grade), ("research_status", research_status),
                 ("email_status", email_status), ("reply_status", reply_status), ("zone_id", zone_id)):
        if v:
            f[k] = v
    if min_score:
        f["score"] = {"$gte": min_score}
    if search_id:
        f["search_ids"] = search_id
    if discovered_from or discovered_to:
        f["discovered_at"] = {k: v for k, v in (("$gte", discovered_from), ("$lte", discovered_to)) if v}
    return f


@api.get("/prospects")
async def list_prospects(q: str = "", category: str = "", city: str = "", suburb: str = "", website_status: str = "", grade: str = "",
                         min_score: int = 0, research_status: str = "", email_status: str = "", reply_status: str = "",
                         campaign_id: str = "", search_id: str = "", zone_id: str = "", discovered_from: str = "", discovered_to: str = "",
                         page: int = 1, page_size: int = 50, sort: str = "discovered_at", user=Depends(require_admin)):
    f = prospect_query(q, category, city, suburb, website_status, grade, min_score, research_status, email_status, reply_status,
                       campaign_id, search_id, zone_id, discovered_from, discovered_to)
    if campaign_id:
        f["id"] = {"$in": await db.drafts.distinct("business_id", {"campaign_id": campaign_id})}
    total = await db.businesses.count_documents(f)
    direction = 1 if sort == "name" else -1
    docs = await db.businesses.find(f, {"_id": 0}).sort(sort, direction).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    return {"total": total, "items": docs}


@api.get("/prospects/export.csv")
async def export_csv(q: str = "", category: str = "", city: str = "", suburb: str = "", website_status: str = "", grade: str = "",
                     min_score: int = 0, research_status: str = "", email_status: str = "", reply_status: str = "",
                     search_id: str = "", user=Depends(require_admin)):
    f = prospect_query(q, category, city, suburb, website_status, grade, min_score, research_status, email_status, reply_status,
                       "", search_id, "", "", "")
    cols = ["name", "category", "address", "suburb", "city", "state", "phone", "primary_email", "website", "website_status",
            "score", "grade", "research_status", "email_status", "reply_status", "follow_up_status", "source", "source_url",
            "parent_group", "discovered_at", "last_assessed_at", "notes"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    async for d in db.businesses.find(f, {"_id": 0}):
        w.writerow([d.get(c, "") if d.get(c) is not None else "" for c in cols])
    await audit("csv_export", "prospects", None, {"filters": {k: v for k, v in f.items() if isinstance(v, str)}}, user["email"])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=prospects.csv"})


@api.get("/prospects/{bid}")
async def prospect_detail(bid: str, user=Depends(require_admin)):
    b = await db.businesses.find_one({"id": bid}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Not found")
    p = {"_id": 0}
    sib = []
    if b.get("parent_group"):
        sib = await db.businesses.find({"parent_group": b["parent_group"], "id": {"$ne": bid}}, {"_id": 0, "id": 1, "name": 1, "address": 1, "suburb": 1}).to_list(50)
    return {"business": b,
            "assessments": await db.assessments.find({"business_id": bid}, p).sort("assessed_at", -1).to_list(20),
            "contacts": await db.contacts.find({"business_id": bid}, p).to_list(50),
            "consent": await db.consent_records.find({"business_id": bid}, p).to_list(20),
            "drafts": await db.drafts.find({"business_id": bid}, p).sort("created_at", -1).to_list(20),
            "outbound": await db.outbound.find({"business_id": bid}, {"_id": 0, "unsub_token": 0}).sort("created_at", -1).to_list(50),
            "inbound": await db.inbound.find({"business_id": bid}, p).sort("received_at", -1).to_list(50),
            "events": await db.discovery_events.find({"business_id": bid}, p).sort("created_at", -1).to_list(50),
            "audit": await db.audit.find({"entity_id": bid}, p).sort("created_at", -1).to_list(50),
            "siblings": sib,
            "suppressed": await db.suppressions.find_one({"type": "business", "value": bid}, p)}


class ProspectPatch(BaseModel):
    notes: Optional[str] = None
    follow_up_status: Optional[str] = None


@api.patch("/prospects/{bid}")
async def patch_prospect(bid: str, body: ProspectPatch, user=Depends(require_admin)):
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    r = await db.businesses.update_one({"id": bid}, {"$set": upd})
    if not r.matched_count:
        raise HTTPException(404, "Not found")
    await audit("prospect_updated", "business", bid, upd, user["email"])
    return clean(await db.businesses.find_one({"id": bid}))


@api.post("/prospects/{bid}/reassess")
async def reassess(bid: str, user=Depends(require_admin)):
    r = await db.businesses.update_one({"id": bid}, {"$set": {"research_status": "refresh_requested", "attempts": 0}})
    if not r.matched_count:
        raise HTTPException(404, "Not found")
    await audit("reassess_requested", "business", bid, actor=user["email"])
    return {"ok": True}


class ExcludeIn(BaseModel):
    reason: str = "manually excluded"
    exclude: bool = True


@api.post("/prospects/{bid}/exclude")
async def exclude(bid: str, body: ExcludeIn, user=Depends(require_admin)):
    b = await db.businesses.find_one({"id": bid}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Not found")
    await db.businesses.update_one({"id": bid}, {"$set": {"excluded": body.exclude, "exclusion_reason": body.reason if body.exclude else None}})
    if body.exclude:
        await add_suppression(bid, "business", body.reason, user["email"])
        await db.drafts.update_many({"business_id": bid, "status": {"$in": ["pending_approval", "approved"]}},
                                    {"$set": {"status": "blocked", "blocked_reason": "business excluded"}})
    else:
        await db.suppressions.delete_one({"type": "business", "value": bid})
        await db.drafts.update_many({"business_id": bid, "status": "blocked", "blocked_reason": "business excluded"},
                                    {"$set": {"status": "pending_approval", "blocked_reason": None}})
    await audit("business_excluded" if body.exclude else "business_unexcluded", "business", bid, {"reason": body.reason}, user["email"])
    return {"ok": True}


class MergeIn(BaseModel):
    keep_id: str
    merge_id: str


@api.post("/prospects/merge")
async def merge(body: MergeIn, user=Depends(require_admin)):
    keep = await db.businesses.find_one({"id": body.keep_id}, {"_id": 0})
    other = await db.businesses.find_one({"id": body.merge_id}, {"_id": 0})
    if not keep or not other or keep["id"] == other["id"]:
        raise HTTPException(400, "Select two different businesses")
    fill = {k: other[k] for k in ("website", "domain", "phone", "phone_norm", "address", "primary_email") if not keep.get(k) and other.get(k)}
    await db.businesses.update_one({"id": keep["id"]}, {"$set": fill, "$addToSet": {"search_ids": {"$each": other.get("search_ids", [])},
                                                                                   "categories": {"$each": other.get("categories", [])},
                                                                                   "merged_ids": other["id"], "alt_source_keys": other.get("source_key")}})
    for coll in ("contacts", "drafts", "assessments", "outbound", "inbound", "discovery_events", "consent_records"):
        await db[coll].update_many({"business_id": other["id"]}, {"$set": {"business_id": keep["id"]}})
    await db.businesses.update_one({"id": other["id"]}, {"$set": {"merged_into": keep["id"], "excluded": True, "research_status": "merged",
                                                                 "source_key": f"merged:{other['source_key']}"}})
    await audit("business_merged", "business", keep["id"], {"merged": other["id"]}, user["email"])
    return {"ok": True}


@api.post("/prospects/{bid}/generate-email")
async def regen_email(bid: str, user=Depends(require_admin)):
    b = await db.businesses.find_one({"id": bid}, {"_id": 0})
    a = await db.assessments.find_one({"business_id": bid}, {"_id": 0}, sort=[("assessed_at", -1)])
    contacts = await db.contacts.find({"business_id": bid, "type": "email"}, {"_id": 0}).to_list(20)
    if not a:
        raise HTTPException(400, "Business has not been assessed yet")
    if not contacts:
        raise HTTPException(400, "No verified public business email found — cannot prepare an email")
    try:
        d = await generate_draft(b, a, contacts, await get_settings(), await services_catalogue())
    except AIError as e:
        raise HTTPException(502, str(e))
    return d


@api.get("/prospects/{bid}/visabal-brief")
async def visabal_brief(bid: str, user=Depends(require_admin)):
    b = await db.businesses.find_one({"id": bid}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Not found")
    a = await db.assessments.find_one({"business_id": bid}, {"_id": 0}, sort=[("assessed_at", -1)])
    if not a:
        raise HTTPException(400, "Business has not been assessed yet")
    f = a.get("features") or {}
    lines = [f"Business name: {b['name']}", f"Website: {b.get('website') or 'No website found'}", f"Category: {b['category']}",
             f"Location: {', '.join(x for x in [b.get('address'), b.get('suburb'), b.get('city'), b.get('state')] if x)}",
             f"Website presence: {a['presence'].replace('_', ' ')} (assessed {a['assessed_at'][:10]})", "", "Website observations:"]
    lines += [f"- {i['issue']} (evidence: {i['evidence']})" for i in a.get("verified_issues", [])] or ["- None verified"]
    missing = [n for n, ok in [("enquiry/contact form", f.get("has_contact_form") or f.get("contact_page_has_form")), ("online booking", f.get("booking_signals")),
                               ("online ordering", f.get("ordering_signals")), ("mobile viewport", f.get("has_viewport_meta")), ("HTTPS", f.get("uses_https"))] if f and not ok]
    lines += ["", "Missing or outdated functionality:"] + ([f"- {m}" for m in missing] or ["- Not determined" if not f else "- None detected"])
    if f.get("copyright_year"):
        lines.append(f"- Footer copyright year: {f['copyright_year']}")
    lines += ["", "Potential improvements:"] + ([f"- {p['improvement']}" for p in a.get("potential_improvements", [])] or ["- None noted"])
    opp = sorted(a.get("opportunities", []), key=lambda o: -(o.get("strength") or 0))
    lines += ["", f"Recommended Bright Coda package: {opp[0]['service_name'] if opp else 'To be decided'}" + (f" - {opp[0]['reason']}" if opp else "")]
    lines += ["", "Supporting research:", f"- Summary: {a.get('summary') or '-'}", f"- Lead score: {a.get('score')} (grade {a.get('grade')})",
              f"- Load time: {a.get('load_ms')} ms" if a.get("load_ms") else "- Load time: n/a", f"- Site builder: {f.get('builder') or 'unknown'}",
              f"- Discovery source: {b.get('source_url') or 'n/a'}"]
    return {"text": "\n".join(lines)}


# ---------- assessments ----------
@api.get("/assessments")
async def list_assessments(presence: str = "", grade: str = "", changed: bool = False, limit: int = 100, user=Depends(require_admin)):
    f = {}
    if presence:
        f["presence"] = presence
    if grade:
        f["grade"] = grade
    if changed:
        f["website_changed"] = True
    docs = await db.assessments.find(f, {"_id": 0, "features": 0}).sort("assessed_at", -1).limit(limit).to_list(limit)
    names = {b["id"]: b for b in await db.businesses.find({"id": {"$in": [d["business_id"] for d in docs]}},
                                                         {"_id": 0, "id": 1, "name": 1, "suburb": 1, "category": 1}).to_list(limit)}
    for d in docs:
        d["business"] = names.get(d["business_id"])
    return docs


@api.get("/screenshots/{name}")
async def get_screenshot(name: str, token: str):
    decode_token(token)
    path = SCREENSHOT_DIR / os.path.basename(name)
    if not path.exists():
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type="image/jpeg")


# ---------- drafts / campaigns ----------
@api.get("/drafts")
async def list_drafts(status: str = "", campaign_id: str = "", user=Depends(require_admin)):
    f = {"status": {"$ne": "superseded"}}
    if status:
        f["status"] = status
    if campaign_id:
        f["campaign_id"] = campaign_id
    docs = await db.drafts.find(f, {"_id": 0}).sort("created_at", -1).to_list(1000)
    bs = {b["id"]: b for b in await db.businesses.find({"id": {"$in": [d["business_id"] for d in docs]}},
                                                      {"_id": 0, "id": 1, "grade": 1, "score": 1, "suburb": 1, "website": 1, "category": 1}).to_list(1000)}
    for d in docs:
        d["business"] = bs.get(d["business_id"])
    return docs


@api.post("/drafts/rewrite-pending")
async def rewrite_pending(user=Depends(require_admin)):
    s, cat, n = await get_settings(), await services_catalogue(), 0
    for d in await db.drafts.find({"status": {"$in": ["pending_approval", "ineligible"]}, "edited": {"$ne": True}}, {"_id": 0}).to_list(500):
        b = await db.businesses.find_one({"id": d["business_id"]}, {"_id": 0})
        a = await db.assessments.find_one({"id": d["assessment_id"]}, {"_id": 0})
        contacts = await db.contacts.find({"business_id": d["business_id"], "type": "email"}, {"_id": 0}).to_list(20)
        if b and a and contacts:
            try:
                await generate_draft(b, a, contacts, s, cat)
                n += 1
            except AIError:
                pass
    await audit("drafts_rewritten", "draft", None, {"count": n}, user["email"])
    return {"rewritten": n}


class DraftPatch(BaseModel):
    subject: str
    body: str


@api.patch("/drafts/{did}")
async def edit_draft(did: str, body: DraftPatch, user=Depends(require_admin)):
    d = await db.drafts.find_one({"id": did}, {"_id": 0})
    if not d or d["status"] in ("sent", "superseded"):
        raise HTTPException(400, "Draft cannot be edited")
    await db.drafts.update_one({"id": did}, {"$set": {"subject": body.subject, "body": body.body, "edited": True,
                                                     "word_count": len(body.body.split())},
                                            "$push": {"history": {"at": iso(), "subject": d["subject"], "body": d["body"]}}})
    await audit("draft_edited", "draft", did, {"business_id": d["business_id"]}, user["email"])
    return clean(await db.drafts.find_one({"id": did}))


@api.post("/drafts/{did}/{action}")
async def draft_action(did: str, action: str, user=Depends(require_admin)):
    d = await db.drafts.find_one({"id": did}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Not found")
    if action == "approve":
        if d["status"] not in ("pending_approval", "rejected"):
            raise HTTPException(400, f"Only eligible drafts can be approved (status: {d['status']})")
        b = await db.businesses.find_one({"id": d["business_id"]}, {"_id": 0})
        c = await db.contacts.find_one({"id": d["contact_id"]}, {"_id": 0})
        a = await db.assessments.find_one({"id": d["assessment_id"]}, {"_id": 0})
        ok, reasons, _ = await check_eligibility(b, c, a, await get_settings())
        if not ok:
            await db.drafts.update_one({"id": did}, {"$set": {"status": "ineligible", "ineligible_reasons": reasons}})
            raise HTTPException(400, "Not eligible: " + "; ".join(reasons))
        await db.drafts.update_one({"id": did}, {"$set": {"status": "approved", "approved_at": iso(), "approved_by": user["email"]}})
        await db.businesses.update_one({"id": d["business_id"]}, {"$set": {"email_status": "approved"}})
    elif action == "reject":
        await db.drafts.update_one({"id": did}, {"$set": {"status": "rejected"}})
    elif action == "unapprove":
        await db.drafts.update_one({"id": did, "status": "approved"}, {"$set": {"status": "pending_approval"}})
    else:
        raise HTTPException(400, "Unknown action")
    await audit(f"draft_{action}", "draft", did, {"business_id": d["business_id"]}, user["email"])
    return clean(await db.drafts.find_one({"id": did}))


class CampaignIn(BaseModel):
    name: str
    draft_ids: List[str] = []
    limit: int = 0
    daily_limit: int = 20
    search_ids: List[str] = []
    followups_enabled: bool = True


class CampaignPatch(BaseModel):
    name: Optional[str] = None
    daily_limit: Optional[int] = None
    search_ids: Optional[List[str]] = None
    followups_enabled: Optional[bool] = None


class ModeIn(BaseModel):
    mode: str
    confirm: bool = False


@api.patch("/campaigns/{cid}")
async def patch_campaign(cid: str, body: CampaignPatch, user=Depends(require_admin)):
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    if "daily_limit" in upd and not (1 <= upd["daily_limit"] <= 500):
        raise HTTPException(400, "Daily limit must be between 1 and 500")
    r = await db.campaigns.update_one({"id": cid}, {"$set": upd})
    if not r.matched_count:
        raise HTTPException(404, "Not found")
    if upd.get("followups_enabled") is False:
        await cancel_followups({"campaign_id": cid}, "follow-ups disabled")
    await audit("campaign_updated", "campaign", cid, upd, user["email"])
    return clean(await db.campaigns.find_one({"id": cid}))


@api.post("/campaigns/{cid}/mode")
async def campaign_mode(cid: str, body: ModeIn, user=Depends(require_admin)):
    if body.mode not in ("review", "autonomous"):
        raise HTTPException(400, "Mode must be review or autonomous")
    if body.mode == "autonomous" and not body.confirm:
        raise HTTPException(400, "Switching to Full Autonomy requires explicit confirmation")
    r = await db.campaigns.update_one({"id": cid}, {"$set": {"mode": body.mode, "mode_changed_at": iso(), "mode_changed_by": user["email"]}})
    if not r.matched_count:
        raise HTTPException(404, "Not found")
    await audit("campaign_mode_changed", "campaign", cid, {"mode": body.mode}, user["email"])
    await activity("control", f"Campaign switched to {'FULL AUTONOMY' if body.mode == 'autonomous' else 'REVIEW MODE'}", level="warn")
    return clean(await db.campaigns.find_one({"id": cid}))


@api.post("/campaigns")
async def create_campaign(body: CampaignIn, user=Depends(require_admin)):
    c = {"id": uid(), "name": body.name, "status": "draft", "limit": body.limit, "sent_count": 0, "created_at": iso(),
         "created_by": user["email"], "mode": "review", "daily_limit": body.daily_limit, "search_ids": body.search_ids,
         "followups_enabled": body.followups_enabled}
    await db.campaigns.insert_one(dict(c))
    r = await db.drafts.update_many({"id": {"$in": body.draft_ids}, "status": {"$in": ["pending_approval", "approved"]}, "campaign_id": None, "kind": {"$ne": "followup"}},
                                    {"$set": {"campaign_id": c["id"]}})
    await audit("campaign_created", "campaign", c["id"], {"drafts": r.modified_count}, user["email"])
    return {**c, "added": r.modified_count}


@api.get("/campaigns")
async def list_campaigns(user=Depends(require_admin)):
    docs = await db.campaigns.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    for c in docs:
        agg = await db.drafts.aggregate([{"$match": {"campaign_id": c["id"]}}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}]).to_list(20)
        c["drafts"] = {x["_id"]: x["n"] for x in agg}
        outs = await db.outbound.find({"campaign_id": c["id"]}, {"_id": 0, "status": 1, "events": 1}).to_list(10000)
        c["delivered"] = len([o for o in outs if any(e["type"] == "delivered" for e in o.get("events", []))])
        c["replies"] = await db.inbound.count_documents({"campaign_id": c["id"], "kind": "reply"})
        c["bounces"] = len([o for o in outs if o["status"] == "bounced"])
        c["opens"] = len([o for o in outs if any(e["type"] == "opened" for e in o.get("events", []))])
        c["positive"] = await db.inbound.count_documents({"campaign_id": c["id"], "kind": "reply", "sentiment": "positive"})
        c["unsubscribes"] = await db.suppressions.count_documents({"reason": "unsubscribed", "value": {"$in": [o.get("to") for o in await db.outbound.find({"campaign_id": c["id"]}, {"to": 1}).to_list(10000)]}})
        c["followups_scheduled"] = await db.outbound.count_documents({"campaign_id": c["id"], "followup_status": {"$in": ["scheduled", "drafted"]}})
        c["followups_sent"] = await db.outbound.count_documents({"campaign_id": c["id"], "kind": "followup"})
        c["next_followup_at"] = (await db.outbound.find_one({"campaign_id": c["id"], "followup_status": "scheduled"}, {"_id": 0, "followup_due_at": 1}, sort=[("followup_due_at", 1)]) or {}).get("followup_due_at")
        from zoneinfo import ZoneInfo
        st = await get_settings()
        day = datetime.now(ZoneInfo(st["sending"]["timezone"])).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
        c["sent_today"] = await db.outbound.count_documents({"campaign_id": c["id"], "created_at": {"$gte": day}, "test_mode": st["sending"]["test_mode"]})
    return docs


@api.get("/campaigns/{cid}/outbound")
async def campaign_outbound(cid: str, user=Depends(require_admin)):
    return await db.outbound.find({"campaign_id": cid}, {"_id": 0, "unsub_token": 0}).sort("created_at", -1).to_list(1000)


@api.post("/campaigns/{cid}/{action}")
async def campaign_action(cid: str, action: str, user=Depends(require_admin)):
    c = await db.campaigns.find_one({"id": cid}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Not found")
    s = await get_settings()
    if action == "approve-all":
        n = 0
        for d in await db.drafts.find({"campaign_id": cid, "status": "pending_approval", "eligible": True}, {"_id": 0}).to_list(1000):
            b = await db.businesses.find_one({"id": d["business_id"]}, {"_id": 0})
            ct = await db.contacts.find_one({"id": d["contact_id"]}, {"_id": 0})
            a = await db.assessments.find_one({"id": d["assessment_id"]}, {"_id": 0})
            ok, reasons, _ = await check_eligibility(b, ct, a, s)
            if ok:
                await db.drafts.update_one({"id": d["id"]}, {"$set": {"status": "approved", "approved_at": iso(), "approved_by": user["email"]}})
                await db.businesses.update_one({"id": d["business_id"]}, {"$set": {"email_status": "approved"}})
                n += 1
            else:
                await db.drafts.update_one({"id": d["id"]}, {"$set": {"status": "ineligible", "ineligible_reasons": reasons}})
        await audit("campaign_batch_approved", "campaign", cid, {"approved": n}, user["email"])
        return {"approved": n}
    m = {"start": "running", "resume": "running", "pause": "paused", "stop": "stopped"}
    if action not in m:
        raise HTTPException(400, "Unknown action")
    if m[action] == "running" and not s["sending"]["test_mode"]:
        missing = [n for n, v in [("compliance settings confirmed", s["compliance"]["configured"]), ("offer catalogue reviewed", s["compliance"]["offer_reviewed"]),
                                  ("Resend API key", s["resend"]["api_key"]), ("sender email", s["sender"]["email"]),
                                  ("business address for sender identification", s["sender"]["business_address"])] if not v]
        if missing:
            raise HTTPException(400, "Setup required before live sending: " + ", ".join(missing))
    await db.campaigns.update_one({"id": cid}, {"$set": {"status": m[action], f"{action}_at": iso()}})
    if action in ("pause", "stop"):
        await cancel_followups({"campaign_id": cid}, f"campaign {m[action]}")
    await audit(f"campaign_{action}", "campaign", cid, {"test_mode": s["sending"]["test_mode"]}, user["email"])
    return clean(await db.campaigns.find_one({"id": cid}))


# ---------- replies / notifications ----------
@api.get("/inbound")
async def list_inbound(kind: str = "", user=Depends(require_admin)):
    f = {"kind": kind} if kind else {}
    docs = await db.inbound.find(f, {"_id": 0}).sort("received_at", -1).to_list(500)
    camps = {c["id"]: c["name"] for c in await db.campaigns.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(500)}
    for d in docs:
        d["campaign_name"] = camps.get(d.get("campaign_id"))
    return docs


@api.post("/inbound/{iid}/handled")
async def inbound_handled(iid: str, user=Depends(require_admin)):
    await db.inbound.update_one({"id": iid}, {"$set": {"handled": True, "handled_at": iso()}})
    return {"ok": True}


@api.get("/notifications")
async def list_notifications(unread: bool = False, user=Depends(require_admin)):
    f = {"read": False} if unread else {}
    return await db.notifications.find(f, {"_id": 0}).sort("created_at", -1).to_list(300)


@api.post("/notifications/read-all")
async def read_all(user=Depends(require_admin)):
    await db.notifications.update_many({"read": False}, {"$set": {"read": True}})
    return {"ok": True}


@api.post("/notifications/{nid}/read")
async def read_one(nid: str, user=Depends(require_admin)):
    await db.notifications.update_one({"id": nid}, {"$set": {"read": True}})
    return {"ok": True}


# ---------- services ----------
class ServiceIn(BaseModel):
    name: str
    description: str = ""
    features: List[str] = []
    pricing: str = ""
    delivery_scope: str = ""
    optional_extras: str = ""
    hosting: str = ""
    maintenance: str = ""
    terms: str = ""
    approved: bool = True
    active: bool = True


@api.get("/services")
async def list_services(user=Depends(require_admin)):
    return await db.services.find({"archived": {"$ne": True}}, {"_id": 0}).sort("created_at", 1).to_list(200)


@api.post("/services")
async def create_service(body: ServiceIn, user=Depends(require_admin)):
    if re.search(r"visabal", body.name + body.description, re.I) and body.approved:
        raise HTTPException(400, "Visabal cannot be approved until its commercial pricing and service details are confirmed")
    doc = {"id": uid(), **body.model_dump(), "created_at": iso()}
    await db.services.insert_one(dict(doc))
    await audit("service_created", "service", doc["id"], {"name": body.name}, user["email"])
    return doc


@api.put("/services/{sid}")
async def update_service(sid: str, body: ServiceIn, user=Depends(require_admin)):
    if re.search(r"visabal", body.name + body.description, re.I) and body.approved:
        raise HTTPException(400, "Visabal cannot be approved until its commercial pricing and service details are confirmed")
    await db.services.update_one({"id": sid}, {"$set": {**body.model_dump(), "updated_at": iso()}})
    await audit("service_updated", "service", sid, {"name": body.name}, user["email"])
    return clean(await db.services.find_one({"id": sid}))


@api.delete("/services/{sid}")
async def archive_service(sid: str, user=Depends(require_admin)):
    await db.services.update_one({"id": sid}, {"$set": {"archived": True, "active": False}})
    await audit("service_archived", "service", sid, actor=user["email"])
    return {"ok": True}


# ---------- settings ----------
def coerce(default, v, k):
    try:
        if isinstance(default, bool):
            if not isinstance(v, bool):
                raise ValueError
            return v
        if isinstance(default, int):
            return int(v)
        if isinstance(default, float):
            return float(v)
        if isinstance(default, dict):
            return {kk: int(vv) for kk, vv in v.items() if kk in default}
        return str(v)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, f"Invalid value for {k}")


def mask(s):
    for sec, key in SECRET_FIELDS:
        v = s[sec].get(key, "")
        s[sec][key] = ""
        s[sec][f"{key}_set"] = bool(v)
        s[sec][f"{key}_hint"] = f"…{v[-4:]}" if v else ""
    return s


@api.get("/settings")
async def read_settings(user=Depends(require_admin)):
    s = mask(await get_settings())
    s.pop("_id", None)
    s["webhook_url"] = f"{public_url()}/api/webhooks/resend"
    s["ai_configured"] = ai_configured()
    return s


@api.put("/settings/{section}")
async def write_settings(section: str, request: Request, user=Depends(require_admin)):
    body = await request.json()
    if section not in ("sender", "sending", "compliance", "scoring", "research", "imap", "resend", "notifications", "backups", "overpass_endpoints"):
        raise HTTPException(400, "Unknown section")
    if section == "overpass_endpoints":
        await db.settings.update_one({"_id": "app"}, {"$set": {"overpass_endpoints": [str(x) for x in body.get("value", []) if x]}})
    else:
        defaults = DEFAULT_SETTINGS[section]
        upd = {}
        for k, v in body.items():
            if k.endswith("_set") or k.endswith("_hint"):
                continue
            if k.startswith("clear_") and (section, k[6:]) in SECRET_FIELDS:
                if v:
                    upd[f"{section}.{k[6:]}"] = ""
                continue
            if k not in defaults:
                raise HTTPException(400, f"Unknown setting: {k}")
            v = coerce(defaults[k], v, k)
            if (section, k) in SECRET_FIELDS:
                if not v:
                    continue
                v = encrypt(v)
            upd[f"{section}.{k}"] = v
        if upd:
            await db.settings.update_one({"_id": "app"}, {"$set": upd})
    await audit("settings_updated", "settings", section, {"keys": [k for k in body if (section, k) not in SECRET_FIELDS]}, user["email"])
    return await read_settings(user)


# ---------- integrations ----------
@api.get("/integrations/status")
async def integrations_status(user=Depends(require_admin)):
    s = await get_settings()
    imap_h = await db.worker_health.find_one({"_id": "imap"}, {"_id": 0}) or {}
    try:
        import playwright  # noqa
        pw = True
    except ImportError:
        pw = False
    last_hook = await db.webhook_events.find_one({}, {"_id": 0, "received_at": 1, "type": 1}, sort=[("received_at", -1)])
    return {"ai": {"configured": ai_configured(), "model": s["research"]["ai_model"]},
            "resend": {"configured": bool(s["resend"]["api_key"]), "sender": s["sender"]["email"], "domain": s["sender"]["domain"]},
            "resend_webhook": {"configured": bool(s["resend"]["webhook_secret"]), "url": f"{public_url()}/api/webhooks/resend", "last_event": last_hook},
            "imap": {"configured": bool(s["imap"]["username"] and s["imap"]["password"]), "enabled": s["imap"]["enabled"], "health": imap_h},
            "overpass": {"configured": True, "endpoints": s["overpass_endpoints"]}, "nominatim": {"configured": True},
            "screenshots": {"configured": pw}}


@api.post("/integrations/test/{name}")
async def integration_test(name: str, user=Depends(require_admin)):
    s = await get_settings()
    try:
        if name == "ai":
            t = await call_ai("test", "Reply with the single word OK.", "Say OK", max_tokens=20)
            msg = f"AI responded: {t.strip()[:40]}"
        elif name == "resend":
            if not s["resend"]["api_key"]:
                raise ValueError("Resend API key not set")
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get("https://api.resend.com/domains", headers={"Authorization": f"Bearer {s['resend']['api_key']}"})
            if r.status_code == 401 and "restricted" in r.text.lower():
                msg = "Key accepted (sending-only key; domain list not permitted)"
            elif r.is_error:
                raise ValueError(f"Resend HTTP {r.status_code}: {r.text[:150]}")
            else:
                doms = [f"{d['name']} ({d['status']})" for d in r.json().get("data", [])]
                msg = "Domains: " + (", ".join(doms) or "none")
        elif name == "imap":
            if not s["imap"]["username"] or not s["imap"]["password"]:
                raise ValueError("IMAP username/password not set")
            await imap_test(s["imap"])
            msg = "Mailbox login successful"
        elif name == "overpass":
            data, ep = await overpass('[out:json][timeout:10];node["shop"="butcher"](around:500,-37.8136,144.9631);out 1;', quick=True)
            msg = f"Overpass OK via {ep}"
        elif name == "nominatim":
            g = await geocode("Melbourne", "Victoria", "Australia")
            msg = f"Geocoded: {g['display_name'][:60]}"
        elif name == "screenshots":
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                br = await p.chromium.launch(args=["--no-sandbox"])
                await br.close()
            msg = "Browser engine available"
        else:
            raise HTTPException(400, "Unknown integration")
        ok = True
    except HTTPException:
        raise
    except Exception as e:
        ok, msg = False, str(e)[:300]
    await audit("integration_tested", "integration", name, {"ok": ok, "message": msg}, user["email"])
    return {"ok": ok, "message": msg}


# ---------- suppressions / audit / reports / backups ----------
class SuppressIn(BaseModel):
    value: str
    type: str = "email"
    reason: str = "manual"


@api.get("/suppressions")
async def list_suppressions(user=Depends(require_admin)):
    docs = await db.suppressions.find({}, {"_id": 0}).sort("created_at", -1).to_list(5000)
    names = {b["id"]: b["name"] for b in await db.businesses.find({"id": {"$in": [d["value"] for d in docs if d["type"] == "business"]}}, {"_id": 0, "id": 1, "name": 1}).to_list(5000)}
    for d in docs:
        d["label"] = names.get(d["value"], d["value"])
    return docs


@api.post("/suppressions")
async def add_supp(body: SuppressIn, user=Depends(require_admin)):
    if body.type not in ("email", "domain"):
        raise HTTPException(400, "Type must be email or domain")
    await add_suppression(body.value, body.type, body.reason, user["email"])
    await cancel_followups({"to": body.value.lower()} if body.type == "email" else {"to": {"$regex": f"@{re.escape(body.value.lower())}$"}}, "suppressed")
    if body.type == "email":
        await db.drafts.update_many({"recipient": body.value.lower(), "status": {"$in": ["pending_approval", "approved"]}},
                                    {"$set": {"status": "blocked", "blocked_reason": "suppressed"}})
    return {"ok": True}


@api.delete("/suppressions/{sid}")
async def remove_supp(sid: str, user=Depends(require_admin)):
    d = await db.suppressions.find_one({"id": sid}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Not found")
    if d["reason"] in ("unsubscribed", "spam complaint"):
        raise HTTPException(400, "Unsubscribes and spam complaints are permanent and cannot be removed")
    await db.suppressions.delete_one({"id": sid})
    await audit("suppression_removed", "suppression", d["value"], d, user["email"])
    return {"ok": True}


@api.get("/audit")
async def get_audit(entity: str = "", limit: int = 300, user=Depends(require_admin)):
    f = {"entity": entity} if entity else {}
    return await db.audit.find(f, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)


@api.get("/reports/costs")
async def cost_report(user=Depends(require_admin)):
    by = await db.ai_usage.aggregate([{"$group": {"_id": "$purpose", "calls": {"$sum": 1}, "cost": {"$sum": "$cost_usd_est"},
                                                  "in": {"$sum": "$input_tokens_est"}, "out": {"$sum": "$output_tokens_est"}}}]).to_list(20)
    by_day = await db.ai_usage.aggregate([{"$group": {"_id": {"$substr": ["$created_at", 0, 10]}, "cost": {"$sum": "$cost_usd_est"}}},
                                          {"$sort": {"_id": 1}}]).to_list(365)
    total = sum(x["cost"] for x in by)
    qualified = await db.businesses.count_documents({"grade": {"$in": ["A", "B"]}})
    assessed = await db.businesses.count_documents({"research_status": "assessed"})
    return {"total_usd": round(total, 4), "by_purpose": by, "by_day": by_day, "qualified": qualified, "assessed": assessed,
            "cost_per_qualified_lead": round(total / qualified, 4) if qualified else None,
            "cost_per_assessment": round(total / assessed, 4) if assessed else None,
            "note": "Costs are estimates based on approximate token counts and the per-million-token prices in Settings."}


@api.get("/reports/searches")
async def search_report(user=Depends(require_admin)):
    out = []
    for sr in await db.searches.find({}, {"_id": 0, "zone_ids": 0, "zones_done": 0}).sort("created_at", -1).to_list(100):
        ids = await db.businesses.distinct("id", {"search_ids": sr["id"]})
        grades = {g: await db.businesses.count_documents({"search_ids": sr["id"], "grade": g}) for g in "ABCD"}
        sent = await db.outbound.count_documents({"business_id": {"$in": ids}, "test_mode": False})
        replies = await db.inbound.count_documents({"business_id": {"$in": ids}, "kind": "reply"})
        cost = await db.ai_usage.aggregate([{"$match": {"business_id": {"$in": ids}}}, {"$group": {"_id": None, "c": {"$sum": "$cost_usd_est"}}}]).to_list(1)
        out.append({**sr, "businesses": len(ids), "grades": grades, "sent": sent, "replies": replies,
                    "ai_cost_usd": round(cost[0]["c"], 4) if cost else 0})
    return out


@api.get("/backups")
async def list_backups(user=Depends(require_admin)):
    h = await db.worker_health.find_one({"_id": "backup"}, {"_id": 0}) or {}
    files = [{"name": f.name, "size_kb": round(f.stat().st_size / 1024), "created": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat()}
             for f in sorted(BACKUP_DIR.glob("backup-*.json.gz"), reverse=True)]
    return {"files": files, "last": h}


@api.post("/backups")
async def create_backup(user=Depends(require_admin)):
    name, counts = await run_backup("manual")
    return {"name": name, "counts": counts}


@api.get("/backups/{name}")
async def download_backup(name: str, token: str):
    decode_token(token)
    p = BACKUP_DIR / os.path.basename(name)
    if not p.exists():
        raise HTTPException(404, "Not found")
    return FileResponse(p, filename=p.name)


# ---------- public endpoints ----------
UNSUB_PAGE = """<html><head><meta name=viewport content="width=device-width"><title>Unsubscribe</title></head>
<body style="font-family:Arial;max-width:520px;margin:60px auto;padding:0 20px;color:#111">{body}</body></html>"""


@api.get("/unsubscribe/{token}", response_class=HTMLResponse)
async def unsubscribe_page(token: str):
    out = await db.outbound.find_one({"unsub_token": token}, {"_id": 0})
    if not out:
        return UNSUB_PAGE.format(body="<h2>Link not recognised</h2><p>This unsubscribe link is invalid.</p>")
    if out.get("test_mode"):
        await audit("test_unsubscribe_clicked", "outbound", out["id"], {"to": out["to"]}, "public")
        return UNSUB_PAGE.format(body="<h2>Test unsubscribe received</h2><p>This was a test-mode email, so the real recipient was not suppressed. The unsubscribe link works.</p>")
    await mark_unsubscribed(out["to"], "unsubscribe_link")
    return UNSUB_PAGE.format(body=f"<h2>You're unsubscribed</h2><p>{out['to']} will not receive any further emails from Bright Coda.</p>")


@api.post("/unsubscribe/{token}")
async def unsubscribe_one_click(token: str):
    out = await db.outbound.find_one({"unsub_token": token}, {"_id": 0})
    if out and not out.get("test_mode"):
        await mark_unsubscribed(out["to"], "one_click")
    return {"ok": True}


@api.post("/webhooks/resend")
async def resend_webhook(request: Request):
    s = await get_settings()
    secret = s["resend"]["webhook_secret"]
    if not secret:
        raise HTTPException(503, "Webhook secret not configured")
    raw = await request.body()
    headers = {k: request.headers[k] for k in ("svix-id", "svix-timestamp", "svix-signature") if k in request.headers}
    try:
        Webhook(secret).verify(raw, headers)
    except WebhookVerificationError:
        raise HTTPException(400, "Invalid signature")
    event = json.loads(raw)
    try:
        await db.webhook_events.insert_one({"svix_id": headers["svix-id"], "type": event.get("type"), "data": event.get("data"),
                                            "received_at": iso()})
    except Exception:
        return {"ok": True, "duplicate": True}
    await process_webhook_event(event)
    return {"ok": True}


@api.get("/health")
async def health():
    hb = await db.worker_health.find_one({"_id": "worker"}, {"_id": 0}) or {}
    return {"ok": True, "worker_heartbeat": hb.get("last_heartbeat")}


app.include_router(api)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    await ensure_settings()
    await create_indexes()
    await seed_admin()
    await seed_services()
    await ensure_catalogue_v2()
    if os.environ.get("RUN_WORKER", "true").lower() == "true":
        app.state.tasks = await start_worker()
