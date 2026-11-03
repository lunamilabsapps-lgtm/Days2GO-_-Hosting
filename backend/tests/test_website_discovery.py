# Website discovery (tiered finder) API tests - only mutates the Burwood Cannings prospect
import time
import pytest
import requests
from conftest import BASE_URL

BID = "da6febe2-09de-4797-b391-b2769beaa310"
OTHER = None


def get_p(client):
    r = client.get(f"{BASE_URL}/api/prospects/{BID}", timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


# Read-only checks
class TestReadOnly:
    def test_burwood_lookup(self, client):
        d = get_p(client)
        lk = d.get("website_lookup")
        print("lookup:", {k: lk.get(k) for k in ("status", "confidence", "source", "tiers", "errors")} if lk else None)
        print("business:", {k: d["business"].get(k) for k in ("website", "website_status", "email_status", "research_status", "website_source")})
        assert lk and lk["status"] == "needs_review"
        c = lk["candidates"][0]
        print("cand:", c)
        assert c["domain"] == "canningsfreerangebutchers.com.au"
        assert "canningsbutchers.com.au" in (c.get("final_url") or "")
        assert c["score"] == 55
        assert d["business"]["website_status"] == "website_unverified"
        assert d["business"]["email_status"] == "needs_review"

    def test_integrations_status(self, client):
        r = client.get(f"{BASE_URL}/api/integrations/status", timeout=30)
        assert r.status_code == 200
        d = r.json()
        print({k: d.get(k) for k in ("serper", "brave", "website_discovery")})
        assert d["serper"]["configured"] is False
        assert d["brave"]["configured"] is False
        assert "website_discovery" in d and "results" in d["website_discovery"]

    def test_serper_test(self, client):
        r = client.post(f"{BASE_URL}/api/integrations/test/serper", timeout=30)
        print(r.status_code, r.text)
        d = r.json()
        assert d["ok"] is False and "API key not set" in str(d)

    def test_brave_test(self, client):
        r = client.post(f"{BASE_URL}/api/integrations/test/brave", timeout=30)
        print(r.status_code, r.text)
        assert r.json().get("ok") is False

    def test_stats(self, client):
        r = client.get(f"{BASE_URL}/api/website-discovery/stats", timeout=30)
        print(r.text)
        assert r.status_code == 200 and "results" in r.json() and "queued" in r.json()

    def test_recheck_blocked(self, client):
        r = client.post(f"{BASE_URL}/api/website-discovery/recheck", timeout=30)
        print(r.status_code, r.text)
        assert r.status_code == 400 and "Serper or Brave" in r.text

    def test_confirm_rejects_facebook(self, client):
        r = client.post(f"{BASE_URL}/api/prospects/{BID}/website/confirm", json={"url": "https://www.facebook.com/canningsbutchers"}, timeout=30)
        print(r.status_code, r.text)
        assert r.status_code == 400

    @pytest.mark.parametrize("u", ["not a url", "", "https://nodot", "ftp//x"])
    def test_confirm_rejects_invalid(self, client, u):
        r = client.post(f"{BASE_URL}/api/prospects/{BID}/website/confirm", json={"url": u}, timeout=30)
        print(u, r.status_code, r.text)
        assert r.status_code == 400

    def test_unauth(self):
        r = requests.post(f"{BASE_URL}/api/prospects/{BID}/website/reject", timeout=30)
        assert r.status_code in (401, 403)

    def test_404(self, client):
        r = client.post(f"{BASE_URL}/api/prospects/nope-123/website/reject", timeout=30)
        assert r.status_code == 404


# Mutating flow on Burwood only: reject -> search again -> confirm
class TestFlow:
    def test_reject(self, client):
        r = client.post(f"{BASE_URL}/api/prospects/{BID}/website/reject", timeout=30)
        assert r.status_code == 200
        d = get_p(client)
        print("after reject:", d["website_lookup"]["status"], d["website_lookup"].get("rejected_domains"), d["business"]["research_status"])
        assert d["website_lookup"]["status"] == "rejected_by_user"
        assert "canningsfreerangebutchers.com.au" in d["website_lookup"]["rejected_domains"]

    def test_search_again(self, client):
        r = client.post(f"{BASE_URL}/api/prospects/{BID}/website/search", timeout=30)
        assert r.status_code == 200
        d = get_p(client)
        print("after search:", d["website_lookup"]["status"], d["business"]["research_status"])
        assert d["website_lookup"]["status"] == "search_requested"
        assert d["business"]["research_status"] == "refresh_requested"
        st = None
        for _ in range(30):
            time.sleep(5)
            d = get_p(client)
            st = d["website_lookup"]["status"]
            if st != "search_requested" and d["business"]["research_status"] in ("assessed", "failed"):
                break
        print("after worker:", st, d["website_lookup"].get("candidates"), d["website_lookup"].get("rejected_domains"),
              d["business"].get("website_status"), d["business"].get("research_status"), d["business"].get("email_status"))
        assert st != "search_requested", "worker did not re-run"
        assert d["business"]["website_status"] != "no_website"

    def test_confirm(self, client):
        r = client.post(f"{BASE_URL}/api/prospects/{BID}/website/confirm", json={"url": "https://canningsbutchers.com.au"}, timeout=30)
        assert r.status_code == 200, r.text
        b = get_p(client)["business"]
        print("after confirm:", {k: b.get(k) for k in ("website", "website_source", "website_confidence", "research_status")})
        assert b["website"] == "https://canningsbutchers.com.au"
        assert b["website_source"] == "manual_confirmation"
        assert b["website_confidence"] == 100
        assert b["research_status"] in ("refresh_requested", "assessing", "pending")
        for _ in range(36):
            time.sleep(5)
            d = get_p(client)
            if d["business"]["research_status"] in ("assessed", "failed"):
                break
        b = d["business"]
        print("final:", {k: b.get(k) for k in ("website", "website_status", "website_source", "research_status", "email_status", "grade", "score")})
        assert b["research_status"] == "assessed"
        assert b["website_status"] == "website_exists"
        assert b["website"] == "https://canningsbutchers.com.au"
