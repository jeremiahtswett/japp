# ADR 0001 — Source access strategy (spec §6.1)

**Decision:** M1 polls four sources over official/public routes only: the Greenhouse
Job Board API (`boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true`), the
Lever postings API (`api.lever.co/v0/postings/{org}?mode=json`), the Ashby posting API
(`api.ashbyhq.com/posting-api/job-board/{org}`), and Adzuna's official developer API
(free registered `app_id`/`app_key`, keys in `.env`). The three ATS feeds are public,
documented, auth-free, and highly reliable; boards to poll come from the user-curated
company list in `sources.yaml`. Adzuna adds broad-market discovery at medium-high
reliability with a clean ToS posture for low-volume registered personal use.

**Explicitly rejected:** scraping LinkedIn or Indeed (ToS-prohibited, bot-blocked —
spec ground rule 4; Indeed's Publisher API is deprecated). **Documented for future
opt-in only:** JSearch (OpenWeb Ninja), which resells Google-for-Jobs data covering
LinkedIn/Indeed postings — legitimate as an API purchase but gray upstream (the vendor
scrapes Google); ~100–200 free requests/month. Not implemented; adding it later is one
new `JobSource` subclass behind a config flag, and requires an explicit user decision.

**Politeness:** configurable poll interval (default 2h, floor 1h enforced at config
validation), per-host request throttle, ETag/If-Modified-Since conditional requests
backed by an on-disk cache, descriptive User-Agent, per-source failure isolation.
