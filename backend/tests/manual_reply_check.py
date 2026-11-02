# Manual check: reply matching via mailer.handle_reply with TEST outbound doc (run from /app/backend)
import asyncio, sys
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from core import db, iso
from mailer import handle_reply


async def main(mode):
    if mode == "setup":
        await db.businesses.insert_one({"id": "TEST_rb", "name": "TEST_Reply Butcher", "source_key": "TEST:rb", "research_status": "assessed", "created_at": iso()})
        await db.drafts.insert_one({"id": "TEST_rd", "business_id": "TEST_rb", "status": "approved", "recipient": "test_reply@example.com", "created_at": iso()})
        out = {"id": "TEST_ro", "business_id": "TEST_rb", "business_name": "TEST_Reply Butcher", "campaign_id": "TEST_rc", "to": "test_reply@example.com",
               "message_id": "<TEST_ro@x>", "test_mode": False, "status": "sent", "events": [], "created_at": iso()}
        await db.outbound.insert_one(dict(out))
        await db.inbound.insert_one({"id": "TEST_ri", "message_id": "<TEST_ri@x>", "from": "test_reply@example.com", "subject": "Re: TEST website",
                                     "received_at": iso(), "kind": "reply", "matched_by": "message_id", "outbound_id": "TEST_ro",
                                     "business_id": "TEST_rb", "business_name": "TEST_Reply Butcher", "campaign_id": "TEST_rc",
                                     "snippet": "TEST: yes interested", "created_at": iso()})
        await handle_reply(out, {"subject": "Re: TEST website"}, "reply")
        b = await db.businesses.find_one({"id": "TEST_rb"}, {"_id": 0})
        d = await db.drafts.find_one({"id": "TEST_rd"}, {"_id": 0})
        n = await db.notifications.find_one({"title": "REPLY from TEST_Reply Butcher"}, {"_id": 0})
        o = await db.outbound.find_one({"id": "TEST_ro"}, {"_id": 0})
        print("reply_status", b["reply_status"], "follow_up", b["follow_up_status"], "draft", d["status"], "outbound", o["status"])
        print("notification", n and n.get("priority"), n and n.get("type"), n)
    else:
        await db.businesses.delete_many({"id": "TEST_rb"})
        for c in ("drafts", "outbound", "inbound", "notifications", "activity"):
            await db[c].delete_many({"$or": [{"business_id": "TEST_rb"}, {"title": {"$regex": "TEST_Reply"}}, {"data.business_id": "TEST_rb"}]})

asyncio.run(main(sys.argv[1]))
