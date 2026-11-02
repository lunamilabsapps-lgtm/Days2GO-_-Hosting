"""Iteration 2 regression: catalogue v2, sender identity, IMAP security, Visabal brief, campaign mode/daily-limit,
live worker review flow (test mode), follow-up draft/sending, follow-up cancellation, autonomy enroll, unsubscribe,
coverage reuse, analytics. Run with: python -m pytest test_v2_campaigns.py -n0 -v (uses TEST_ data, cleans up)."""
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

from conftest import BASE_URL

TAG = uuid.uuid4().hex[:6]
NOW = lambda: datetime.now(timezone.utc).isoformat()
SRCH = f"TEST_srch_{TAG}"
ST = {}


def seed_one(mdb, i, search_ids=None, email=None):
    bid, cid, aid, did = (f"TEST_{x}{i}_{TAG}" for x in "bcad")
    email = email or f"test_{TAG}_{i}@example.com"
    mdb.businesses.insert_one({"id": bid, "name": f"TEST_V2 Biz {i} {TAG}", "source_key": f"TEST:{bid}", "category": "butchers",
                               "suburb": "TESTville", "city": "Melbourne", "state": "VIC", "research_status": "assessed", "grade": "A",
                               "score": 80, "search_ids": search_ids or [], "categories": ["butchers"], "excluded": False,
                               "website": f"https://test{i}-{TAG}.example.com", "created_at": NOW(), "discovered_at": NOW()})
    mdb.contacts.insert_one({"id": cid, "business_id": bid, "type": "email", "value": email, "verified_on_source": True,
                             "source_url": "https://example.com/contact", "personal": False})
    mdb.assessments.insert_one({"id": aid, "business_id": bid, "features": {"has_viewport_meta": True, "uses_https": False},
                                "assessed_at": NOW(), "grade": "A", "score": 80, "presence": "has_website",
                                "verified_issues": [{"issue": "No HTTPS", "evidence": "http:// only"}],
                                "potential_improvements": [{"improvement": "Add enquiry form"}],
                                "opportunities": [{"service_name": "Starter Website", "reason": "basic site", "strength": 5}],
                                "summary": "TEST summary"})
    mdb.drafts.insert_one({"id": did, "business_id": bid, "business_name": f"TEST_V2 Biz {i} {TAG}", "contact_id": cid,
                           "assessment_id": aid, "recipient": email, "subject": f"TEST subject {i}",
                           "body": "Hi team,\n\nTEST body text about a Starter Website for $249 one-off plus $29/month.",
                           "status": "pending_approval", "eligible": True, "created_at": NOW(), "campaign_id": None, "kind": "initial"})
    return {"bid": bid, "cid": cid, "aid": aid, "did": did, "email": email}


@pytest.fixture(scope="module", autouse=True)
def env(client, mdb):
    orig = client.get(f"{BASE_URL}/api/settings").json()["sending"]
    ST["orig_sending"] = orig
    r = client.put(f"{BASE_URL}/api/settings/sending", json={"test_mode": True, "hours_start": 0, "hours_end": 24,
                                                               "weekdays_only": False, "interval_seconds": 5})
    assert r.status_code == 200
    ST["seed"] = {i: seed_one(mdb, i) for i in (1, 2)}
    ST["seed"][3] = seed_one(mdb, 3, search_ids=[SRCH])
    yield
    client.put(f"{BASE_URL}/api/settings/sending", json={"test_mode": True, "hours_start": 9, "hours_end": 17,
                                                          "weekdays_only": True, "interval_seconds": 180})
    for c in mdb.campaigns.find({"name": {"$regex": f"^TEST_.*{TAG}"}}):
        client.post(f"{BASE_URL}/api/campaigns/{c['id']}/stop")
    bids = [v["bid"] for v in ST["seed"].values()]
    mdb.businesses.delete_many({"id": {"$in": bids}})
    for coll in ("contacts", "assessments", "drafts", "outbound", "consent_records", "inbound"):
        mdb[coll].delete_many({"business_id": {"$in": bids}})
    mdb.suppressions.delete_many({"value": {"$regex": f"test_{TAG}"}})
    mdb.campaigns.delete_many({"name": {"$regex": f"^TEST_.*{TAG}"}})
    mdb.notifications.delete_many({"$or": [{"title": {"$regex": TAG}}, {"body": {"$regex": TAG}}]})


def wait_for(fn, timeout=60, step=3):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


# ---------- catalogue / identity / imap ----------
def test_services_catalogue_v2(client):
    d = client.get(f"{BASE_URL}/api/services").json()
    names = {x["name"]: x for x in d}
    assert set(names) == {"Starter Website", "Business Website", "AI Business Website", "Ecommerce Website"}
    assert "$249" in names["Starter Website"]["pricing"] and names["Starter Website"]["hosting"] == "$29/month"
    assert "$599" in names["Business Website"]["pricing"] and names["Business Website"]["hosting"] == "$29/month"
    assert "$1,299" in names["AI Business Website"]["pricing"] and names["AI Business Website"]["hosting"] == "$49/month"
    assert "$1,999" in names["Ecommerce Website"]["pricing"] and "quoted" in names["Ecommerce Website"]["hosting"].lower()


def test_sender_identity_and_imap(client):
    s = client.get(f"{BASE_URL}/api/settings").json()
    snd = s["sender"]
    assert snd["name"] == "Leon Duddington" and snd["email"] == "outreach@brightcoda.com"
    assert snd["reply_to"] == "support@brightcoda.com" and snd["abn"] == "42 932 842 837"
    assert snd["business_address"] == "83 Old Gippsland Road, Lilydale, Victoria" and snd["signature_block"]
    im = s["imap"]
    assert im["host"] == "imap.hostinger.com" and int(im["port"]) == 993 and im["security"] == "ssl"
    assert im["username"] == "support@brightcoda.com" and im["password"] == "" and "password_set" in im
    assert s["resend"]["api_key"] == ""


def test_imap_security_save(client):
    before = client.get(f"{BASE_URL}/api/settings").json()["imap"]
    r = client.put(f"{BASE_URL}/api/settings/imap", json={"security": "starttls"})
    assert r.status_code == 200 and r.json()["imap"]["security"] == "starttls"
    assert r.json()["imap"]["password_set"] == before["password_set"]
    r = client.put(f"{BASE_URL}/api/settings/imap", json={"security": "ssl"})
    assert r.json()["imap"]["security"] == "ssl"


# ---------- visabal brief ----------
def test_visabal_brief(client, mdb):
    sd = ST["seed"][1]
    t = client.get(f"{BASE_URL}/api/prospects/{sd['bid']}/visabal-brief").json()["text"]
    for frag in ("Business name: TEST_V2", "Website: https://test1", "Category: butchers", "Location:", "Website observations",
                 "Missing or outdated functionality", "Potential improvements", "Recommended Bright Coda package: Starter Website",
                 "Supporting research"):
        assert frag in t, frag
    bid = f"TEST_un_{TAG}"
    mdb.businesses.insert_one({"id": bid, "name": "TEST_unassessed", "category": "x", "source_key": f"TEST:{bid}"})
    try:
        r = client.get(f"{BASE_URL}/api/prospects/{bid}/visabal-brief")
        assert r.status_code == 400
    finally:
        mdb.businesses.delete_one({"id": bid})
    assert client.get(f"{BASE_URL}/api/prospects/TEST_nope/visabal-brief").status_code == 404


# ---------- campaign create / patch / mode ----------
def test_campaign_create_empty_and_mode(client):
    r = client.post(f"{BASE_URL}/api/campaigns", json={"name": f"TEST_empty_{TAG}", "draft_ids": [], "daily_limit": 7})
    assert r.status_code == 200 and r.json()["daily_limit"] == 7 and r.json()["mode"] == "review" and r.json()["added"] == 0
    cid = r.json()["id"]
    assert client.post(f"{BASE_URL}/api/campaigns/{cid}/mode", json={"mode": "autonomous"}).status_code == 400
    assert client.post(f"{BASE_URL}/api/campaigns/{cid}/mode", json={"mode": "bogus", "confirm": True}).status_code == 400
    r = client.post(f"{BASE_URL}/api/campaigns/{cid}/mode", json={"mode": "autonomous", "confirm": True})
    assert r.status_code == 200 and r.json()["mode"] == "autonomous"
    assert client.post(f"{BASE_URL}/api/campaigns/{cid}/mode", json={"mode": "review"}).json()["mode"] == "review"
    assert client.patch(f"{BASE_URL}/api/campaigns/{cid}", json={"daily_limit": 0}).status_code == 400
    assert client.patch(f"{BASE_URL}/api/campaigns/{cid}", json={"daily_limit": 3}).json()["daily_limit"] == 3
    assert client.patch(f"{BASE_URL}/api/campaigns/TEST_nope", json={"daily_limit": 3}).status_code == 404


# ---------- live worker: review mode, daily limit, follow-ups ----------
def test_review_flow_daily_limit(client, mdb):
    s1, s2 = ST["seed"][1], ST["seed"][2]
    r = client.post(f"{BASE_URL}/api/campaigns", json={"name": f"TEST_review_{TAG}", "draft_ids": [s1["did"], s2["did"]], "daily_limit": 1})
    cid = r.json()["id"]
    ST["review_cid"] = cid
    assert r.json()["added"] == 2
    for d in (s1["did"], s2["did"]):
        assert client.post(f"{BASE_URL}/api/drafts/{d}/approve").status_code == 200
    assert client.post(f"{BASE_URL}/api/campaigns/{cid}/start").json()["status"] == "running"
    outs = wait_for(lambda: client.get(f"{BASE_URL}/api/campaigns/{cid}/outbound").json(), 90)
    assert outs, "no outbound created by worker"
    o = outs[0]
    print("outbound status:", o["status"], o.get("note"))
    assert o["kind"] == "initial" and o["followup_status"] == "scheduled"
    due = datetime.fromisoformat(o["followup_due_at"])
    assert timedelta(days=4.9) < due - datetime.fromisoformat(o["created_at"]) < timedelta(days=9.1)
    time.sleep(25)
    outs = client.get(f"{BASE_URL}/api/campaigns/{cid}/outbound").json()
    assert len(outs) == 1, f"daily limit 1 not enforced: {len(outs)}"
    c = next(x for x in client.get(f"{BASE_URL}/api/campaigns").json() if x["id"] == cid)
    assert "campaign daily limit reached" in (c.get("waiting_reason") or ""), c.get("waiting_reason")
    ST["out1"] = o


def test_followup_generated_and_sent(client, mdb):
    cid, o = ST["review_cid"], ST["out1"]
    mdb.outbound.update_one({"id": o["id"]}, {"$set": {"followup_due_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}})
    fd = wait_for(lambda: mdb.drafts.find_one({"parent_outbound_id": o["id"], "kind": "followup"}, {"_id": 0}), 90)
    assert fd, "no follow-up draft created"
    assert fd["status"] == "pending_approval" and fd["subject"].startswith("Re: ")
    assert "GST" not in fd["body"]
    assert mdb.outbound.find_one({"id": o["id"]})["followup_status"] == "drafted"
    # follow-ups are not limited by campaign daily limit? raise limit so it can be sent
    client.patch(f"{BASE_URL}/api/campaigns/{cid}", json={"daily_limit": 5})
    assert client.post(f"{BASE_URL}/api/drafts/{fd['id']}/approve").status_code == 200
    fo = wait_for(lambda: mdb.outbound.find_one({"draft_id": fd["id"]}, {"_id": 0}), 90)
    assert fo and fo["kind"] == "followup" and fo["followup_status"] == "none"
    assert mdb.outbound.find_one({"id": o["id"]})["followup_status"] == "sent"
    time.sleep(15)
    assert mdb.drafts.count_documents({"parent_outbound_id": o["id"], "kind": "followup"}) == 1


def test_pause_cancels_followups_and_analytics(client, mdb):
    cid = ST["review_cid"]
    wait_for(lambda: mdb.outbound.count_documents({"campaign_id": cid, "kind": "initial"}) >= 2, 60)
    c = next(x for x in client.get(f"{BASE_URL}/api/campaigns").json() if x["id"] == cid)
    for k in ("sent_count", "sent_today", "delivered", "opens", "replies", "positive", "bounces", "unsubscribes",
              "followups_scheduled", "followups_sent"):
        assert k in c, k
    assert c["followups_sent"] == 1 and c["sent_count"] >= 2
    sched = mdb.outbound.count_documents({"campaign_id": cid, "followup_status": "scheduled"})
    assert sched >= 1
    client.post(f"{BASE_URL}/api/campaigns/{cid}/pause")
    assert mdb.outbound.count_documents({"campaign_id": cid, "followup_status": "scheduled"}) == 0
    assert mdb.outbound.count_documents({"campaign_id": cid, "followup_status": "cancelled"}) >= 1


# ---------- autonomy ----------
def test_autonomy_enroll_and_send(client, mdb):
    s3 = ST["seed"][3]
    r = client.post(f"{BASE_URL}/api/campaigns", json={"name": f"TEST_auto_{TAG}", "draft_ids": [], "daily_limit": 5, "search_ids": [SRCH]})
    cid = r.json()["id"]
    ST["auto_cid"] = cid
    client.post(f"{BASE_URL}/api/campaigns/{cid}/mode", json={"mode": "autonomous", "confirm": True})
    client.post(f"{BASE_URL}/api/campaigns/{cid}/start")
    d = wait_for(lambda: (lambda x: x if x and x["status"] in ("approved", "sent") else None)(mdb.drafts.find_one({"id": s3["did"]}, {"_id": 0})), 60)
    assert d and d["approved_by"] == "full_autonomy" and d["campaign_id"] == cid
    o = wait_for(lambda: mdb.outbound.find_one({"draft_id": s3["did"]}, {"_id": 0}), 60)
    assert o and o["campaign_id"] == cid
    client.post(f"{BASE_URL}/api/campaigns/{cid}/stop")
    assert mdb.outbound.find_one({"id": o["id"]})["followup_status"] == "cancelled"


# ---------- unsubscribe (non-test outbound) ----------
def test_unsubscribe_non_test_cancels_followups(client, mdb):
    s3 = ST["seed"][3]
    tok = f"TESTtok{TAG}"
    oid = f"TEST_o_{TAG}"
    mdb.outbound.insert_one({"id": oid, "business_id": s3["bid"], "business_name": "TEST", "campaign_id": ST["auto_cid"],
                             "to": s3["email"], "unsub_token": tok, "test_mode": False, "status": "sent", "kind": "initial",
                             "followup_status": "scheduled", "followup_due_at": NOW(), "events": [], "created_at": "2000-01-01T00:00:00+00:00",
                             "message_id": f"<TEST{TAG}@x>"})
    r = requests.get(f"{BASE_URL}/api/unsubscribe/{tok}")
    assert r.status_code == 200 and "unsubscribed" in r.text
    assert mdb.outbound.find_one({"id": oid})["followup_status"] == "cancelled"
    assert mdb.suppressions.find_one({"value": s3["email"]})


# ---------- coverage + stats regression ----------
def test_coverage_and_stats(client):
    regs = client.get(f"{BASE_URL}/api/regions").json()
    mel = next(r for r in regs if r.get("name", "").lower().startswith("melbourne") or r.get("city", "").lower() == "melbourne")
    cov = client.get(f"{BASE_URL}/api/coverage", params={"region_id": mel["id"], "category": "butchers"}).json()
    txt = str(cov)
    assert "completed" in txt
    assert client.get(f"{BASE_URL}/api/stats").status_code == 200
