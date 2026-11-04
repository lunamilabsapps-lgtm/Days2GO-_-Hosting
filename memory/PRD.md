# Bright Coda Local Business Scout — PRD

## Original problem statement
BUILD SPECIFICATION: BRIGHT CODA LOCAL BUSINESS SCOUT. This is a production-ready autonomous platform for Bright Coda (https://brightcoda.com). It finds local brick-and-mortar businesses in Australian cities, assesses their websites, identifies opportunities, writes personalised sales emails and sends approved campaigns through Resend. It also needs: a live activity dashboard (SSE/WebSockets, pause/resume/stop, no fake progress), a geographical discovery engine with permanent coverage records and a coverage map, modular discovery sources (OSM/Overpass, no Google Maps scraping) and duplicate detection (domain, name, phone, address, fuzzy matching, multi-location parents, manual merge). Further parts are an AI website assessment agent (no invented problems, store the evidence), lead scoring 1–100 with A/B/C/D grades and configurable weights, and an editable service/offer catalogue (no Visabal). It must write personalised emails of 100–160 words in Australian English and send them through Resend with approval, Spam Act compliance, unsubscribe and suppression. Reply detection uses IMAP or Resend inbound, with a GREEN REPLIED tag and notifications. It also includes a prospect database with filters and CSV export, a notification centre, persistent background jobs with retries, backoff and restart recovery, and Docker deployment on a Hostinger VPS (compose, nginx/HTTPS, backups, docs). Initial test search: Butchers in Melbourne, in research & draft mode.

User choices: AI = Claude Opus 5.5. Login = single password-protected admin (self-hosted). Storage = MongoDB everywhere. Outbound = the user's own Resend account. Email architecture is hybrid: Resend for outbound, Hostinger IMAP for replies, Resend webhooks for delivered/bounce/complaint, and matching by Message-ID/In-Reply-To/References/sender. Replies are never answered automatically. Credentials are configurable in admin and stored securely; outbound and inbound stay independent.
Additional requirements: multiple campaigns; a permanent exclusion/suppression list; contact-source verification (never invent emails); an opportunity report; AI cost and cost-per-qualified-lead reporting; CSV export and automated backups; campaign, coverage and performance reporting; reassessment intervals; multi-location support; a full audit trail; integrations testable in admin; a test mode that cannot send real emails; consent/unsubscribe/bounce/complaint suppression; processing that continues while the browser is closed or after a VPS restart.

## Architecture
- Backend: FastAPI (`server.py` routes) with core.py (db, settings, crypto, activity/audit/notify), discovery.py (Nominatim + Overpass, category→OSM tags, dedupe), assess.py (httpx + BeautifulSoup + Playwright screenshot/mobile check, Claude assessment, scoring, contacts, eligibility/consent, email drafts), mailer.py (Resend send, webhooks, IMAP poll, unsubscribe), worker.py (discovery loop, 1–4 research slots, sender, IMAP, backups, heartbeat, recovery). Uses MongoDB with unique indexes.
- Worker runs inside the API in preview (RUN_WORKER=true) and as a separate `worker` container in Docker.
- Live: SSE `/api/stream` reads activity events from Mongo, so it works across processes.
- Frontend: React + Tailwind + shadcn, dark/light, react-leaflet map. Pages: Dashboard, New Search, Live Agent, Coverage, Prospects (+detail), Assessments, Campaigns, Replies, Notifications, Service Catalogue, Integrations, Settings.
- Deploy: docker-compose (mongo, api, worker, frontend, caddy HTTPS proxy, mongodump backup), deploy/nginx.conf alternative, .env.example, DEPLOYMENT.md.

## Implemented (2026-11-02)
- Everything above. Iteration 1 testing: backend 44/44 passed. Fixes applied after it: round-robin discovery across searches, partial-zone coverage when max is reached, lockout by email (XFF bypass), settings validation and secret clearing, a quick Overpass test, test-mode unsubscribe no longer suppressing real addresses, consent record upsert, daily limit in the sending timezone, 404s, unexclude restoring drafts, mobile overflow, campaigns filter race, toast typo.
- Initial Melbourne butchers search (262 suburbs, research & draft mode) is running.

## Implemented (2026-11-02, v2 configuration brief)
- Business identity: Leon Duddington / Bright Coda (sole trader), ABN 42 932 842 837, outreach@ → reply-to support@, signature block, Spam Act footer with address, no GST.
- IMAP SSL/TLS/STARTTLS setting; Resend webhooks incl. opened/clicked.
- Approved catalogue v2 (Starter $249+$29/mo, Business $599+$29/mo, AI Business from $1,299+$49/mo, Ecommerce from $1,999+quoted), old services archived; package recommendation logic in AI prompts.
- Visabal research brief per prospect (copy button).
- Per-campaign REVIEW MODE / FULL AUTONOMY control (confirm required), per-campaign daily limit (default 20), duplicate-send guard, shared-address draft dedupe, bounce guard auto-pause.
- One follow-up 5 business days later (threaded), cancelled on reply/unsubscribe/bounce/complaint/suppression/pause/stop/limit.
- Reply sentiment (positive responses), campaign analytics extended. Green rows for replied prospects.
- Iteration 2 testing: backend 11/11 + 27/27, frontend all flows passed.

## Backlog
- P1: Email follow-up sequences (follow_up_status exists, no automatic follow-ups are sent); additional discovery source adapters (licensed directories / search APIs); shadcn Select restyle.
- P2: Resend inbound webhook as an alternative to IMAP; per-search cost dashboard charts.

- 2026-11-03 BUILT & tested (iteration_3): website discovery (website_finder.py) when OSM has no website. Serper Google search (web, then places endpoint) as primary, Brave as fallback, homepage verification scoring (name/phone/suburb/address), confidence + source stored, manual-verification state, cache per business, backfill of existing No Website prospects. Est. 23-33h. AI Voice Agent proposal parked by user.

## Next tasks
- User skipped SERPER_API_KEY / BRAVE_API_KEY at first; keys added 2026-11-04, both tested OK. Re-check of 174 prospects done: 17 found, 31 needs manual check, 127 not found; ~371 searches ≈ US$0.48.
- 2026-11-04: VPS readiness check: compose/install.sh valid, new deps in requirements, SERPER/BRAVE in .env.example + DEPLOYMENT.md, hardcoded admin password removed from backend/tests.
- 2026-11-04: Chain/branch confirmation (follows up to 6 location/store/branch pages, Google Maps listing within 1.5 km of mapped location, Maps street address on site; site must carry the business name). Phone saved from matching Google Maps listing (phone_source). Re-run of 150 review/not-found prospects (backend/website_backfill.py): +6 found, 71 phones added. Totals: 23 found, 29 needs review, 123 not found. Total search spend ≈ US$0.97.
- User to enter the Resend key, webhook secret, IMAP mailbox, sender identity and compliance confirmations, then run a test campaign.
