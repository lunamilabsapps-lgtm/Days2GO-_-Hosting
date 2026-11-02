import os
import gzip
import asyncio
from datetime import datetime, timedelta, timezone
from bson import json_util
from core import (db, iso, log, get_settings, activity, audit, notify, set_current, BACKUP_DIR, ensure_settings,
                  create_indexes)
from discovery import search_zone, osm_to_candidate, ingest_candidate
from assess import assess_business
from mailer import send_draft, can_send_now, poll_imap, cancel_followups
from core import is_suppressed

WORKER_ID = os.environ.get("HOSTNAME", "worker")


async def agent_running():
    s = await get_settings()
    return s["agent_state"] == "running", s


async def recover():
    r1 = await db.businesses.update_many({"research_status": "assessing"}, {"$set": {"research_status": "pending"}})
    r2 = await db.coverage.update_many({"status": "searching"}, {"$set": {"status": "needs_research"}})
    await db.agent_current.update_many({}, {"$set": {"stage": "idle", "business": None}})
    if r1.modified_count or r2.modified_count:
        await activity("recovery", f"Recovered after restart: {r1.modified_count} assessment(s) and {r2.modified_count} zone search(es) resumed from last checkpoint", level="warn")


async def discovery_step(s):
    search = await db.searches.find_one({"status": "running", "discovery_status": {"$ne": "completed"}}, {"_id": 0},
                                        sort=[("last_discovery_at", 1), ("created_at", 1)])
    if not search:
        return False
    await db.searches.update_one({"id": search["id"]}, {"$set": {"last_discovery_at": iso()}})
    done = set(search.get("zones_done", []))
    pending = [z for z in search["zone_ids"] if z not in done]
    if not pending or (search.get("max_businesses") and search["progress"]["new"] >= search["max_businesses"]):
        await db.searches.update_one({"id": search["id"]}, {"$set": {"discovery_status": "completed", "discovery_completed_at": iso()}})
        await activity("discovery_done", f"Discovery finished for {search['category']} in {search['city']}", search_id=search["id"], level="success")
        return True
    zone = await db.zones.find_one({"id": pending[0]}, {"_id": 0})
    region = await db.regions.find_one({"id": search["region_id"]}, {"_id": 0})
    cov_key = {"zone_id": zone["id"], "category": search["category"].lower() + (f"|{search['subcategory'].lower()}" if search.get("subcategory") else ""), "source": "openstreetmap"}
    cov = await db.coverage.find_one(cov_key, {"_id": 0})
    cutoff = (datetime.now(timezone.utc) - timedelta(days=s["research"]["rediscovery_days"])).isoformat()
    if cov and cov.get("status") == "completed" and cov.get("last_searched_at", "") > cutoff and not search.get("force_refresh"):
        attached = await db.businesses.update_many({"zone_id": zone["id"], "categories": search["category"]},
                                                   {"$addToSet": {"search_ids": search["id"]}})
        await db.searches.update_one({"id": search["id"]}, {"$addToSet": {"zones_done": zone["id"]},
                                                           "$inc": {"progress.zones_done": 1, "progress.reused_zones": 1}})
        await activity("coverage_reused", f"{zone['name']}: already searched on {cov['last_searched_at'][:10]} — reusing coverage ({attached.modified_count} known businesses)",
                       search_id=search["id"])
        return True
    await db.coverage.update_one(cov_key, {"$set": {"status": "searching", "region_id": region["id"], "zone_name": zone["name"],
                                                    "started_at": iso()}, "$setOnInsert": {"history": []}}, upsert=True)
    await db.searches.update_one({"id": search["id"]}, {"$set": {"current_zone": zone["name"], "stage": "discovering"}})
    await set_current(0, stage="searching", zone=zone["name"], search_id=search["id"], business=None,
                      findings=[], screenshot=None, score=None, grade=None, contact_status=None, email_status=None)
    await activity("searching", f"Searching for {search['category']} in {zone['name']}", search_id=search["id"], slot=0)
    try:
        els, ep, q = await search_zone(search, zone, s["research"]["zone_radius_m"])
    except Exception as e:
        await db.coverage.update_one(cov_key, {"$set": {"status": "needs_research", "error": str(e)[:200], "last_attempt_at": iso()}})
        await db.searches.update_one({"id": search["id"]}, {"$inc": {"progress.zone_errors": 1, "retry_count": 1}})
        await activity("error", f"Search failed for {zone['name']}: {str(e)[:150]} — will retry", search_id=search["id"], level="error")
        if (search.get("retry_count") or 0) > 5:
            await db.searches.update_one({"id": search["id"]}, {"$addToSet": {"zones_done": zone["id"]}, "$set": {"retry_count": 0}})
            await notify("api_failure", "Discovery source failing", str(e)[:200], "high")
        await asyncio.sleep(min(60, 5 * 2 ** min(search.get("retry_count") or 0, 4)))
        return True
    new = dup = 0
    partial = False
    for el in els:
        c = osm_to_candidate(el, zone, region, search["category"])
        await activity("discovered", f"Business discovered: {c['name']}", c, search["id"], data={"source": c["source_url"]}, slot=0)
        res = await ingest_candidate(c, search, zone)
        new += res == "new"
        dup += res == "duplicate"
        if search.get("max_businesses") and search["progress"]["new"] + new >= search["max_businesses"]:
            partial = el is not els[-1]
            break
    await db.coverage.update_one(cov_key, {"$set": {"status": "needs_research" if partial else "completed", "last_searched_at": iso(), "results_count": len(els),
                                                    "new_count": new, "endpoint": ep, "query": q},
                                           "$push": {"history": {"at": iso(), "results": len(els), "new": new, "search_id": search["id"]}}})
    await db.searches.update_one({"id": search["id"]}, {"$addToSet": {"zones_done": zone["id"]}, "$set": {"retry_count": 0},
                                                       "$inc": {"progress.zones_done": 1, "progress.discovered": len(els),
                                                                "progress.new": new, "progress.duplicates": dup}})
    await activity("zone_done", f"{zone['name']} completed: {len(els)} found, {new} new, {dup} duplicates", search_id=search["id"], level="success")
    await asyncio.sleep(s["research"]["request_delay_seconds"])
    return True


async def discovery_loop():
    while True:
        try:
            ok, s = await agent_running()
            if not ok or not await discovery_step(s):
                await asyncio.sleep(4)
        except Exception as e:
            log.exception("discovery loop")
            await activity("error", f"Discovery error: {str(e)[:200]}", level="error")
            await asyncio.sleep(10)


async def research_step(slot, s):
    running = [x["id"] for x in await db.searches.find({"status": "running"}, {"id": 1}).to_list(100)]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=s["research"]["reassess_days"])).isoformat()
    q = {"excluded": False, "$or": [{"research_status": "pending"}, {"research_status": "refresh_requested"},
                                    {"research_status": "assessed", "last_assessed_at": {"$lt": cutoff}}]}
    q["$and"] = [{"$or": [{"search_ids": {"$in": running}}, {"research_status": "refresh_requested"}]}]
    b = await db.businesses.find_one_and_update(q, {"$set": {"research_status": "assessing", "claimed_by": f"{WORKER_ID}:{slot}",
                                                             "claimed_at": iso()}}, sort=[("discovered_at", 1)], projection={"_id": 0})
    if not b:
        return False
    sid = next((x for x in b.get("search_ids", []) if x in running), None)
    search = await db.searches.find_one({"id": sid}, {"_id": 0}) if sid else None
    b["_sid"] = sid
    try:
        await assess_business(b, search, slot)
        if sid:
            await db.searches.update_one({"id": sid}, {"$inc": {"progress.assessed": 1}})
    except Exception as e:
        attempts = (b.get("attempts") or 0) + 1
        st = "failed" if attempts >= 3 else "pending"
        await db.businesses.update_one({"id": b["id"]}, {"$set": {"research_status": st, "attempts": attempts, "last_error": str(e)[:300]}})
        await activity("error", f"Research error on {b['name']}: {str(e)[:150]}" + (" — will retry" if st == "pending" else " — giving up"),
                       b, sid, "error", slot=slot)
        if st == "failed":
            await notify("research_error", f"Research failed: {b['name']}", str(e)[:200])
        await asyncio.sleep(5 * attempts)
    await activity("next", "Moving to next business", b, sid, slot=slot)
    await asyncio.sleep(s["research"]["request_delay_seconds"])
    return True


async def finalize_searches():
    for sr in await db.searches.find({"status": "running", "discovery_status": "completed"}, {"_id": 0}).to_list(50):
        busy = await db.businesses.count_documents({"search_ids": sr["id"], "research_status": {"$in": ["pending", "assessing"]}})
        if busy == 0:
            await db.searches.update_one({"id": sr["id"]}, {"$set": {"status": "completed", "completed_at": iso(), "stage": "completed"}})
            await notify("search_completed", f"Search completed: {sr['category']} in {sr['city']}",
                         f"{sr['progress']['new']} new businesses, {sr['progress']['assessed']} assessed", link="/coverage")
            await audit("search_completed", "search", sr["id"], sr["progress"])
            await activity("search_done", f"Search completed: {sr['category']} in {sr['city']}", search_id=sr["id"], level="success")


async def research_loop(slot):
    await asyncio.sleep(slot * 2)
    while True:
        try:
            ok, s = await agent_running()
            if slot > s["research"]["concurrency"]:
                await asyncio.sleep(10)
                continue
            if not ok or not await research_step(slot, s):
                await set_current(slot, stage="idle", business=None)
                await finalize_searches()
                await asyncio.sleep(4)
        except Exception as e:
            log.exception("research loop")
            await asyncio.sleep(10)


async def recheck_and_approve(d, c, s, actor):
    from assess import check_eligibility
    b = await db.businesses.find_one({"id": d["business_id"]}, {"_id": 0})
    ct = await db.contacts.find_one({"id": d.get("contact_id")}, {"_id": 0})
    a = await db.assessments.find_one({"id": d.get("assessment_id")}, {"_id": 0})
    if not (b and ct and a):
        return False
    ok, reasons, _ = await check_eligibility(b, ct, a, s)
    if ok:
        await db.drafts.update_one({"id": d["id"]}, {"$set": {"status": "approved", "campaign_id": c["id"], "approved_at": iso(), "approved_by": actor}})
        await db.businesses.update_one({"id": d["business_id"]}, {"$set": {"email_status": "approved"}})
        await audit("draft_approve", "draft", d["id"], {"campaign_id": c["id"], "mode": "full_autonomy"}, actor)
    else:
        await db.drafts.update_one({"id": d["id"]}, {"$set": {"status": "ineligible", "eligible": False, "ineligible_reasons": reasons}})
    return ok


async def autonomy_enroll(c, s):
    q = {"status": "pending_approval", "eligible": True, "kind": {"$ne": "followup"}, "$or": [{"campaign_id": None}, {"campaign_id": c["id"]}]}
    if c.get("search_ids"):
        q["business_id"] = {"$in": await db.businesses.distinct("id", {"search_ids": {"$in": c["search_ids"]}})}
    for d in await db.drafts.find(q, {"_id": 0}).sort("created_at", 1).limit(10).to_list(10):
        await recheck_and_approve(d, c, s, "full_autonomy")


async def followup_step(c, s):
    from assess import generate_followup
    due = await db.outbound.find({"campaign_id": c["id"], "followup_status": "scheduled", "followup_due_at": {"$lte": iso()},
                                  "test_mode": s["sending"]["test_mode"]}, {"_id": 0}).limit(5).to_list(5)
    for o in due:
        b = await db.businesses.find_one({"id": o["business_id"]}, {"_id": 0})
        if b.get("reply_status") == "replied" or o.get("status") in ("bounced", "complained", "failed", "replied") or await is_suppressed(o["to"], b):
            await db.outbound.update_one({"id": o["id"]}, {"$set": {"followup_status": "cancelled", "followup_cancel_reason": "not eligible at due time"}})
            continue
        try:
            await generate_followup(o, b, s, c)
            await activity("email", f"Follow-up prepared for {b['name']}" + (" (sending automatically)" if c.get("mode") == "autonomous" else " (awaiting approval)"), b)
        except Exception as e:
            log.warning("followup generation failed: %s", e)


async def bounce_guard(c):
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    recent_bad = await db.outbound.count_documents({"campaign_id": c["id"], "test_mode": False, "status": {"$in": ["bounced", "complained", "failed"]}, "created_at": {"$gte": since}})
    total = await db.outbound.count_documents({"campaign_id": c["id"], "test_mode": False})
    bad = await db.outbound.count_documents({"campaign_id": c["id"], "test_mode": False, "status": {"$in": ["bounced", "complained", "failed"]}})
    if recent_bad >= 3 or (total >= 10 and bad / total > 0.08):
        reason = f"auto-paused: {bad} bounce/complaint/failure out of {total} sent"
        await db.campaigns.update_one({"id": c["id"]}, {"$set": {"status": "paused", "waiting_reason": reason}})
        await cancel_followups({"campaign_id": c["id"]}, "campaign auto-paused")
        await notify("delivery_problem", f"Campaign paused: {c['name']}", reason, "high", link="/campaigns")
        await audit("campaign_auto_paused", "campaign", c["id"], {"reason": reason})
        return True
    return False


async def sender_step():
    s = await get_settings()
    camps = await db.campaigns.find({"status": "running"}, {"_id": 0}).to_list(20)
    if not camps:
        return
    test = s["sending"]["test_mode"]
    if not test:
        missing = [n for n, v in [("compliance settings", s["compliance"]["configured"]), ("offer review", s["compliance"]["offer_reviewed"]),
                                  ("Resend API key", s["resend"]["api_key"]), ("sender email", s["sender"]["email"])] if not v]
        if missing:
            await db.campaigns.update_many({"status": "running"}, {"$set": {"waiting_reason": "setup required: " + ", ".join(missing)}})
            return
    for c in camps:
        if not test and await bounce_guard(c):
            continue
        if c.get("mode") == "autonomous":
            await autonomy_enroll(c, s)
        await followup_step(c, s)
    ok, why = can_send_now(s)
    if not ok:
        await db.campaigns.update_many({"status": "running"}, {"$set": {"waiting_reason": why}})
        return
    from zoneinfo import ZoneInfo
    day = datetime.now(ZoneInfo(s["sending"]["timezone"])).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
    sent_today = await db.outbound.count_documents({"created_at": {"$gte": day}, "test_mode": test})
    if sent_today >= s["sending"]["daily_limit"]:
        await db.campaigns.update_many({"status": "running"}, {"$set": {"waiting_reason": "account daily sending limit reached"}})
        return
    last = await db.outbound.find_one({}, {"_id": 0, "created_at": 1}, sort=[("created_at", -1)])
    if last and datetime.fromisoformat(last["created_at"]) > datetime.now(timezone.utc) - timedelta(seconds=s["sending"]["interval_seconds"]):
        return
    for c in camps:
        if c.get("sent_count", 0) >= min(c.get("limit") or 10**9, s["sending"]["campaign_limit"]):
            await db.campaigns.update_one({"id": c["id"]}, {"$set": {"status": "completed", "completed_at": iso()}})
            await cancel_followups({"campaign_id": c["id"]}, "campaign sending limit reached")
            continue
        camp_today = await db.outbound.count_documents({"campaign_id": c["id"], "created_at": {"$gte": day}, "test_mode": test})
        if camp_today >= int(c.get("daily_limit") or 20):
            await db.campaigns.update_one({"id": c["id"]}, {"$set": {"waiting_reason": f"campaign daily limit reached ({camp_today}/{c.get('daily_limit') or 20})"}})
            continue
        d = await db.drafts.find_one({"campaign_id": c["id"], "status": "approved"}, {"_id": 0}, sort=[("kind", 1), ("approved_at", 1)])
        if not d:
            pending = await db.drafts.count_documents({"campaign_id": c["id"], "status": "pending_approval"})
            fu = await db.outbound.count_documents({"campaign_id": c["id"], "followup_status": {"$in": ["scheduled", "drafted"]}})
            if c.get("mode") != "autonomous" and not pending and not fu:
                await db.campaigns.update_one({"id": c["id"]}, {"$set": {"status": "completed", "completed_at": iso()}})
                await notify("campaign_completed", f"Campaign completed: {c['name']}", f"{c.get('sent_count', 0)} emails sent", link="/campaigns")
            else:
                await db.campaigns.update_one({"id": c["id"]}, {"$set": {"waiting_reason": "waiting for approved emails or follow-ups" if c.get("mode") != "autonomous" else "waiting for new eligible prospects"}})
            continue
        await db.campaigns.update_one({"id": c["id"]}, {"$set": {"waiting_reason": None}})
        await send_draft(d, c, s)
        return


async def sender_loop():
    while True:
        try:
            await sender_step()
        except Exception as e:
            log.exception("sender")
            await notify("api_failure", "Email sending error", str(e)[:200], "high")
            await asyncio.sleep(30)
        await asyncio.sleep(10)


async def imap_loop():
    while True:
        s = await get_settings()
        try:
            n = await poll_imap()
            await db.worker_health.update_one({"_id": "imap"}, {"$set": {"last_poll": iso(), "new": n, "error": None}}, upsert=True)
        except Exception as e:
            prev = await db.worker_health.find_one({"_id": "imap"}) or {}
            await db.worker_health.update_one({"_id": "imap"}, {"$set": {"last_poll": iso(), "error": str(e)[:200]}}, upsert=True)
            if prev.get("error") != str(e)[:200]:
                await notify("api_failure", "Mailbox (IMAP) check failed", str(e)[:200])
        await asyncio.sleep(max(30, int(s["imap"]["poll_seconds"])))


async def run_backup(reason="scheduled"):
    name = f"backup-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json.gz"
    path = BACKUP_DIR / name
    counts = {}
    with gzip.open(path, "wt") as f:
        for coll in sorted(await db.list_collection_names()):
            n = 0
            async for doc in db[coll].find({}):
                f.write(json_util.dumps({"c": coll, "d": doc}) + "\n")
                n += 1
            counts[coll] = n
    s = await get_settings()
    files = sorted(BACKUP_DIR.glob("backup-*.json.gz"))
    for old in files[:-s["backups"]["keep"]]:
        old.unlink()
    await db.worker_health.update_one({"_id": "backup"}, {"$set": {"last_backup": iso(), "file": name}}, upsert=True)
    await audit("backup_created", "backup", name, {"reason": reason, "counts": counts})
    return name, counts


async def backup_loop():
    while True:
        try:
            s = await get_settings()
            h = await db.worker_health.find_one({"_id": "backup"}) or {}
            due = not h.get("last_backup") or datetime.fromisoformat(h["last_backup"]) < datetime.now(timezone.utc) - timedelta(hours=s["backups"]["interval_hours"])
            if s["backups"]["enabled"] and due:
                name, _ = await run_backup()
                await notify("backup", "Database backup created", name)
        except Exception as e:
            log.exception("backup")
        await asyncio.sleep(600)


async def heartbeat_loop():
    while True:
        await db.worker_health.update_one({"_id": "worker"}, {"$set": {"last_heartbeat": iso(), "worker_id": WORKER_ID}}, upsert=True)
        await asyncio.sleep(10)


async def start_worker():
    await ensure_settings()
    await create_indexes()
    await recover()
    await db.worker_health.update_one({"_id": "worker"}, {"$set": {"started_at": iso()}}, upsert=True)
    tasks = [discovery_loop(), sender_loop(), imap_loop(), backup_loop(), heartbeat_loop()] + [research_loop(i + 1) for i in range(4)]
    return [asyncio.create_task(t) for t in tasks]


if __name__ == "__main__":
    async def main():
        await start_worker()
        await asyncio.Event().wait()
    asyncio.run(main())
