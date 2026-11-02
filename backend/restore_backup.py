"""Restore a Bright Coda Scout JSON backup (Settings -> Backups) into the configured MongoDB.
Usage (on the VPS):  docker compose run --rm -v $PWD/migrate:/migrate worker python restore_backup.py /migrate/backup-XXXX.json.gz
"""
import sys
import gzip
import asyncio
from bson import json_util
from core import db

SKIP = {"worker_health", "agent_current", "login_attempts", "users", "counters"}


async def main(path):
    counts = {}
    with gzip.open(path, "rt") as f:
        for line in f:
            row = json_util.loads(line)
            coll, doc = row["c"], row["d"]
            if coll in SKIP:
                continue
            await db[coll].replace_one({"_id": doc["_id"]}, doc, upsert=True)
            counts[coll] = counts.get(coll, 0) + 1
    seq = await db.activity.find_one({}, {"seq": 1}, sort=[("seq", -1)])
    if seq:
        await db.counters.update_one({"_id": "activity"}, {"$max": {"v": seq["seq"]}}, upsert=True)
    for k, v in sorted(counts.items()):
        print(f"{k}: {v}")
    print("Restore complete. Re-enter the Resend key, webhook secret and IMAP password in Integrations "
          "(they were encrypted with the old server's key).")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
