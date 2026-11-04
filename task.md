You are an expert Senior Python Developer & SaaS Architect. Build a fully automated, robust B2B Outreach and Dynamic PDF Generation system in Python based on the following precise specifications. Organize the code cleanly into the specified modular folder structure.

---
### PROJECT DEFINITION & CORE RULES
1. **Campaign Segmentation:**
   - **Australia Campaign:** Uses manual CSV list first. If empty or more leads needed, falls back to Apify scraper for specific target cities. Limit: Max 15 emails per day. Branding on generated PDF: Growva Business logo ONLY (NO ProcedureTracking logo).
   - **Pakistan Schools Campaign:** Uses ONLY manual upload (`pakistan_schools_manual.csv`). If the manual file is empty or no schools exist, do NOT send any emails until new schools are added. Limit: Max 5 emails per day. Branding on generated PDF: Dual Logos (Growva Business + ProcedureTracking).

2. **Deduplication Check (Mandatory):**
   - Before processing any business/school from manual lists or Apify, check `sent_history.csv` or database. If the `url`, `business_name`, or `city` already exists in history, skip it completely. Never scrape, audit, or email a duplicate lead.

3. **Smart Scheduling & Business Days Rules:**
   - **Timezones:** 
     - Pakistan Campaign runs at 9:00 AM Pakistan Standard Time (PST).
     - Australia Campaign runs at 9:00 AM local Australian Time based on the target city/state timezone.
   - **Strict Business Days (Monday to Thursday ONLY):**
     - Emails must ONLY be sent on Monday, Tuesday, Wednesday, and Thursday.
     - **No emails on Friday, Saturday, and Sunday** for both systems.
     - If a scheduled follow-up email (e.g., Day 3) falls on a Friday, Saturday, or Sunday, the system must automatically shift and defer the dispatch to the next valid business day (Monday).

4. **Response & Stop Logic:**
   - Before sending *any* email after the first one (Email 2, 3, 4, 5), check if a reply or response has been received from that business/school URL.
   - If a reply/response is detected, immediately stop all future automated emails for that specific URL.

5. **Dynamic PDF Generation:**
   - Write a script using `ReportLab` that dynamically builds a 2-page executive audit report matching the exact layout style of the provided reference.
   - It must fetch real-time website headers (Server type, PHP version, CMS) using Python `requests` (no paid AI APIs required).
   - Inject variables (`{business_name}`, `{server_type}`, `{php_version}`, `{url}`) into the PDF.
   - Apply logo rendering conditional logic: `if campaign == "Australia": render(Growva_Logo_Only)` else `render(Growva_Logo + ProcedureTracking_Logo)`.

6. **Email Sequence Structure (5-Step Sequence):**
   - **Email 1 (Day 1):** Initial hook + General Security/Advisory PDF attached.
   - **Email 2 (Day 3/4):** Custom Generated Audit PDF attached specifically tailored to their scraped tech stack.
   - **Email 3 (Day 6/7):** Text-only follow-up reminding them to review the custom audit report (NO PDF attached to avoid spam).
   - **Email 4 (Day 9/10):** Value proposition / product intro. For Australia: Growva Business SaaS workflows. For Pakistan: ProcedureTracking CRM features (Fee receipts, Parent App, Attendance sync).
   - **Email 5 (Day 13/14):** Final Break-up email with high open-rate subject line, re-attaching the custom audit report as a final notice, stating we will not follow up further.

---
### STEP-BY-STEP IMPLEMENTATION TASKS FOR CURSOR

- **Task 1: Setup Core & Database (`config.py`, `database.py`)**
  - Implement environment variables loader (`.env`).
  - Create SQLite or CSV logging mechanism (`sent_history.csv`) to track `url`, `business_name`, `campaign_type`, `email_step`, `sent_date`, and `status`.
  - Implement duplicate check function: `is_already_processed(url, business_name)`.

- **Task 2: Scrapers & Manual Loaders (`scraper/`)**
  - Implement `manual_loader.py` to read `australia_manual.csv` and `pakistan_schools_manual.csv`.
  - Implement Apify integration in `apify_scraper.py` as a fallback for Australia with city-wise filtering.

- **Task 3: Tech Detector & Dynamic PDF Builder (`generator/`) + Apify lead backlog**
  - Implement `tech_detector.py` to inspect target website headers (CMS, Server, PHP version) using `requests` and `BeautifulSoup`.
  - Implement `pdf_builder.py` using `ReportLab` to generate the 2-page clean executive audit PDF dynamically, handling logo paths conditionally based on campaign type.
  - Harden Tech Detector & Dynamic PDF Builder as planned (stable detect keys, soft-fail network/SSL, stronger PHP/CMS signals, strict 2-page PDFs, inject `{business_name}` / `{server_type}` / `{php_version}` / `{url}`, AU Growva-only vs PK dual-logo branding).
  - **Apify excess-lead backlog:** Any leads found during Australia Apify scraping that exceed the daily send quota (15) must be safely stored in a local backlog/database queue (`data/lead_backlog.csv`). Prefer draining this backlog on upcoming outreach days before re-scraping Apify. Skip backlog entries already present in `sent_history` / processed leads.
Please implement the final outreach engine updates (Task 4 & Task 5) based on the following locked project rules and architecture:

1. Campaign & Targeting Rules:
   - Australia Campaign: Target service businesses (salons, gyms, cafes, etc.) for Growva Business (Growvabusiness.app). 
     - School/College Filtering: If an Australian lead is a school/college, NEVER email them unless a PHP/legacy security issue is detected via tech_detector. If no PHP issue is found, completely skip/reject Australian schools.
     - For normal service businesses, send the Growva Business campaign.
   - Pakistan Campaign: Strictly handle via manual CSV (`pakistan_schools_manual.csv`) targeting schools only, pitching ProcedureTracking with dual branding logos (Growva + ProcedureTracking).

2. Raw Data Preservation:
   - Save all raw Apify scraped data (business name, phone, rating, review count, Google Maps URL, and social/Instagram links) into a dedicated local storage/CSV file so no data is lost for future manual WhatsApp broadcast or Instagram outreach.

3. 6-Email Sequence for Growva Business (Australia):
   - Email 1: Google Reviews hook (using exact review count and rating data fetched from Apify).
   - Email 2: Google Reviews Audit Report (attaching a custom 2-page PDF built dynamically using Apify data and relative benchmark phrasing like "competitors get X% more reviews").
   - Email 3: Customers who don't return (Churn & re-booking nudges).
   - Email 4: Paying for new customers (Commission & marketplace savings).
   - Email 5: Everything in one dashboard (Operations, staff, reminders, reviews).
   - Email 6: Goodbye / Final Follow-up (with Australian Spam Act compliance including full name, "Growva Business", and an unsubscribe/stop line like "Not relevant? Reply 'stop'...").

4. Infrastructure & Execution (Task 4 & Task 5):
   - Implement weekend detector (`is_business_day`) restricting emails to Monday–Thursday only (defending Friday–Sunday to Monday).
   - Enforce strict daily sending limits (15 for Australia, 5 for Pakistan).
   - Implement response checking logic to halt active sequences if a reply is received.
   - Set up the master runner (`main.py`) with cron/CLI support to safely execute daily operations.
- **Task 4: Email Engine, Timezones & Business Day Rules (`sender/`)**
  - Implement weekend detector (`is_business_day(date)`) which returns `True` only for Mon-Thu, and defers Fri-Sun dates to Monday.
  - Implement SMTP mail sender (`email_engine.py`) with strict daily limits (15 for Australia, 5 for Pakistan).
  - Implement response checker mock/logic to halt sequences if a reply is found.

- **Task 5: Master Runner (`main.py`)**
  - Tie everything together with a CLI or cron-compatible runner that executes the daily queue safely following all timezones and constraints.