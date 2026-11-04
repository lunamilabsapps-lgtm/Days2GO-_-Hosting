import asyncio
import sys
from core import db
from website_finder import find_website, apply_found

STATUS_MAP = {"needs_review": "website_unverified", "not_found": "no_website_found"}


async def main(since):
    ls = await db.website_lookups.find({"status": {"$in": ["needs_review", "not_found"]}, "searched_at": {"$lt": since}},
                                       {"_id": 0, "business_id": 1}).to_list(1000)
    n = f = 0
    for lk in ls:
        b = await db.businesses.find_one({"id": lk["business_id"], "website": {"$in": ["", None]}}, {"_id": 0})
        if not b:
            continue
        d = await find_website(b, force=True)
        n += 1
        if d["status"] == "found":
            await apply_found(b, d["chosen_url"], d["source"], d["confidence"])
            f += 1
        if d["status"] == "found" or b.get("website_status") != STATUS_MAP.get(d["status"]):
            await db.businesses.update_one({"id": b["id"]}, {"$set": {"research_status": "refresh_requested", "attempts": 0}})
        print("PROGRESS", n, f, b["name"], d["status"], flush=True)
    print("DONE", n, f, flush=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
