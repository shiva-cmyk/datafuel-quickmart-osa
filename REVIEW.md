# Code Review: review_me.py

## Purpose

`review_me.py` is an intentionally flawed script provided by the assignment. The task is to identify real problems, explain their consequences with concrete examples, and fix only the 2–3 most serious problems without rewriting the entire file.

The review below is based on the actual code and an actual attempt to run the script against `mock_portal.py`.

---

# Problems Found — Most Serious First

## Problem 1 — Infinite/unbounded retry, no timeout, and incorrect transient-error handling

**Severity:** CRITICAL

### What the original code did

The original `fetch_inventory()` used:

```python
while True:
    try:
        requests.get(...)
        ...
    except Exception:
        time.sleep(0.1)
        continue
```

There was:

* no request timeout
* no maximum retry count
* no special handling for HTTP 429
* no use of `Retry-After`
* no distinction between temporary and permanent errors

### What can go wrong?

A request can hang indefinitely because there is no timeout.

Also, a permanent error such as HTTP 400 or 401 is caught and retried forever even though retrying cannot fix the request.

The server can also return HTTP 429 when the client sends requests too quickly. The API specifically says to respect the `Retry-After` header.

Repeated requests every 0.1 seconds can make the situation worse and can contribute to the server's soft-ban behavior.

### Concrete example

Suppose the API returns:

```text
HTTP 429
Retry-After: 2
```

The original code waits only:

```text
0.1 seconds
```

and sends another request.

If the server keeps returning 429, the script continues indefinitely.

Even worse, if the server returns:

```text
HTTP 400
```

the original code catches the exception and tries again forever even though the request itself is invalid.

### Fix

The fixed version:

* adds a 5-second timeout
* limits retries to 5 attempts
* handles 429 separately
* respects `Retry-After`
* retries 500/503
* uses exponential backoff
* stops after the retry limit
* does not intentionally retry permanent HTTP errors such as 400/401/404

### Fixed in review_me.py?

**YES**

### Evidence

`review_me.py`:

```python
MAX_RETRIES = 5
REQUEST_TIMEOUT = 5
```

and:

```python
timeout=REQUEST_TIMEOUT
```

and bounded:

```python
for attempt in range(1, MAX_RETRIES + 1):
```

The fixed code also handles:

```python
if r.status_code == 429:
```

and:

```python
if r.status_code in (500, 503):
```

---

# Problem 2 — Wrong OSA calculation: `qty` is used instead of `in_stock`

**Severity:** CRITICAL

### What the code does

`city_osa()` reads:

```python
SELECT qty
FROM inventory
```

and determines availability using:

```python
if qty > 0
```

### Why is this wrong?

The QuickMart API explicitly defines `in_stock` as the availability flag.

`qty` is only informational.

The mock server intentionally contains **ghost stock**:

```text
in_stock = true
qty = 0
```

Therefore, using `qty > 0` can produce the wrong OSA number.

### Concrete example

Suppose QuickMart returns:

```text
sku_id: SKU-001
in_stock: true
qty: 0
```

The correct interpretation is:

```text
Product is in stock
```

because `in_stock` is `true`.

But `city_osa()` checks:

```python
qty > 0
```

which becomes:

```text
0 > 0 → false
```

The product is incorrectly counted as out of stock.

### Fix

The calculation should use:

```python
in_stock
```

instead of:

```python
qty
```

### Fixed in review_me.py?

**NO — intentionally left unfixed**

### Why?

The assignment specifically says to fix only the 2–3 most serious problems in `review_me.py`.

This problem is documented here as a critical finding, but changing the entire `city_osa()` calculation would also require addressing the related city-weighting, timezone, missing-data, and completeness problems.

The production implementation in `sweep.py`/`app.py` uses the correct `in_stock` field.

### Evidence

Problematic code remains in:

```python
city_osa()
```

```python
SELECT qty
FROM inventory
```

and:

```python
if qty > 0
```

---

# Problem 3 — Incorrect city OSA aggregation

**Severity:** CRITICAL

### What the code does

The code calculates an OSA percentage separately for every store:

```python
in_stock / len(rows)
```

and then calculates:

```python
sum(per_store) / len(per_store)
```

This means it gives every store the same weight.

### Why is this wrong?

The assignment defines OSA as:

```text
total in-stock observations
--------------------------- × 100
total observations
```

The number of observations can differ between stores.

Therefore, store percentages cannot simply be averaged.

### Concrete example

Suppose:

```text
Store A:
9 in stock out of 10
= 90%

Store B:
1 in stock out of 2
= 50%
```

The current code calculates:

```text
(90% + 50%) / 2
= 70%
```

But the required calculation is:

```text
(9 + 1) / (10 + 2) × 100
= 83.33%
```

Therefore the current implementation produces the wrong business number.

### Fix

Count all valid observations together:

```text
total in-stock observations
---------------------------
total observations
```

Do not average the individual store percentages.

### Fixed in review_me.py?

**NO**

### Evidence

The problematic logic is in:

```python
city_osa()
```

```python
per_store.append(
    in_stock / len(rows)
    if rows
    else 0.0
)
```

followed by:

```python
sum(per_store) / len(per_store)
```

---

# Problem 4 — Mutable default argument

**Severity:** HIGH

### What the original code did

The original function was:

```python
def fetch_inventory(store_id, as_of, cursor="0", results=[]):
```

The list `results` is created only once when Python creates the function.

It is not recreated for every function call.

### Concrete example

Suppose the first call collects:

```text
MUM-001
SKU-001
SKU-002
SKU-003
```

Then a second independent call for:

```text
MUM-002
```

can reuse the same default list.

MUM-002's results could therefore contain MUM-001's results.

That can produce incorrect inventory and incorrect OSA.

### Fix

Use:

```python
results=None
```

and initialize it inside the function:

```python
if results is None:
    results = []
```

### Fixed in review_me.py?

**YES**

### Evidence

Current `review_me.py` contains:

```python
def fetch_inventory(store_id, as_of, cursor="0", results=None):
```

and:

```python
if results is None:
    results = []
```

---

# Problem 5 — Timezone-less `datetime.utcnow()`

**Severity:** HIGH

### What the original code does

At the bottom of the script:

```python
datetime.utcnow().isoformat()
```

is used.

This produces a timestamp without timezone information.

For example:

```text
2026-10-02T17:12:07.300078
```

There is no `Z` or `+00:00`.

### Why is this a problem?

The QuickMart API requires `as_of` to be an ISO-8601 timestamp **with a timezone**.

The mock server rejects a timezone-less timestamp.

### Actual evidence

We ran:

```text
python review_me.py
```

and the actual server returned:

```text
400 Client Error: Bad Request
```

for:

```text
as_of=2026-10-02T17:12:07.300078
```

Therefore this is a reproduced problem, not just a theoretical concern.

### Fix

Use a timezone-aware UTC datetime, for example:

```python
datetime.now(timezone.utc)
```

and serialize it with the UTC timezone.

### Fixed in review_me.py?

**NO**

### Why?

Only the requested 2–3 targeted review fixes were made.

### Evidence

Current code still contains:

```python
datetime.utcnow().isoformat()
```

---

# Problem 6 — No detection of partial responses or soft bans

**Severity:** HIGH

### What the code does

After receiving a successful HTTP response, it immediately processes:

```python
body["items"]
```

It does not check:

```text
partial
meta.source
```

### Why is this dangerous?

The QuickMart server can return HTTP 200 while the data is actually degraded.

A soft-ban response can contain:

```text
HTTP 200
meta.source = "edge"
```

and may contain empty or truncated data.

The response can therefore look successful at the HTTP level while containing incomplete information.

### Concrete example

Suppose the real inventory contains:

```text
30 products
```

but a soft-ban response returns:

```text
HTTP 200
items = 8 products
meta.source = "edge"
partial = false
```

The original code accepts those 8 products as if they were the complete snapshot.

The resulting OSA could therefore be wrong.

### Fix

Check:

```python
body.get("partial")
```

and:

```python
body.get("meta", {}).get("source")
```

A degraded response should not be treated as a valid complete snapshot.

### Fixed in review_me.py?

**NO**

### Evidence

No `partial` or `meta.source` validation exists in `fetch_inventory()`.

---

# Problem 7 — SQL is constructed using string interpolation

**Severity:** HIGH

### What the original code did

The original `save()` constructed SQL using f-strings:

```python
f"INSERT INTO inventory VALUES ('{store_id}', '{it['sku_id']}', '{it['name']}', ...)"
```

### Concrete example

Suppose a product name is:

```text
Bob's Milk
```

The generated SQL can contain:

```sql
'Bob's Milk'
```

The apostrophe can terminate the SQL string early and cause an SQL syntax error.

More generally, inserting external data directly into SQL is unsafe and makes escaping the data the programmer's responsibility.

### Fix

Use parameterized SQL:

```python
VALUES (?, ?, ?, ?, ?, ?)
```

and pass the values separately.

### Fixed in review_me.py?

**YES**

### Evidence

Current `save()` uses:

```python
VALUES (?, ?, ?, ?, ?, ?)
```

with values supplied separately.

---

# Problem 8 — No primary key or idempotency

**Severity:** HIGH

### What the code does

The temporary `inventory` table created by `review_me.py` has no primary key:

```python
CREATE TABLE IF NOT EXISTS inventory (
    store_id TEXT,
    sku_id TEXT,
    name TEXT,
    in_stock INT,
    qty INT,
    observed_at TEXT
)
```

### Why is this a problem?

Running the same operation twice can insert the same observations again.

### Concrete example

Suppose one run stores:

```text
MUM-001 | SKU-001
```

Running the same sweep again can insert another:

```text
MUM-001 | SKU-001
```

The database now contains two observations that may actually represent the same snapshot.

That can inflate the denominator and change OSA.

### Fix

The real implementation uses a primary key based on:

```text
as_of + store_id + sku_id
```

and uses conflict-safe insertion.

### Fixed in review_me.py?

**NO**

### Evidence

The review script's `inventory` table has no primary key.

---

# Problem 9 — No completeness tracking

**Severity:** HIGH

### What the code does

The script only saves product rows.

It does not record whether a particular store/sweep was:

```text
complete
```

or:

```text
incomplete
```

and it does not record a reason.

### Why is this a problem?

Missing data can accidentally be treated as zero availability.

For example:

```text
Expected: 30 products
Received: 0 products
```

The code cannot tell whether:

```text
the store genuinely had no products
```

or:

```text
the request failed
```

or:

```text
the server returned degraded data
```

### Fix

Store a separate store-sweep record containing:

```text
store
sweep timestamp
status
reason
```

The production implementation does this using the `store_sweeps` table.

### Fixed in review_me.py?

**NO**

---

# Problem 10 — Incorrect UTC/IST date handling

**Severity:** MEDIUM/HIGH

### What the code does

It uses:

```python
substr(observed_at, 1, 10)
```

to determine the date.

It also uses:

```python
date.today() - timedelta(days=1)
```

### Why is this a problem?

The assignment defines the requested date as an **IST calendar day**.

A UTC timestamp near midnight can belong to a different calendar day in IST.

### Concrete example

A sweep at:

```text
2026-09-27T19:00:00Z
```

is:

```text
2026-09-28T00:30:00+05:30
```

in IST.

Therefore that sweep belongs to:

```text
2026-09-28
```

not:

```text
2026-09-27
```

Simply taking the first ten characters of the UTC timestamp gives the wrong calendar day.

### Fix

Convert timestamps to IST before determining the calendar date.

The production implementation stores the IST calendar date for every sweep.

### Fixed in review_me.py?

**NO**

---

# Summary of Targeted Fixes

The assignment says not to rewrite `review_me.py`.

Only these targeted fixes were made:

| Problem                                      | Fixed?               |
| -------------------------------------------- | -------------------- |
| Infinite/unbounded retry and missing timeout | YES                  |
| `in_stock` vs `qty`                          | NO in `review_me.py` |
| Incorrect city aggregation                   | NO                   |
| Mutable default argument                     | YES                  |
| Timezone-less datetime                       | NO                   |
| Partial/soft-ban detection                   | NO                   |
| SQL string interpolation                     | YES                  |
| Missing primary key/idempotency              | NO                   |
| Missing completeness tracking                | NO                   |
| UTC/IST date handling                        | NO                   |

The three actual code changes are:

1. Bounded retries with timeout and transient-error handling.
2. Parameterized SQL.
3. Mutable default argument fix.

The remaining problems are intentionally documented rather than implemented because the assignment explicitly says to fix only the top 2–3 problems.

---

# Important Note About the OSA Fix

Although `in_stock` is a critical problem identified during the review, it was **not changed inside `review_me.py`** because changing only that line would leave the surrounding city aggregation, missing-data, completeness, and timezone problems unresolved.

The main production implementation (`sweep.py` and `app.py`) uses `in_stock` correctly.

---

# Review Execution Result

The script was actually executed with `mock_portal.py` running.

Command:

```text
python review_me.py
```

Result:

```text
HTTP 400 Bad Request
```

The failing request contained:

```text
as_of=2026-10-02T17:12:07.300078
```

The timestamp has no timezone.

This confirms the timezone problem described above is reproducible against the provided mock API.

---

# Overall Review Conclusion

`review_me.py` contains multiple correctness and reliability problems. The most important business-level risks are incorrect OSA calculation, unsafe handling of incomplete/degraded data, and retry behavior that can hang or overload the API.

The file was not rewritten from scratch. Only three targeted code-quality/reliability fixes were made, while the remaining problems are explicitly documented for the review exercise.
