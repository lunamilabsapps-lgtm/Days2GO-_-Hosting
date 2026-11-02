"""In-process checks of mailer/worker logic (no real sends): duplicate guard, webhook opened/bounce/complaint,
autonomous follow-up with In-Reply-To headers, handle_reply + sentiment, IMAP reply detection (monkeypatched fetch),
bounce guard. Run: cd /app/backend && /root/.venv/bin/python tests/inprocess_mailer_check.py"""
import asyncio
import copy
import sys
import uuid
from datetime import datetime, timedelta, timezone
from email.message import Message

sys.path.insert(0, "/app/backend")
import mailer  # noqa
import worker  # noqa
from core import db, get_settings  # noqa

TAG = uuid.uuid4().hex[:6]
NOW = lambda: datetime.now(timezone.utc).isoformat()
RES = []


def check(name, cond, extra=""):
    RES.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f" -> {extra}" if extra and not cond else ""))


async def seed(i, email):
    bid, cid, aid, did = (f"TEST_ip{x}{i}_{TAG}" for x in "bcad")
    await db.businesses.insert_one({"id": bid, "name": f"TEST_IP {i} {TAG}", "source_key": f"TEST:{bid}", "category": "butchers",
                                    "excluded": False, "search_ids": [], "categories": ["butchers"], "created_at": NOW()})
    await db.contacts.insert_one({"id": cid, "business_id": bid, "type": "email", "value": email, "verified_on_source": True,
                                  "source_url": "https://example.com", "personal": False})
    await db.assessments.insert_one({"id": aid, "business_id": bid, "features": {}, "assessed_at": NOW()})
    d = {"id": did, "business_id": bid, "business_name": f"TEST_IP {i} {TAG}", "contact_id": cid, "assessment_id": aid,
         "recipient": email, "subject": f"TEST ip {i}", "body": "Hi,\n\nTEST body.", "status": "approved", "eligible": True,
         "created_at": NOW(), "kind": "initial"}
    await db.drafts.insert_one(dict(d))
    return bid, d


class FakeResp:
    is_error = False
    text = ""

    def json(self):
        return {"id": f"TESTres_{uuid.uuid4().hex[:6]}"}


CAPTURED = []


class FakeClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        CAPTURED.append(json)
        return FakeResp()


async def main():
    s = copy.deepcopy(await get_settings())
    s["sending"]["test_mode"] = True
    s["resend"]["api_key"] = ""
    camp = {"id": f"TEST_ipcamp_{TAG}", "name": f"TEST_ip {TAG}", "status": "draft", "mode": "review", "daily_limit": 20, "followups_enabled": True}
    await db.campaigns.insert_one(dict(camp))
    bids = []
    try:
        dup = f"test_ip_{TAG}_dup@example.com"
        bA, dA = await seed("A", dup)
        bB, dB = await seed("B", dup)
        bids += [bA, bB]
        r = await mailer.send_draft(dA, camp, s)
        oA = await db.outbound.find_one({"draft_id": dA["id"]}, {"_id": 0})
        check("dry run status test_dry_run", r == "test_dry_run" and oA["status"] == "test_dry_run", r)
        check("initial followup scheduled", oA["kind"] == "initial" and oA["followup_status"] == "scheduled")
        r = await mailer.send_draft(dB, camp, s)
        dB2 = await db.drafts.find_one({"id": dB["id"]})
        check("duplicate guard blocks", r == "blocked" and dB2["blocked_reason"] == "this address has already been emailed", dB2.get("blocked_reason"))

        # webhook opened
        await db.outbound.update_one({"id": oA["id"]}, {"$set": {"resend_id": f"TESTrid_{TAG}"}})
        await mailer.process_webhook_event({"type": "email.opened", "data": {"email_id": f"TESTrid_{TAG}"}})
        oA = await db.outbound.find_one({"id": oA["id"]}, {"_id": 0})
        check("opened event recorded", any(e["type"] == "opened" for e in oA["events"]) and oA.get("opened"))
        check("opened does not cancel followup", oA["followup_status"] == "scheduled")

        # autonomous follow-up with threading headers
        camp_auto = {**camp, "mode": "autonomous"}
        await db.outbound.update_one({"id": oA["id"]}, {"$set": {"followup_due_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}})
        await worker.followup_step(camp_auto, s)
        fd = await db.drafts.find_one({"parent_outbound_id": oA["id"]}, {"_id": 0})
        check("autonomy followup auto-approved", fd and fd["status"] == "approved" and fd["approved_by"] == "full_autonomy" and fd["subject"].startswith("Re: "), fd)
        check("followup no GST", fd and "GST" not in fd["body"])
        await worker.followup_step(camp_auto, s)
        check("only one followup draft", await db.drafts.count_documents({"parent_outbound_id": oA["id"]}) == 1)
        s_key = copy.deepcopy(s)
        s_key["resend"]["api_key"] = "re_TESTFAKE"
        orig_client = mailer.httpx.AsyncClient
        mailer.httpx.AsyncClient = FakeClient
        try:
            r = await mailer.send_draft(fd, camp_auto, s_key)
        finally:
            mailer.httpx.AsyncClient = orig_client
        p = CAPTURED[-1] if CAPTURED else {}
        h = p.get("headers", {})
        check("followup sent w/ In-Reply-To/References", r == "sent" and h.get("In-Reply-To") == oA["message_id"] and h.get("References") == oA["message_id"], h)
        check("followup goes to test recipient", p.get("to") == [s["sending"]["test_recipient"]], p.get("to"))
        check("reply_to set", p.get("reply_to") == "support@brightcoda.com", p.get("reply_to"))
        check("footer has ABN, no GST", "42 932 842 837" in p.get("text", "") and "GST" not in p.get("text", ""))
        check("parent followup_status sent", (await db.outbound.find_one({"id": oA["id"]}))["followup_status"] == "sent")

        # handle_reply
        bC, dC = await seed("C", f"test_ip_{TAG}_c@example.com")
        bids.append(bC)
        await mailer.send_draft(dC, camp, s)
        oC = await db.outbound.find_one({"draft_id": dC["id"]}, {"_id": 0})
        in_id = f"TEST_in_{TAG}"
        await db.inbound.insert_one({"id": in_id, "business_id": bC, "campaign_id": camp["id"], "kind": "reply", "message_id": f"<TESTin{TAG}>"})
        await mailer.handle_reply(oC, {"subject": "x", "body": "Yes interested, please call me", "inbound_id": in_id}, "reply")
        b = await db.businesses.find_one({"id": bC})
        oC = await db.outbound.find_one({"id": oC["id"]})
        inn = await db.inbound.find_one({"id": in_id})
        n = await db.notifications.find_one({"data.business_id": bC, "type": "reply"})
        check("reply: business replied", b["reply_status"] == "replied")
        check("reply: followup cancelled", oC["followup_status"] == "cancelled")
        check("reply: sentiment positive", inn.get("sentiment") == "positive", inn.get("sentiment"))
        check("reply: urgent notification", n and n.get("priority", n.get("level")) == "urgent", n)

        # IMAP reply detection
        bD, dD = await seed("D", f"test_ip_{TAG}_d@example.com")
        bids.append(bD)
        await mailer.send_draft(dD, camp, s)
        oD = await db.outbound.find_one({"draft_id": dD["id"]}, {"_id": 0})
        msg = Message()
        msg["Message-ID"] = f"<TESTimap{TAG}@example.com>"
        msg["From"] = f"Owner <test_ip_{TAG}_d@example.com>"
        msg["Subject"] = "Re: TEST ip D"
        msg["In-Reply-To"] = oD["message_id"]
        msg["Date"] = "Mon, 02 Nov 2026 10:00:00 +1100"
        msg.set_payload("Sounds good, tell me more about the Starter Website.")
        s_imap = copy.deepcopy(s)
        s_imap["imap"].update(enabled=True, username="dummy", password="dummy")
        og, of = mailer.get_settings, mailer._imap_fetch

        async def fake_gs():
            return s_imap
        mailer.get_settings = fake_gs
        mailer._imap_fetch = lambda cfg, since_days=4: [msg]
        try:
            n1 = await mailer.poll_imap()
            n2 = await mailer.poll_imap()
        finally:
            mailer.get_settings, mailer._imap_fetch = og, of
        inn = await db.inbound.find_one({"message_id": f"<TESTimap{TAG}@example.com>"}, {"_id": 0})
        check("imap: inbound recorded once", n1 == 1 and n2 == 0, (n1, n2))
        check("imap: matched_by message_id", inn and inn["matched_by"] == "message_id" and inn["kind"] == "reply", inn)
        check("imap: business REPLIED", (await db.businesses.find_one({"id": bD}))["reply_status"] == "replied")
        check("imap: followups cancelled", (await db.outbound.find_one({"id": oD["id"]}))["followup_status"] == "cancelled")
        check("imap: sentiment set", inn and (await db.inbound.find_one({"id": inn["id"]})).get("sentiment") in ("positive", "neutral", "negative"))

        # bounce + complaint webhooks on non-test outbound
        for i, typ in (("E", "email.bounced"), ("F", "email.complained")):
            em = f"test_ip_{TAG}_{i.lower()}@example.com"
            bx, dx = await seed(i, em)
            bids.append(bx)
            await mailer.send_draft(dx, camp, s)
            ox = await db.outbound.find_one({"draft_id": dx["id"]}, {"_id": 0})
            await db.outbound.update_one({"id": ox["id"]}, {"$set": {"test_mode": False, "resend_id": f"TESTrid{i}{TAG}"}})
            await mailer.process_webhook_event({"type": typ, "data": {"email_id": f"TESTrid{i}{TAG}", "bounce": {"type": "Permanent"}}})
            ox = await db.outbound.find_one({"id": ox["id"]})
            check(f"{typ}: followup cancelled", ox["followup_status"] == "cancelled", ox["followup_status"])
            check(f"{typ}: suppressed", await db.suppressions.find_one({"value": em}))

        # bounce guard
        bg = {**camp, "id": f"TEST_bg_{TAG}", "status": "running"}
        await db.campaigns.insert_one(dict(bg))
        for k in range(3):
            await db.outbound.insert_one({"id": f"TEST_bgo{k}_{TAG}", "campaign_id": bg["id"], "business_id": bA, "test_mode": False,
                                          "status": "bounced", "created_at": NOW(), "to": f"test_ip_{TAG}_bg{k}@example.com"})
        paused = await worker.bounce_guard(bg)
        c = await db.campaigns.find_one({"id": bg["id"]})
        check("bounce guard auto-pauses", paused and c["status"] == "paused" and "auto-paused" in c["waiting_reason"])
    finally:
        await db.businesses.delete_many({"id": {"$in": bids}})
        for coll in ("contacts", "assessments", "drafts", "outbound", "inbound", "consent_records"):
            await db[coll].delete_many({"business_id": {"$in": bids}})
        await db.outbound.delete_many({"campaign_id": {"$in": [camp["id"], f"TEST_bg_{TAG}"]}})
        await db.campaigns.delete_many({"id": {"$in": [camp["id"], f"TEST_bg_{TAG}"]}})
        await db.suppressions.delete_many({"value": {"$regex": f"test_ip_{TAG}"}})
        await db.notifications.delete_many({"$or": [{"title": {"$regex": TAG}}, {"body": {"$regex": TAG}}, {"data.business_id": {"$in": bids}}]})
    print(f"\nRESULT {sum(ok for _, ok in RES)}/{len(RES)} passed")


asyncio.run(main())
