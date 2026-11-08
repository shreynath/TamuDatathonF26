# Sponsor execution plan and truth-in-advertising matrix

Event-specific MLH prize list: https://www.mlh.com/events/tamu-datathon-ce/prizes

The existence of this kit **does not establish a single new sponsor prize submission**.
All nine categories require real use and eligibility verification.

| Prize | What has been implemented | Additional acceptance evidence required |
|---|---|---|
| Gemini API | Real REST adapter + verified evidence-grounded server endpoint and demo | Live authorized model response in public/authorized judge demo; sponsor submission |
| Snowflake API | Real Cortex REST chat-completions adapter | Genuine Snowflake PAT/account, model access, live request, demo, submission |
| Tiger Data | Hypertable schema, continuous aggregate, parameterized ingest and daily read | Authorized Tiger service, original timestamped data, real table/results, demo |
| Vultr | Read-only instance inventory, plus a deploy plan that refuses open SSH and embedded secrets | Provisioned/authorized instance, HTTPS live application, monitored running endpoint |
| MongoDB Atlas | Source-cited investigation persistence and list endpoint | Real Atlas cluster, database user, indexes/permissions, live save and retrieval |
| Solana | Report SHA-256, and a Devnet read that sets digest_verified only when a memo equals that digest | A signed Devnet memo you publish, then the same check against that signature |
| GoDaddy Registry | Syntax, GoDaddy Registry TLD list, .study campaign check, public-address DNS, HTTPS, RDAP. prize_ready stays false | You register a .study name, point DNS, serve HTTPS, and keep the registrar receipt |
| SpaceXSI | This repo's commits credit Cursor; evidence checklist | Actual Grok Bot automation, Cursor proof, required raffle opt-in and eligibility |
| DEV Writing | `docs/DEV_ARTICLE.md` scores 10/10 on the local rubric and is ready to paste. published stays false | Post that file on DEV during the monthly window with the mlhacks tag, then keep the URL |

## Suggested independent sponsor demos

**Gemini:** Ask “Why inspect M-1158?” Compare deterministic baseline evidence and the verified AI narrative. Deliberately try a fake citation, invalid machine ID, unsupported numeric question, and prompt injection; show the rejection path.

**Snowflake:** Ask the same question through Cortex. Show real account model, latency, relevant user role, response, and model comparison. Do not call it a Snowflake integration before a paid/authorized model call actually succeeds.

**Tiger Data:** Import *original* hourly records with unmodified dates and source hashes. Compare a time-bucket SQL query with independently computed aggregates. Demonstrate a date-range interaction that is really served from Tiger, not from a static JSON file.

**MongoDB:** Save an actual deterministic investigation with evidence IDs, reopen it, and verify the source list. Don't save sensitive player profiles or secrets.

**Vultr:** On an authorized instance, configure HTTPS and limit access to the backend. Show external health check and inspect real instance inventory. A read-only Vultr API key alone is not a hosted app.

**Solana:** If eligible, publish a report-hash memo on Devnet using an authorized client and wallet. Then verify the transaction signature, confirmation, and exact memo bytes. The current code checks transaction existence only, not the digest, and must never claim on-chain proof until expanded and tested.

**GoDaddy:** Confirm event-specific supported TLD, secure explicit registration approval, DNS resolution, HTTPS and actually deployed app. DNS success alone is not ownership proof.

**SpaceXSI:** Verify this event's Cursor+Grok Bot requirement. Create and run one tangible Grok Bot workflow (e.g. non-destructive build report triage). Preserve genuine logs and complete the raffle opt-in if required. Do not fabricate tool use.

**DEV:** Publish the authentic project story including actually verified results, engineering decisions and relevant source links, tagged `#mlhacks`, through the correct account.

## Priority given the same-day 9 PM House Edge deadline

1. Submit House Edge and Poker through the actual authenticated Google Forms; save receipts.
2. Finish Royale's public release, video, write-up, Devpost, and reconcile its competing plans.
3. Complete the Gemini interactive demo with an authenticated backend and live evidence.
4. Add Snowflake + Tiger + Mongo + Vultr only where credentials, time, and budgets allow.
5. Attempt SpaceXSI/DEV/GoDaddy/Solana only after eligibility is verified.

**Do not modify Databricks**: teammate owns it. Do not resume Routes.
