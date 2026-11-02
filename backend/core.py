import os
import re
import uuid
import math
import logging
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from cryptography.fernet import Fernet

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT_DIR / "data")))
SCREENSHOT_DIR = DATA_DIR / "screenshots"
BACKUP_DIR = DATA_DIR / "backups"
for d in (SCREENSHOT_DIR, BACKUP_DIR):
    d.mkdir(parents=True, exist_ok=True)

log = logging.getLogger("scout")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
USER_AGENT = "BrightCodaScout/1.0 (+https://brightcoda.com)"
_fernet = Fernet(os.environ["APP_ENCRYPTION_KEY"].encode())


def now():
    return datetime.now(timezone.utc)


def iso():
    return now().isoformat()


def uid():
    return str(uuid.uuid4())


def encrypt(v: str) -> str:
    return _fernet.encrypt(v.encode()).decode() if v else ""


def decrypt(v: str) -> str:
    try:
        return _fernet.decrypt(v.encode()).decode() if v else ""
    except Exception:
        return ""


def clean(doc):
    if doc is None:
        return None
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def norm_name(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"&", " and ", s)
    s = re.sub(r"\b(pty|ltd|the|co|company|shop|store)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def norm_phone(s: str) -> str:
    d = re.sub(r"\D", "", s or "")
    if d.startswith("61"):
        d = "0" + d[2:]
    return d[-9:] if len(d) >= 9 else d


def norm_domain(url: str) -> str:
    if not url:
        return ""
    u = re.sub(r"^https?://", "", url.strip().lower())
    u = u.split("/")[0].split("?")[0].split(":")[0]
    return u[4:] if u.startswith("www.") else u


def haversine_m(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return 1e9
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


DEFAULT_SETTINGS = {
    "_id": "app",
    "agent_state": "running",
    "sender": {"name": "Bright Coda", "email": "", "reply_to": "", "domain": "", "business_name": "Bright Coda",
               "business_address": "", "abn": "", "website": "https://brightcoda.com", "signature_name": "Leon Duddington",
               "signature_block": "Kind Regards\n\nLeon Duddington\nwww.brightcoda.com\n\nsupport@brightcoda.com\n0405806045",
               "location": "Lilydale, Melbourne", "experience": "20 years in the online tech industry", "mobile": "0405806045"},
    "sending": {"daily_limit": 30, "campaign_limit": 200, "interval_seconds": 180, "hours_start": 9, "hours_end": 17,
                "timezone": "Australia/Melbourne", "weekdays_only": True, "test_mode": True,
                "test_recipient": "delivered@resend.dev"},
    "compliance": {"configured": False, "offer_reviewed": False, "default_basis": "inferred_conspicuous_publication",
                   "allow_personal_addresses": False},
    "scoring": {"weights": {"business_fit": 15, "website_gap": 20, "opportunity": 20, "relevance": 15,
                            "commercial_value": 10, "contact": 10, "confidence": 10},
                "min_grade_for_email": "C"},
    "research": {"reassess_days": 90, "rediscovery_days": 60, "concurrency": 2, "request_delay_seconds": 2,
                 "zone_radius_m": 2500, "ai_model": "claude-opus-5-5", "ai_input_cost_per_mtok": 15.0,
                 "ai_output_cost_per_mtok": 75.0, "screenshots": True},
    "imap": {"enabled": False, "host": "imap.hostinger.com", "port": 993, "username": "", "password": "",
             "folder": "INBOX", "poll_seconds": 120},
    "resend": {"api_key": "", "webhook_secret": ""},
    "overpass_endpoints": ["https://maps.mail.ru/osm/tools/overpass/api/interpreter",
                           "https://overpass-api.de/api/interpreter",
                           "https://overpass.kumi.systems/api/interpreter"],
    "notifications": {"high_quality_prospect": True, "search_completed": True, "campaign_completed": True,
                      "reply": True, "delivery_problem": True, "unsubscribe": True, "research_error": True,
                      "api_failure": True, "backup": True},
    "backups": {"enabled": True, "interval_hours": 24, "keep": 14},
}
SECRET_FIELDS = {("resend", "api_key"), ("resend", "webhook_secret"), ("imap", "password")}


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


async def get_settings():
    doc = await db.settings.find_one({"_id": "app"}) or {}
    s = _merge(DEFAULT_SETTINGS, doc)
    for sec, key in SECRET_FIELDS:
        s[sec][key] = decrypt(s[sec].get(key, ""))
    return s


async def ensure_settings():
    if not await db.settings.find_one({"_id": "app"}):
        await db.settings.insert_one(dict(DEFAULT_SETTINGS))


async def next_seq(name="activity"):
    r = await db.counters.find_one_and_update({"_id": name}, {"$inc": {"v": 1}}, upsert=True, return_document=True)
    return r["v"]


async def activity(kind, message, business=None, search_id=None, level="info", data=None, slot=None):
    doc = {"id": uid(), "seq": await next_seq(), "kind": kind, "message": message, "level": level,
           "search_id": search_id, "slot": slot, "data": data or {}, "created_at": iso()}
    if business:
        doc["business_id"] = business.get("id")
        doc["business_name"] = business.get("name")
    await db.activity.insert_one(doc)
    return doc


async def audit(action, entity, entity_id=None, details=None, actor="agent"):
    await db.audit.insert_one({"id": uid(), "action": action, "entity": entity, "entity_id": entity_id,
                               "details": details or {}, "actor": actor, "created_at": iso()})


async def notify(ntype, title, body="", priority="normal", link=None, data=None):
    s = await get_settings()
    if ntype != "reply" and not s["notifications"].get(ntype, True):
        return
    await db.notifications.insert_one({"id": uid(), "type": ntype, "title": title, "body": body, "priority": priority,
                                       "link": link, "data": data or {}, "read": False, "created_at": iso()})


async def set_current(slot, **fields):
    fields["updated_at"] = iso()
    await db.agent_current.update_one({"_id": f"slot{slot}"}, {"$set": fields}, upsert=True)


async def is_suppressed(email: str, business=None):
    email = (email or "").lower().strip()
    dom = email.split("@")[-1] if "@" in email else ""
    q = [{"value": email}, {"value": dom, "type": "domain"}]
    if business:
        q.append({"type": "business", "value": business.get("id")})
        if business.get("domain"):
            q.append({"type": "domain", "value": business["domain"]})
    return await db.suppressions.find_one({"$or": q}, {"_id": 0})


async def add_suppression(value, stype, reason, source="system"):
    value = (value or "").lower().strip() if stype != "business" else value
    if not value:
        return
    await db.suppressions.update_one({"value": value}, {"$setOnInsert": {
        "id": uid(), "value": value, "type": stype, "reason": reason, "source": source, "created_at": iso()}},
        upsert=True)
    await audit("suppression_added", "suppression", value, {"type": stype, "reason": reason}, source)


async def create_indexes():
    await db.businesses.create_index("id", unique=True)
    await db.businesses.create_index("source_key", unique=True, sparse=True)
    await db.businesses.create_index("domain")
    await db.businesses.create_index("phone_norm")
    await db.businesses.create_index([("zone_id", 1)])
    await db.businesses.create_index([("research_status", 1)])
    await db.zones.create_index([("region_id", 1), ("name", 1)], unique=True)
    await db.coverage.create_index([("zone_id", 1), ("category", 1), ("source", 1)], unique=True)
    await db.regions.create_index("key", unique=True)
    await db.activity.create_index("seq")
    await db.suppressions.create_index("value", unique=True)
    await db.outbound.create_index("message_id", unique=True, sparse=True)
    await db.outbound.create_index("unsub_token", unique=True, sparse=True)
    await db.inbound.create_index("message_id", unique=True, sparse=True)
    await db.webhook_events.create_index("svix_id", unique=True)
    await db.contacts.create_index([("business_id", 1), ("value", 1)], unique=True)
    await db.users.create_index("email", unique=True)
    await db.drafts.create_index("business_id")
