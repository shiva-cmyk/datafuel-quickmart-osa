# Recording

## Recording Status

**Status:** NOT PROVIDED YET

The assignment requires a screen recording showing the development process and a final approximately 5-minute walkthrough.

No recording URL is included in this repository yet.

---

# Required Recording

The recording should show the project from beginning to end.

It should include:

1. Starting the mock QuickMart server.
2. Showing the API/health endpoint.
3. Running the inventory sweeps.
4. Showing how pagination works.
5. Showing retry/error handling.
6. Showing soft-ban handling.
7. Showing the SQLite database.
8. Running the tests.
9. Starting `app.py`.
10. Calling `/osa`.
11. Showing the results for:

* Mumbai
* Delhi
* Bengaluru

12. Explaining incomplete coverage.
13. Explaining the OSA calculation.
14. Explaining the code review.
15. Showing the important documentation.
16. Giving the final project walkthrough.

---

# Development Recording

The assignment asks for the screen recording to begin before coding and continue until the last commit.

The recording may consist of multiple parts if breaks are necessary.

The recording should not be artificially sped up or edited to hide development activity.

**Development recording URL:** NOT PROVIDED YET

---

# Final 5-Minute Walkthrough

The final walkthrough should briefly explain:

## 0:00–0:30 — Problem

Explain that the project collects inventory snapshots from the QuickMart mock API and calculates city-level On-Shelf Availability (OSA).

## 0:30–1:00 — Architecture

Explain:

```text
QuickMart API
     ↓
sweep.py
     ↓
SQLite
     ↓
app.py
     ↓
GET /osa
```

## 1:00–2:00 — Scraper

Explain:

* store pagination
* inventory pagination
* active-store selection
* `as_of`
* `in_stock`
* duplicate handling
* timestamp normalization
* retries
* timeout
* 429
* 500/503
* soft-ban handling
* partial responses

## 2:00–3:00 — Database and OSA

Explain:

* `stores`
* `sweeps`
* `store_sweeps`
* `observations`
* primary keys
* idempotency
* complete/incomplete sweeps
* weighted OSA calculation
* coverage

## 3:00–4:00 — API

Demonstrate:

```text
GET /osa?city=Mumbai&date=2026-09-28
GET /osa?city=Delhi&date=2026-09-28
GET /osa?city=Bengaluru&date=2026-09-28
```

Explain why Delhi may contain incomplete coverage when the mock API intentionally returns a partial response.

## 4:00–5:00 — Tests and Review

Show:

```text
python -m pytest -q
```

Explain:

* wrong OSA tests
* ghost stock
* weighted aggregation
* incomplete stores
* IST date mapping
* duplicate handling
* retry behavior
* code review findings

Then briefly explain the most important fixes made to `review_me.py`.

---

# Final Recording Link

**URL:** NOT PROVIDED YET

After uploading the recording, replace the line above with the actual public/unlisted YouTube or Google Drive URL.

---

# Link Verification

The final recording URL must be tested in an incognito/private browser window before submission.

**Verification status:** NOT VERIFIED

---

# Recording Notes

Do not claim that a recording exists until it has actually been recorded and uploaded.

Do not invent a recording URL.

The final submission should contain the real recording URL and, if useful, timestamps/chapters for important sections.
