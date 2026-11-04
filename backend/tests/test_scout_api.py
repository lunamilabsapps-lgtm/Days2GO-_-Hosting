"""Backend regression tests for Bright Coda Local Business Scout (auth, protection, core read APIs, drafts,
campaigns in test mode, services, settings, suppressions, unsubscribe, resend webhook, merge, backups)."""
import base64
import json
import os
import time
import uuid
from datetime import datetime, timezone

import pytest
import requests
from svix.webhooks import Webhook

from conftest import BASE_URL

NOW = lambda: datetime.now(timezone.utc).isoformat()
TAG = uuid.uuid4().hex[:6]


# ---------- TEST seed data (business/contact/assessment/draft) ----------
@pytest.fixture(scope="module")
def seed(mdb):
    ids = {}
    for i in (1, 2):
        bid = f"TEST_b{i}_{TAG}"
        mdb.businesses.insert_one({"id": bid, "name": f"TEST_Biz {i} {TAG}", "source_key": f"TEST:{bid}", "category": "florists",
                                   "suburb": "TESTville", "research_status": "assessed", "grade": "A" if i == 1 else None,
                                   "score": 80, "search_ids": [], "categories": ["florists"], "excluded": False,
                                   "website": "" if i == 1 else f"https://test{i}-{TAG}.example.com",
                                   "phone": "" if i == 1 else "0399990000", "created_at": NOW()})
        cid, aid, did = f"TEST_c{i}_{TAG}", f"TEST_a{i}_{TAG}", f"TEST_d{i}_{TAG}"
        email = f"test_{TAG}_{i}@example.com"
        mdb.contacts.insert_one({"id": cid, "business_id": bid, "type": "email", "value": email, "verified_on_source": True,
                                 "source_url": "https://example.com/contact", "personal": False})
        mdb.assessments.insert_one({"id": aid, "business_id": bid, "features": {}, "assessed_at": NOW(), "grade": "A", "score": 80})
        mdb.drafts.insert_one({"id": did, "business_id": bid, "business_name": f"TEST_Biz {i} {TAG}", "contact_id": cid,
                               "assessment_id": aid, "recipient": email, "subject": "TEST subject", "body": "TEST body text",
                               "status": "pending_approval", "eligible": True, "created_at": NOW()})
        ids[i] = {"bid": bid, "cid": cid, "aid": aid, "did": did, "email": email}
    yield ids
    bids = [v["bid"] for v in ids.values()]
    for coll in ("businesses",):
        mdb[coll].delete_many({"id": {"$in": bids}})
    for coll in ("contacts", "assessments", "drafts", "outbound", "consent_records", "inbound"):
        mdb[coll].delete_many({"business_id": {"$in": bids}})
    mdb.suppressions.delete_many({"value": {"$regex": f"test_{TAG}"}})
    mdb.campaigns.delete_many({"name": {"$regex": "^TEST_"}})
    mdb.services.delete_many({"name": {"$regex": "^TEST_"}})
    mdb.notifications.delete_many({"title": {"$regex": TAG}})


# ---------- auth ----------
class TestAuth:
    def test_login_ok(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]})
        assert r.status_code == 200 and r.json()["token"] and r.json()["user"]["email"] == os.environ["ADMIN_EMAIL"].lower()

    def test_login_wrong(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": f"TEST_wrong_{TAG}@example.com", "password": "x"})
        assert r.status_code == 401

    def test_lockout(self, mdb):
        em = f"test_lock_{TAG}@example.com"
        codes = [requests.post(f"{BASE_URL}/api/auth/login", json={"email": em, "password": "bad"}).status_code for _ in range(6)]
        mdb.login_attempts.delete_many({"_id": {"$regex": f"^{em}"}})
        assert codes[:5] == [401] * 5 and codes[5] == 429, codes

    def test_me(self, client):
        r = client.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 200 and "password_hash" not in r.json()


@pytest.mark.parametrize("path", ["/api/stats", "/api/agent/state", "/api/searches", "/api/prospects", "/api/drafts", "/api/campaigns",
                                  "/api/settings", "/api/suppressions", "/api/audit", "/api/backups", "/api/inbound", "/api/notifications",
                                  "/api/services", "/api/integrations/status", "/api/reports/costs", "/api/coverage", "/api/regions"])
def test_requires_auth(path):
    assert requests.get(f"{BASE_URL}{path}").status_code == 401


def test_public_endpoints():
    assert requests.get(f"{BASE_URL}/api/health").json()["ok"] is True
    assert "not recognised" in requests.get(f"{BASE_URL}/api/unsubscribe/nonexistent").text


# ---------- core read APIs ----------
class TestReads:
    def test_stats(self, client):
        d = client.get(f"{BASE_URL}/api/stats").json()
        assert isinstance(d["discovered"], int) and "assessed" in d

    def test_prospects_and_export(self, client, token):
        r = client.get(f"{BASE_URL}/api/prospects")
        assert r.status_code == 200
        e = requests.get(f"{BASE_URL}/api/prospects/export.csv?token={token}")
        assert e.status_code == 200 and "," in e.text.splitlines()[0]

    def test_parse(self, client):
        r = client.post(f"{BASE_URL}/api/searches/parse", json={"instruction": "Find all florists in Geelong"}, timeout=90)
        assert r.status_code == 200 and "florist" in r.json()["category"].lower() and "geelong" in r.json()["city"].lower()

    def test_costs(self, client):
        d = client.get(f"{BASE_URL}/api/reports/costs").json()
        assert "total_usd" in d and "cost_per_qualified_lead" in d

    def test_activity_and_sse(self, token):
        r = requests.get(f"{BASE_URL}/api/stream?token={token}", stream=True, timeout=15)
        assert r.status_code == 200
        got = b""
        for chunk in r.iter_content(256):
            got += chunk
            if b"event:" in got:
                break
        r.close()
        assert b"event:" in got


# ---------- drafts / campaign (TEST mode) ----------
class TestDraftsCampaign:
    def test_patch_draft(self, client, seed, mdb):
        did = seed[1]["did"]
        r = client.patch(f"{BASE_URL}/api/drafts/{did}", json={"subject": "TEST edited", "body": "TEST edited body"})
        assert r.status_code == 200 and r.json()["subject"] == "TEST edited"
        assert mdb.drafts.find_one({"id": did})["edited"] is True

    def test_ineligible_cannot_approve(self, client, mdb):
        d = mdb.drafts.find_one({"status": "ineligible"})
        if not d:
            pytest.skip("no ineligible draft")
        r = client.post(f"{BASE_URL}/api/drafts/{d['id']}/approve")
        assert r.status_code == 400

    def test_campaign_flow(self, client, seed, mdb):
        orig = client.get(f"{BASE_URL}/api/settings").json()["sending"]
        try:
            client.put(f"{BASE_URL}/api/settings/sending", json={"hours_start": 0, "hours_end": 24, "weekdays_only": False, "interval_seconds": 5})
            c = client.post(f"{BASE_URL}/api/campaigns", json={"name": f"TEST_camp_{TAG}", "draft_ids": [seed[1]["did"]]}).json()
            assert c["added"] == 1
            assert client.post(f"{BASE_URL}/api/campaigns/{c['id']}/approve-all").json()["approved"] == 1
            assert client.post(f"{BASE_URL}/api/campaigns/{c['id']}/start").json()["status"] == "running"
            out = None
            for _ in range(30):
                out = mdb.outbound.find_one({"campaign_id": c["id"]})
                if out:
                    break
                time.sleep(2)
            assert out, "no outbound record created"
            assert out["status"] == "test_dry_run" and out["test_mode"] is True and out["actual_to"] == orig["test_recipient"]
            assert "unsub_token" not in client.get(f"{BASE_URL}/api/campaigns/{c['id']}/outbound").json()[0]
            for a, st in (("pause", "paused"), ("resume", "running"), ("stop", "stopped")):
                assert client.post(f"{BASE_URL}/api/campaigns/{c['id']}/{a}").json()["status"] == st
        finally:
            client.put(f"{BASE_URL}/api/settings/sending", json={k: orig[k] for k in ("hours_start", "hours_end", "weekdays_only", "interval_seconds")})

    def test_live_blocked(self, client, seed):
        c = client.post(f"{BASE_URL}/api/campaigns", json={"name": f"TEST_live_{TAG}", "draft_ids": []}).json()
        try:
            client.put(f"{BASE_URL}/api/settings/sending", json={"test_mode": False})
            r = client.post(f"{BASE_URL}/api/campaigns/{c['id']}/start")
            assert r.status_code == 400 and "Setup required before live sending" in r.json()["detail"]
        finally:
            client.put(f"{BASE_URL}/api/settings/sending", json={"test_mode": True})
        assert client.get(f"{BASE_URL}/api/settings").json()["sending"]["test_mode"] is True

    def test_unsubscribe(self, client, seed, mdb):
        out = mdb.outbound.find_one({"business_id": seed[1]["bid"]})
        if not out:
            pytest.skip("no outbound")
        # pending draft for same recipient to verify blocking
        mdb.drafts.insert_one({"id": f"TEST_dx_{TAG}", "business_id": seed[1]["bid"], "recipient": seed[1]["email"],
                               "status": "pending_approval", "created_at": NOW()})
        r = requests.get(f"{BASE_URL}/api/unsubscribe/{out['unsub_token']}")
        assert r.status_code == 200 and "unsubscribed" in r.text
        assert mdb.businesses.find_one({"id": seed[1]["bid"]})["email_status"] == "unsubscribed"
        assert mdb.drafts.find_one({"id": f"TEST_dx_{TAG}"})["status"] == "blocked"
        sup = [s for s in client.get(f"{BASE_URL}/api/suppressions").json() if s["value"] == seed[1]["email"]]
        assert sup and sup[0]["reason"] == "unsubscribed"
        assert client.delete(f"{BASE_URL}/api/suppressions/{sup[0]['id']}").status_code == 400


# ---------- resend webhook ----------
class TestWebhook:
    def test_webhook(self, client, seed, mdb):
        secret = "whsec_" + base64.b64encode(os.urandom(24)).decode()
        prev = mdb.settings.find_one({"_id": "app"})["resend"].get("webhook_secret", "")
        rid = f"TEST_rid_{TAG}"
        mdb.outbound.insert_one({"id": f"TEST_o_{TAG}", "business_id": seed[2]["bid"], "business_name": "TEST_Biz 2", "campaign_id": "TEST",
                                 "to": seed[2]["email"], "resend_id": rid, "test_mode": False, "status": "sent", "events": [], "created_at": "2000-01-01T00:00:00+00:00"})
        try:
            assert client.put(f"{BASE_URL}/api/settings/resend", json={"webhook_secret": secret}).status_code == 200
            wh = Webhook(secret)
            payload = json.dumps({"type": "email.complained", "created_at": NOW(), "data": {"email_id": rid}})
            mid = f"msg_{TAG}"
            ts = datetime.now(timezone.utc)
            hdr = {"svix-id": mid, "svix-timestamp": str(int(ts.timestamp())), "svix-signature": wh.sign(mid, ts, payload),
                   "Content-Type": "application/json"}
            bad = dict(hdr, **{"svix-signature": "v1,AAAA"})
            assert requests.post(f"{BASE_URL}/api/webhooks/resend", data=payload, headers=bad).status_code == 400
            r = requests.post(f"{BASE_URL}/api/webhooks/resend", data=payload, headers=hdr)
            assert r.status_code == 200 and r.json() == {"ok": True}
            r2 = requests.post(f"{BASE_URL}/api/webhooks/resend", data=payload, headers=hdr)
            assert r2.json().get("duplicate") is True
            assert mdb.outbound.find_one({"id": f"TEST_o_{TAG}"})["status"] == "complained"
            s = mdb.suppressions.find_one({"value": seed[2]["email"]})
            assert s and s["reason"] == "spam complaint"
            assert mdb.businesses.find_one({"id": seed[2]["bid"]})["email_status"] == "complained"
        finally:
            mdb.settings.update_one({"_id": "app"}, {"$set": {"resend.webhook_secret": prev}})
            mdb.webhook_events.delete_many({"svix_id": {"$regex": TAG}})


# ---------- merge / prospects ----------
class TestProspects:
    def test_detail_notes_exclude(self, client, seed):
        bid = seed[2]["bid"]
        assert client.get(f"{BASE_URL}/api/prospects/{bid}").status_code == 200
        assert client.patch(f"{BASE_URL}/api/prospects/{bid}", json={"notes": "TEST note"}).status_code == 200
        assert client.get(f"{BASE_URL}/api/prospects/{bid}").json()["business"].get("notes") == "TEST note"
        assert client.post(f"{BASE_URL}/api/prospects/{bid}/exclude", json={"reason": "TEST", "exclude": True}).status_code == 200
        d = client.get(f"{BASE_URL}/api/prospects/{bid}").json()
        assert d["business"]["excluded"] is True and d["suppressed"]
        client.post(f"{BASE_URL}/api/prospects/{bid}/exclude", json={"exclude": False})
        d = client.get(f"{BASE_URL}/api/prospects/{bid}").json()
        assert d["business"]["excluded"] is False and not d["suppressed"]
        assert client.post(f"{BASE_URL}/api/prospects/{bid}/reassess").status_code == 200

    def test_merge(self, client, seed, mdb):
        r = client.post(f"{BASE_URL}/api/prospects/merge", json={"keep_id": seed[1]["bid"], "merge_id": seed[2]["bid"]})
        assert r.status_code == 200
        keep, other = mdb.businesses.find_one({"id": seed[1]["bid"]}), mdb.businesses.find_one({"id": seed[2]["bid"]})
        assert other["merged_into"] == keep["id"] and keep["website"] and keep["phone"] == "0399990000"
        assert mdb.contacts.count_documents({"business_id": keep["id"]}) == 2

    def test_merge_same(self, client, seed):
        assert client.post(f"{BASE_URL}/api/prospects/merge", json={"keep_id": seed[1]["bid"], "merge_id": seed[1]["bid"]}).status_code == 400


# ---------- services / settings / misc ----------
class TestMisc:
    def test_services(self, client, mdb):
        assert client.post(f"{BASE_URL}/api/services", json={"name": "TEST_Visabal", "approved": True}).status_code == 400
        s = client.post(f"{BASE_URL}/api/services", json={"name": f"TEST_svc_{TAG}", "approved": True}).json()
        u = client.put(f"{BASE_URL}/api/services/{s['id']}", json={"name": f"TEST_svc_{TAG}", "pricing": "$1"})
        assert u.json()["pricing"] == "$1"
        assert client.put(f"{BASE_URL}/api/services/{s['id']}", json={"name": "TEST Visabal", "approved": True}).status_code == 400
        assert client.delete(f"{BASE_URL}/api/services/{s['id']}").status_code == 200
        assert s["id"] not in [x["id"] for x in client.get(f"{BASE_URL}/api/services").json()]

    @pytest.mark.parametrize("name,ok", [("ai", True), ("nominatim", True), ("overpass", True), ("screenshots", True), ("resend", False), ("imap", False)])
    def test_integrations(self, client, name, ok):
        r = client.post(f"{BASE_URL}/api/integrations/test/{name}", timeout=90)
        assert r.status_code == 200 and r.json()["ok"] is ok, r.json()

    def test_backup_and_audit(self, client):
        r = client.post(f"{BASE_URL}/api/backups", timeout=90)
        assert r.status_code == 200 and r.json()["name"]
        assert r.json()["name"] in [f["name"] for f in client.get(f"{BASE_URL}/api/backups").json()["files"]]
        assert len(client.get(f"{BASE_URL}/api/audit").json()) > 0
