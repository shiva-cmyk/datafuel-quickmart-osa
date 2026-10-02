# AI_LOG.md

# DataFuel QuickMart OSA Assignment — AI Usage Log

## 1. AI Tools Used

AI assistance was used during development for:

* understanding the assignment requirements
* explaining the QuickMart API behavior
* designing the SQLite schema
* reviewing Python code
* identifying edge cases
* suggesting tests
* explaining HTTP retry behavior
* explaining pagination
* explaining UTC and IST handling
* reviewing `review_me.py`
* preparing documentation and interview explanations

The AI was not treated as the source of truth.

The original assignment files, especially `README.md`, `API.md`, and the provided `mock_portal.py`, were treated as the source of truth.

---

# 2. Important Prompts Used

## Prompt 1 — Assignment Understanding

A major prompt asked the AI to:

> Read the complete original assignment and explain exactly what needs to be built, without assuming that anything is already completed.

The purpose was to understand:

* scraper requirements
* API requirements
* database requirements
* OSA calculation
* coverage
* retry behavior
* soft-ban behavior
* tests
* documentation
* submission requirements

The assignment was explicitly treated as the source of truth.

---

## Prompt 2 — Project Audit

A major prompt asked the AI to:

> Inspect the actual project files and compare them against the original assignment. Do not claim something is completed unless the actual code, tests, database, or documentation proves it.

This led to checking:

* `sweep.py`
* `app.py`
* `db.py`
* tests
* database behavior
* `review_me.py`
* documentation
* Git/submission files

The goal was to avoid claiming that a feature existed merely because a filename or comment suggested it.

---

## Prompt 3 — `review_me.py` Review

The AI was asked to review the intentionally bad `review_me.py`, identify real problems, and fix only the 2–3 most serious problems.

The provided assignment checklist was then used to verify the review rather than blindly accepting AI suggestions.

---

# 3. AI Mistake #1 — Incorrect Priority for `review_me.py` Fixes

## What AI initially suggested

The AI initially selected:

1. infinite retry/no timeout
2. SQL string interpolation
3. mutable default argument

as the three targeted fixes.

These are real problems, but the assignment's own review checklist makes clear that **wrong OSA numbers are especially important**.

The assignment specifically highlights:

```text
city_osa()
```

and asks whether it uses:

```text
in_stock
```

or:

```text
qty
```

because the mock server intentionally contains ghost-stock cases.

## How the mistake was caught

The assignment was reread carefully.

The API documentation states that:

```text
in_stock
```

is QuickMart's availability flag, while:

```text
qty
```

is informational.

The mock server also intentionally creates cases where:

```text
in_stock = true
qty = 0
```

Therefore using `qty > 0` can produce a wrong OSA number.

This showed that the AI's initial prioritization did not fully follow the assignment's emphasis on correctness of business numbers.

## Correction

The review was revised so that the `in_stock` problem is explicitly documented as a critical finding.

Only the requested 2–3 fixes are made in `review_me.py`; the remaining correctness issues are documented rather than turning the review file into a complete rewrite.

---

# 4. AI Mistake #2 — Incorrect Assumption About the Review Script's Successful Execution

## What happened

The AI initially provided a modified `review_me.py` and expected it to be testable against the running mock API.

However, the script still contained:

```text
datetime.utcnow().isoformat()
```

which creates a timezone-less timestamp.

## How the mistake was caught

The script was actually executed:

```text
python review_me.py
```

The mock API returned:

```text
400 Bad Request
```

The actual request contained:

```text
as_of=2026-10-02T17:12:07.300078
```

There was no timezone such as:

```text
Z
```

or:

```text
+00:00
```

The API documentation explicitly requires a timezone-aware ISO-8601 timestamp.

## Correction

The issue was not hidden or falsely reported as successful.

It was documented as a real problem in `REVIEW.md`.

The timezone problem was intentionally left unfixed because the assignment requires only 2–3 targeted fixes to `review_me.py`.

---

# 5. AI Mistake #3 — Risk of Treating Code Presence as Proof of Completion

During the project audit, the AI was instructed not to infer completion from filenames or comments.

For example:

```text
sweep.py exists
```

does not automatically prove:

```text
pagination works
```

Similarly:

```text
tests exist
```

does not prove:

```text all tests pass
```

## How this was corrected

Actual commands were used to verify behavior.

For example:

```text
python -m pytest -q
```

was run and produced:

```text
16 passed
```

The six required sweep timestamps were also actually executed.

API behavior was tested rather than assumed.

This principle was applied throughout the project:

```text
Code exists ≠ feature proven
```

---

# 6. AI Mistake #4 — Initial Risk of Using an Ideal Design Instead of the Actual Assignment

AI-generated explanations can naturally describe a cleaner or more complete architecture than the one actually implemented.

This assignment explicitly requires reviewing the real project.

Therefore, whenever an ideal solution differed from the actual implementation, the actual implementation was treated as authoritative for the audit.

Examples include:

* incomplete store handling
* soft-ban behavior
* timezone normalization
* OSA calculation
* review script limitations

The documentation was written to distinguish:

```text
implemented
```

from:

```text
implemented but not verified
```

and:

```text
not implemented
```

---

# 7. Verification Rules Used

The following rules were used when checking AI-generated suggestions:

## Rule 1

Never assume a requirement is implemented because a file exists.

## Rule 2

Never claim tests pass without running them.

## Rule 3

Never invent database row counts.

## Rule 4

Never invent API responses.

## Rule 5

Never assume HTTP 200 means the inventory snapshot is complete.

## Rule 6

Check the actual `mock_portal.py` behavior before implementing error handling.

## Rule 7

Use `API.md` to determine the meaning of API fields.

## Rule 8

Use actual test results to verify behavior.

## Rule 9

Use the original assignment to decide what must be implemented.

## Rule 10

Do not modify `mock_portal.py`.

---

# 8. Human Verification

AI suggestions were manually checked against:

* `README.md`
* `API.md`
* `mock_portal.py`
* `review_me.py`
* actual project source code
* pytest results
* actual QuickMart server responses
* SQLite database behavior

This was especially important because the mock server intentionally contains unusual behavior:

* 429 rate limiting
* 500/503 errors
* slow requests
* soft bans
* partial responses
* duplicate inventory items
* mixed timezone timestamps
* ghost stock
* SKU name changes
* store launch timing

The unusual behavior means assumptions based only on normal API behavior would be unsafe.

---

# 9. Final AI-Use Principle

AI was used as a development and reasoning assistant, not as the authority.

The authority hierarchy for this assignment was:

```text
Original Assignment
       ↓
README.md / API.md
       ↓
Provided mock_portal.py
       ↓
Actual project code
       ↓
Actual tests and runtime results
       ↓
AI suggestions
```

If an AI suggestion conflicted with the actual assignment or observed behavior, the assignment and observed behavior were followed.
