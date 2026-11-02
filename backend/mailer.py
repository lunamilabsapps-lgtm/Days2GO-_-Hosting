import os
import re
import email
import imaplib
import asyncio
import secrets
from email.utils import parseaddr, parsedate_to_datetime
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import httpx
from core import db, uid, iso, log, get_settings, activity, audit, notify, is_suppressed, add_suppression


def public_url():
    return os.environ["PUBLIC_APP_URL"].rstrip("/")


def compose_body(d, s, token):
    snd = s["sender"]
    unsub = f"{public_url()}/api/unsubscribe/{token}"
    sig = snd.get("signature_name") or snd["name"]
    ident = " | ".join(x for x in [f"{snd.get('business_name')} ({snd['business_status']})" if snd.get("business_status") else snd.get("business_name"),
                                   f"ABN {snd['abn']}" if snd.get("abn") else "",
                                   snd.get("business_address"), snd.get("website")] if x)
    sig_lines = [x for x in [sig if sig != snd.get("business_name") else "", " · ".join(y for y in [snd.get("business_name"), snd.get("location")] if y), snd.get("mobile")] if x]
    if snd.get("signature_block"):
        sig_text, sig_html = snd["signature_block"].strip(), snd["signature_block"].strip().replace("\n", "<br>")
    else:
        sig_text, sig_html = "Cheers,\n" + "\n".join(sig_lines), "Cheers,<br>" + "<br>".join(sig_lines)
    text = f"{d['body']}\n\n{sig_text}\n\n--\n" + f"{ident}\nYou received this one-off email because your business email is published on your website. " \
           f"If you'd rather not hear from us, unsubscribe here: {unsub}"
    html_body = "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in d["body"].split("\n\n"))
    html = f"""<div style="font-family:Arial,sans-serif;font-size:15px;line-height:1.55;color:#1f2937">{html_body}
<p>{sig_html}</p><hr style="border:none;border-top:1px solid #e5e7eb">
<p style="font-size:12px;color:#6b7280">{ident}<br>You received this one-off email because your business email is published on your website.
<a href="{unsub}">Unsubscribe</a></p></div>"""
    return text, html, unsub


def can_send_now(s):
    snd = s["sending"]
    t = datetime.now(ZoneInfo(snd["timezone"]))
    if snd.get("weekdays_only") and t.weekday() >= 5:
        return False, "outside sending days"
    if not (snd["hours_start"] <= t.hour < snd["hours_end"]):
        return False, f"outside sending hours ({snd['hours_start']}:00-{snd['hours_end']}:00 {snd['timezone']})"
    return True, ""


async def send_draft(d, campaign, s):
    snd = s["sender"]
    test = s["sending"]["test_mode"]
    b = await db.businesses.find_one({"id": d["business_id"]}, {"_id": 0})
    sup = await is_suppressed(d["recipient"], b)
    if sup or b.get("reply_status") == "replied" or b.get("excluded"):
        await db.drafts.update_one({"id": d["id"]}, {"$set": {"status": "blocked", "blocked_reason": "suppressed/replied/excluded"}})
        return "blocked"
    token = secrets.token_urlsafe(24)
    domain = snd.get("domain") or (snd.get("email", "@x").split("@")[-1])
    message_id = f"<{uid()}@{domain}>"
    text, html, unsub = compose_body(d, s, token)
    to = s["sending"]["test_recipient"] if test else d["recipient"]
    subject = (f"[TEST → {d['recipient']}] " if test else "") + d["subject"]
    out = {"id": uid(), "draft_id": d["id"], "campaign_id": campaign["id"], "business_id": d["business_id"],
           "business_name": d["business_name"], "to": d["recipient"], "actual_to": to, "subject": d["subject"],
           "message_id": message_id, "unsub_token": token, "test_mode": test, "events": [], "created_at": iso()}
    key = s["resend"]["api_key"]
    if not key:
        if not test:
            raise RuntimeError("Resend API key not configured")
        out.update(status="test_dry_run", sent_at=iso(), note="Test mode without Resend key: nothing was sent.")
    else:
        payload = {"from": f"{snd['name']} <{snd['email']}>", "to": [to], "subject": subject, "text": text, "html": html,
                   "headers": {"Message-ID": message_id, "List-Unsubscribe": f"<{unsub}>",
                               "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}}
        if snd.get("reply_to"):
            payload["reply_to"] = snd["reply_to"]
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post("https://api.resend.com/emails", json=payload,
                             headers={"Authorization": f"Bearer {key}", "Idempotency-Key": f"draft-{d['id']}"})
        if r.is_error:
            await notify("delivery_problem", f"Resend rejected email to {d['business_name']}", r.text[:300], "high")
            await db.drafts.update_one({"id": d["id"]}, {"$set": {"status": "send_failed", "error": r.text[:300]}})
            await audit("email_send_failed", "draft", d["id"], {"error": r.text[:300]})
            return "failed"
        out.update(status="sent", resend_id=r.json().get("id"), sent_at=iso())
    await db.outbound.insert_one(dict(out))
    await db.drafts.update_one({"id": d["id"]}, {"$set": {"status": "sent", "sent_at": iso(), "outbound_id": out["id"]}})
    await db.businesses.update_one({"id": d["business_id"]}, {"$set": {"email_status": "sent" if not test else "test_sent",
                                                                     "follow_up_status": "none"}})
    await db.campaigns.update_one({"id": campaign["id"]}, {"$inc": {"sent_count": 1}, "$set": {"last_sent_at": iso()}})
    await audit("email_sent", "outbound", out["id"], {"to": to, "test_mode": test, "status": out["status"]})
    await activity("sent", f"{'TEST ' if test else ''}Email {'logged (dry run)' if out['status'] == 'test_dry_run' else 'sent'} to {d['business_name']}",
                   b, data={"to": to})
    return out["status"]


async def mark_unsubscribed(email_addr, source):
    email_addr = email_addr.lower()
    await add_suppression(email_addr, "email", "unsubscribed", source)
    bids = [c["business_id"] for c in await db.contacts.find({"value": email_addr}, {"_id": 0}).to_list(50)]
    await db.businesses.update_many({"id": {"$in": bids}}, {"$set": {"email_status": "unsubscribed", "follow_up_status": "cancelled"}})
    await db.drafts.update_many({"recipient": email_addr, "status": {"$in": ["pending_approval", "approved"]}},
                                {"$set": {"status": "blocked", "blocked_reason": "unsubscribed"}})
    await notify("unsubscribe", f"Unsubscribe: {email_addr}", f"Source: {source}")


async def handle_reply(out, msg_meta, kind):
    b = await db.businesses.find_one({"id": out["business_id"]}, {"_id": 0})
    if kind == "reply":
        await db.businesses.update_one({"id": b["id"]}, {"$set": {"reply_status": "replied", "email_status": "replied",
                                                                 "follow_up_status": "cancelled", "replied_at": iso()}})
        await db.drafts.update_many({"business_id": b["id"], "status": {"$in": ["pending_approval", "approved"]}},
                                    {"$set": {"status": "blocked", "blocked_reason": "business replied"}})
        await db.outbound.update_one({"id": out["id"]}, {"$set": {"status": "replied"}, "$push": {"events": {"type": "replied", "at": iso()}}})
        camp = await db.campaigns.find_one({"id": out["campaign_id"]}, {"_id": 0, "name": 1})
        await notify("reply", f"REPLY from {b['name']}", f"Campaign: {(camp or {}).get('name')} — {msg_meta.get('subject', '')}",
                     "urgent", link=f"/prospects/{b['id']}", data={"business_id": b["id"]})
        await activity("reply", f"Reply received from {b['name']}", b, level="success")
    elif kind == "ooo":
        await db.businesses.update_one({"id": b["id"]}, {"$set": {"reply_status": "out_of_office"}})
    await audit(f"inbound_{kind}", "business", b["id"], {"subject": msg_meta.get("subject")})


async def process_webhook_event(event):
    t = event.get("type", "")
    data = event.get("data") or {}
    out = await db.outbound.find_one({"resend_id": data.get("email_id")}, {"_id": 0})
    if not out:
        return
    status = {"email.delivered": "delivered", "email.bounced": "bounced", "email.complained": "complained",
              "email.delivery_delayed": "delayed", "email.failed": "failed"}.get(t)
    if not status:
        return
    upd = {"$push": {"events": {"type": status, "at": event.get("created_at") or iso()}}}
    if out.get("status") != "replied":
        upd["$set"] = {"status": status}
    await db.outbound.update_one({"id": out["id"]}, upd)
    if out.get("test_mode"):
        return
    if status == "delivered":
        await db.businesses.update_one({"id": out["business_id"], "email_status": "sent"}, {"$set": {"email_status": "delivered"}})
    elif status == "bounced":
        btype = (data.get("bounce") or {}).get("type", "")
        await db.businesses.update_one({"id": out["business_id"]}, {"$set": {"email_status": "bounced"}})
        if btype.lower() in ("permanent", "hard", ""):
            await add_suppression(out["to"], "email", f"bounced {btype}".strip(), "resend_webhook")
        await notify("delivery_problem", f"Bounce: {out['business_name']}", out["to"], "high")
    elif status == "complained":
        await add_suppression(out["to"], "email", "spam complaint", "resend_webhook")
        await db.businesses.update_one({"id": out["business_id"]}, {"$set": {"email_status": "complained", "follow_up_status": "cancelled"}})
        await notify("delivery_problem", f"Spam complaint: {out['business_name']}", out["to"], "high")
    elif status == "failed":
        await notify("delivery_problem", f"Delivery failed: {out['business_name']}", out["to"], "high")


OOO_RE = re.compile(r"(out of (the )?office|automatic reply|auto.?reply|on leave|away from|annual leave)", re.I)
UNSUB_RE = re.compile(r"\b(unsubscribe|remove me|stop emailing|take me off)\b", re.I)


def _body_text(msg):
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_type() == "text/plain":
            try:
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "ignore")
            except Exception:
                pass
    return ""


def _imap_connect(cfg, timeout):
    sec = (cfg.get("security") or "ssl").lower()
    if sec == "ssl":
        m = imaplib.IMAP4_SSL(cfg["host"], int(cfg["port"]), timeout=timeout)
    else:
        m = imaplib.IMAP4(cfg["host"], int(cfg["port"]), timeout=timeout)
        if sec == "starttls":
            m.starttls()
    m.login(cfg["username"], cfg["password"])
    return m


def _imap_fetch(cfg, since_days=4):
    m = _imap_connect(cfg, 30)
    m.select(cfg.get("folder") or "INBOX", readonly=True)
    since = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
    _, ids = m.search(None, f"(SINCE {since})")
    msgs = []
    for i in ids[0].split()[-300:]:
        _, data = m.fetch(i, "(BODY.PEEK[])")
        if data and data[0]:
            msgs.append(email.message_from_bytes(data[0][1]))
    m.logout()
    return msgs


async def imap_test(cfg):
    def t():
        m = _imap_connect(cfg, 20)
        m.select(cfg.get("folder") or "INBOX", readonly=True)
        m.logout()
    await asyncio.to_thread(t)


async def poll_imap():
    s = await get_settings()
    cfg = s["imap"]
    if not cfg["enabled"] or not cfg["username"] or not cfg["password"]:
        return 0
    msgs = await asyncio.to_thread(_imap_fetch, cfg)
    n = 0
    for msg in msgs:
        mid = (msg.get("Message-ID") or "").strip()
        if not mid or await db.inbound.find_one({"message_id": mid}):
            continue
        frm = parseaddr(msg.get("From", ""))[1].lower()
        subj = str(msg.get("Subject", ""))
        refs = " ".join([msg.get("In-Reply-To", ""), msg.get("References", "")])
        body = _body_text(msg)
        ctype = msg.get_content_type()
        is_bounce = frm.startswith(("mailer-daemon", "postmaster")) or ctype == "multipart/report"
        out = None
        for ref in re.findall(r"<[^>]+>", refs):
            out = await db.outbound.find_one({"message_id": ref}, {"_id": 0})
            if out:
                break
        matched_by = "message_id" if out else None
        if not out and is_bounce:
            fr = re.search(r"Final-Recipient:.*?;\s*([^\s]+)", body + str(msg), re.I)
            if fr:
                out = await db.outbound.find_one({"to": fr.group(1).lower()}, {"_id": 0}, sort=[("created_at", -1)])
                matched_by = "bounce_recipient"
        if not out and frm:
            out = await db.outbound.find_one({"to": frm, "test_mode": False}, {"_id": 0}, sort=[("created_at", -1)])
            matched_by = "sender_address" if out else None
        if not out:
            continue
        auto = (msg.get("Auto-Submitted", "no").lower() != "no") or bool(OOO_RE.search(subj))
        kind = "bounce" if is_bounce else "ooo" if auto else "reply"
        try:
            date = parsedate_to_datetime(msg.get("Date")).isoformat()
        except Exception:
            date = iso()
        await db.inbound.insert_one({"id": uid(), "message_id": mid, "from": frm, "subject": subj, "received_at": date,
                                     "in_reply_to": msg.get("In-Reply-To"), "kind": kind, "matched_by": matched_by,
                                     "outbound_id": out["id"], "business_id": out["business_id"],
                                     "business_name": out["business_name"], "campaign_id": out["campaign_id"],
                                     "snippet": body[:400], "created_at": iso()})
        n += 1
        if kind == "bounce":
            await add_suppression(out["to"], "email", "bounced (mailbox)", "imap")
            await db.businesses.update_one({"id": out["business_id"]}, {"$set": {"email_status": "bounced"}})
            await notify("delivery_problem", f"Bounce: {out['business_name']}", out["to"], "high")
            continue
        await handle_reply(out, {"subject": subj}, kind)
        if kind == "reply" and UNSUB_RE.search(body[:500] + subj):
            await mark_unsubscribed(out["to"], "reply_request")
    return n
