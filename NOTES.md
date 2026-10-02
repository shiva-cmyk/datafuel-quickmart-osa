# NOTES.md

# DataFuel QuickMart OSA Assignment — Implementation Notes

## 1. Store Selection

The QuickMart API provides the complete store roster through:

```text
GET /v1/stores?page=N
```

The implementation in `sweep.py` first fetches all store pages.

The scraper tracks stores where:

```text
is_active = true
```

Inactive/decommissioned stores are not included in inventory sweeps.

### Why?

`is_active` indicates whether the store is part of the QuickMart network.

A store that is inactive should not be treated as an expected active store for OSA.

`is_serviceable` is stored in the database but is not used as the primary filter.

This is intentional because:

```text
is_serviceable = false
```

does not necessarily mean the store is shut down. It means the store is currently not accepting orders and this value can change during the day.

For example, the provided mock server contains an active but currently non-serviceable store:

```text
DEL-006
```

Therefore we do not remove every non-serviceable store from the network.

---

# 2. Why `in_stock` Is Used Instead of `qty`

The API documentation explicitly defines:

```text
in_stock
```

as QuickMart's availability flag.

`qty` is only informational.

The mock server intentionally creates ghost-stock cases where:

```text
in_stock = true
qty = 0
```

Therefore:

```text
qty > 0
```

must not be used to decide whether a product is available.

The production implementation stores and calculates OSA using:

```text
in_stock
```

This prevents ghost-stock cases from producing incorrect OSA values.

---

# 3. Incomplete Store Sweeps

The scraper does not assume that every API response is complete.

For every active store and sweep timestamp, the database stores a `store_sweeps` record.

The status can be:

```text
complete
```

or:

```text
incomplete
```

An incomplete result also records a reason.

Examples include:

```text
portal returned partial snapshot
```

or:

```text
soft ban persisted after retries
```

or:

```text
scrape error: ...
```

### Why?

Missing data is not the same as zero stock.

The assignment explicitly says:

> Wrong number is worse than no number.

Therefore incomplete data is excluded from the valid OSA calculation.

---

# 4. Partial API Responses

The QuickMart API can return:

```text
partial = true
```

A response with `partial = true` is not considered a complete inventory snapshot.

`sweep.py` marks that store-sweep as incomplete.

It does not store the partial products as a valid complete snapshot.

### Why?

If only part of a store's inventory is received, calculating OSA from that incomplete data could produce a misleading number.

---

# 5. Soft-Ban Handling

The mock QuickMart server intentionally has a soft-ban behavior.

A soft-banned request can still return:

```text
HTTP 200
```

but:

```text
meta.source = "edge"
```

and the response may contain empty or truncated inventory.

Therefore checking only:

```text
HTTP 200
```

is not enough.

`sweep.py` checks:

```text
meta.source
```

and treats:

```text
edge
```

as a soft-ban/degraded response.

The scraper waits before trying again and restarts the store's inventory pagination from cursor `0`.

The retry count is bounded.

If the soft ban continues after the allowed attempts, the store-sweep is recorded as incomplete.

### Why restart from cursor 0?

A degraded response may have returned incomplete data and may have incorrectly indicated that there are no more pages.

Starting again from cursor `0` gives the server a chance to return the complete snapshot.

Previously collected data is cleared when restarting so that potentially incomplete data is not mixed with a later complete attempt.

---

# 6. Rate Limiting and HTTP 429

The API can return:

```text
HTTP 429
```

which means the client is sending requests too quickly.

The server provides:

```text
Retry-After
```

`sweep.py` reads this header and waits for the specified amount of time before retrying.

The scraper also introduces a small delay between requests.

The normal request delay is:

```text
0.45 seconds
```

This keeps the request rate well below the mock server's burst threshold.

### Why?

Immediately retrying a 429 would make the rate-limit problem worse.

---

# 7. HTTP 500 and 503

HTTP 500 and 503 are treated as temporary server-side failures.

`sweep.py` retries them using exponential backoff.

The wait times increase approximately as:

```text
1 second
2 seconds
4 seconds
8 seconds
...
```

with a maximum delay of 8 seconds for this implementation.

Retries are bounded.

The scraper therefore does not retry forever.

---

# 8. Timeouts

Inventory requests use a timeout.

Current timeout:

```text
5 seconds
```

The mock server intentionally has some slow requests.

Without a timeout, the scraper could wait indefinitely.

With the timeout, the request fails and can be retried according to the retry policy.

---

# 9. Permanent HTTP Errors

Not every HTTP error should be retried.

For example:

```text
400 Bad Request
401 Unauthorized
404 Not Found
```

are not treated as temporary server failures.

The retry logic in `sweep.py` retries temporary problems such as:

```text
timeout
429
500
503
```

but does not intentionally retry permanent HTTP errors.

---

# 10. Pagination

Both the store API and inventory API are paginated.

### Stores

The scraper starts at:

```text
page = 1
```

and continues using:

```text
next_page
```

until:

```text
next_page = null
```

### Inventory

The scraper starts with:

```text
cursor = 0
```

and continues using:

```text
next_cursor
```

until:

```text
next_cursor = null
```

### Why?

The API does not return the entire dataset in one response.

Pagination allows the scraper to retrieve all stores and all inventory pages.

---

# 11. Duplicate Inventory Items

The mock server can intentionally duplicate an inventory item across pages.

The scraper therefore deduplicates inventory items using:

```text
sku_id
```

A dictionary keyed by `sku_id` is used while collecting the pages.

This means that if the same SKU appears twice during the same store/sweep, it does not become two observations.

### Why?

Counting the same SKU twice would increase the observation count and could change the OSA percentage incorrectly.

---

# 12. Timestamp Normalization

QuickMart can return `observed_at` timestamps in different timezones.

Mumbai and Bengaluru use UTC timestamps.

Delhi can return IST timestamps.

The scraper converts all `observed_at` timestamps to UTC before storing them.

### Why?

Having one internal timezone makes timestamp comparisons and database queries more consistent.

The requested business date is still calculated using IST.

---

# 13. UTC and IST

The assignment defines the `/osa` date as an IST calendar day.

Therefore the scraper stores each sweep's:

```text
as_of
```

in UTC and also stores:

```text
ist_date
```

for the corresponding IST calendar date.

For example:

```text
2026-09-27T19:00:00Z
```

is:

```text
2026-09-28T00:30:00+05:30
```

in IST.

Therefore this sweep belongs to:

```text
2026-09-28
```

for the `/osa?date=2026-09-28` query.

Using only the UTC calendar date would incorrectly assign this sweep to September 27.

---

# 14. Database Design

SQLite is used as the local database.

The main database file is:

```text
osa.db
```

The application creates the database automatically if it does not already exist.

`db.py` creates the schema.

The main tables are:

```text
stores
sweeps
store_sweeps
observations
```

---

# 15. `stores` Table

This table contains the QuickMart store roster.

Important fields:

```text
store_id
city
name
is_active
is_serviceable
```

The store ID is the primary key.

The table is populated from the actual QuickMart store API.

---

# 16. `sweeps` Table

This table represents one inventory sweep.

Important fields:

```text
as_of
ist_date
started_at
finished_at
```

`as_of` identifies the requested snapshot time.

It is the primary key.

---

# 17. `store_sweeps` Table

This table records the result of one store during one sweep.

Important fields:

```text
as_of
store_id
status
reason
item_count
fetched_at
```

The primary key is:

```text
(as_of, store_id)
```

This means one store has one recorded result for a particular sweep.

---

# 18. `observations` Table

Each row represents one SKU observation for:

```text
one store
one sweep
one SKU
```

Important fields:

```text
as_of
store_id
sku_id
name
in_stock
qty
price
observed_at
```

The primary key is:

```text
(as_of, store_id, sku_id)
```

This prevents duplicate observations for the same SKU in the same store/sweep.

---

# 19. Idempotency

Idempotency means that running the same operation again should not create incorrect duplicate data.

For a complete store-sweep, the implementation deletes the previous observations for that exact:

```text
as_of + store_id
```

and inserts the newly fetched complete snapshot.

The `store_sweeps` row is also updated using an upsert.

Therefore rerunning the same sweep does not keep adding duplicate observations.

For incomplete results, existing valid observations are not deleted. However, the current `store_sweeps` status becomes incomplete, and the API excludes that store-sweep from the OSA calculation.

This protects the reported number from using stale data as if it were a fresh complete snapshot.

---

# 20. Transactions and Commits

The database writes are committed after important operations.

For example:

* store roster
* sweep record
* individual store result

are committed to SQLite.

This means progress is saved as the scraper works through the stores.

If a later store fails, already completed store results remain available.

The API can then see which stores were complete and which were incomplete.

---

# 21. OSA Calculation

The required OSA calculation is:

```text
total in_stock observations
--------------------------- × 100
total observations
```

For example:

```text
Store A:
9 in stock / 10 observations

Store B:
1 in stock / 2 observations
```

The correct calculation is:

```text
(9 + 1) / (10 + 2) × 100
= 83.33%
```

It is not:

```text
(90% + 50%) / 2
= 70%
```

The production `app.py` calculates OSA using all valid observations together.

This gives each observation equal weight.

---

# 22. Incomplete Stores and OSA

A store-sweep marked:

```text
incomplete
```

is not used as a valid source of observations for the OSA calculation.

However, it is reported in the coverage information.

This gives the API two pieces of information:

```text
What OSA can be calculated from valid data?
```

and:

```text
How complete was the underlying data?
```

---

# 23. No Data

No data must never silently become:

```text
0%
```

A value of 0% means that valid observations were seen and none were in stock.

No data means we do not have enough observations to calculate OSA.

Therefore `/osa` returns:

```text
status = no_data
osa_pct = null
```

when there is no valid observation data.

---

# 24. City Validation

The API accepts only:

```text
Mumbai
Delhi
Bengaluru
```

An invalid city returns HTTP 400.

An invalid date format also returns HTTP 400.

---

# 25. Why `app.py` Does Not Call QuickMart

The scraper and reporting API have different jobs.

`sweep.py` talks to QuickMart and collects data.

`app.py` reads the local SQLite database and calculates OSA.

Architecture:

```text
QuickMart API
      |
      | HTTP requests
      v
   sweep.py
      |
      | observations
      v
    osa.db
      |
      | SQL queries
      v
    app.py
      |
      v
   /osa API
```

Keeping these responsibilities separate means `/osa` can report from stored sweep data instead of depending on the live QuickMart server.

---

# 26. SQLite Choice

SQLite is suitable for this assignment because:

* the assignment explicitly allows it
* the database is local
* no separate database server is required
* it supports primary keys and transactions
* it is easy to inspect and reproduce

For a much larger production system, a server-based database could be considered.

---

# 27. Optional 20,000-Store Scaling

For approximately 20,000 stores, the current sequential scraper would take significantly longer.

Possible improvements would include:

* controlled concurrency
* connection pooling
* careful rate limiting
* batching
* checkpointing
* stronger monitoring
* a production database
* queue-based workers

Concurrency must still respect QuickMart's rate limits.

Simply creating thousands of simultaneous requests would make the rate-limit and soft-ban problem worse.

---

# 28. Three Short Assignment Questions

## Q1. Why is HTTP 200 not always enough?

Because QuickMart can return HTTP 200 with degraded data during a soft ban. The scraper must also inspect fields such as `meta.source` and `partial`.

## Q2. Why should `in_stock` be used instead of `qty`?

Because QuickMart defines `in_stock` as the availability flag. The mock API intentionally creates ghost-stock cases where `in_stock=true` but `qty=0`.

## Q3. Why can't we average store percentages?

Because stores can contain different numbers of observations. OSA must be calculated from total in-stock observations divided by total observations.

---

# 29. Important Implementation Principle

The most important rule for this project is:

```text
Wrong number is worse than no number.
```

Therefore:

```text
missing data ≠ out of stock
partial data ≠ complete data
HTTP 200 ≠ necessarily valid snapshot
qty > 0 ≠ the official availability flag
UTC date ≠ automatically the IST business date
```

The implementation is designed around preserving data correctness rather than forcing a number when the data is incomplete.
