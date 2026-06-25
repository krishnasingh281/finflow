# FinFlow — Transaction Integrity & Leaderboard System

A Django REST API that handles financial transactions with built-in idempotency,
concurrent-safe updates, and a multi-factor ranking system.

**Live Demo:**
- Frontend: https://finflow-five-gamma.vercel.app
- Backend:  https://finflow-api-d5wx.onrender.com

---

## Tech Stack

| Layer     | Technology                        |
|-----------|-----------------------------------|
| Backend   | Python 3.11, Django 4.2, Django REST Framework |
| Database  | SQLite (file-based, zero config)  |
| Frontend  | Vanilla HTML + CSS + JavaScript   |
| Hosting   | Render (backend), Vercel (frontend) |

---

## How to Run Locally

```bash
# 1. Clone the repo
git clone https://github.com/krishnasingh281/finflow.git
cd finflow

# 2. Create and activate virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run migrations (creates db.sqlite3 automatically)
cd backend
python manage.py migrate

# 5. Start the server
python manage.py runserver

# 6. Open the frontend
# Just open frontend/index.html in your browser
# It auto-detects localhost and points to http://127.0.0.1:8000/api
```

The API is now available at `http://127.0.0.1:8000/api/`

---

## Database Schema

Three tables power the entire system:

### 1. `transactions`
Stores every individual transaction submitted.

| Column           | Type         | Notes                              |
|------------------|--------------|------------------------------------|
| transaction_id   | UUID         | Auto-generated unique ID           |
| user_id          | VARCHAR(100) | Indexed for fast lookups           |
| amount           | DECIMAL(12,2)| Must be > 0 and ≤ 1,000,000       |
| transaction_type | VARCHAR(10)  | Either "credit" or "debit"         |
| description      | VARCHAR(255) | Optional                           |
| status           | VARCHAR(10)  | "success" or "failed"              |
| idempotency_key  | VARCHAR(255) | Stored for reference               |
| created_at       | DATETIME     | Auto-set on creation               |

### 2. `user_summaries`
A denormalized running-total table. Updated atomically after every transaction.
This avoids expensive aggregation queries on every GET /summary or GET /ranking call.

| Column               | Type          | Notes                                  |
|----------------------|---------------|----------------------------------------|
| user_id              | VARCHAR(100)  | Unique, indexed                        |
| total_credit         | DECIMAL(14,2) | Running sum of all credits             |
| total_debit          | DECIMAL(14,2) | Running sum of all debits              |
| transaction_count    | INTEGER       | Count of successful transactions       |
| failed_attempt_count | INTEGER       | Count of bad/duplicate requests        |
| reliability_score    | FLOAT         | 0.1 – 1.0, decays on abuse            |
| composite_rank_score | FLOAT         | Pre-computed score (0–100)             |
| last_updated         | DATETIME      | Timestamp of last change               |

### 3. `idempotency_keys`
Stores previously processed idempotency keys and the exact response returned.
Used to return identical responses on duplicate requests without re-processing.

| Column        | Type         | Notes                          |
|---------------|--------------|--------------------------------|
| key           | VARCHAR(255) | Unique constraint              |
| response_body | TEXT         | Full JSON response as string   |
| created_at    | DATETIME     | When this key was first seen   |

### Data Flow (POST /transaction)

```
Client Request
     │
     ▼
Input Validation (serializer)
     │ fail → 400 + penalize reliability score
     │
     ▼
Idempotency Check (lookup idempotency_keys table)
     │ found → return cached response (no DB write)
     │
     ▼
Atomic DB Transaction (select_for_update locks user row)
     │
     ├── INSERT into transactions table
     │
     └── UPDATE user_summaries using F() expressions
              (atomic increment, no race condition)
     │
     ▼
Recompute composite_rank_score for ALL users
     │
     ▼
Store idempotency_key + response
     │
     ▼
Return 201 Created
```

---

## API Reference

### POST /api/transaction

Submit a credit or debit transaction.

**Request Body:**
```json
{
    "user_id": "user_alice",
    "amount": 500.00,
    "transaction_type": "credit",
    "description": "Monthly salary",
    "idempotency_key": "unique-uuid-per-request"
}
```

**Validation Rules:**
- `user_id` — required, non-empty, no SQL injection characters (`;`, `--`, `DROP`, etc.)
- `amount` — required, must be > 0 and ≤ 1,000,000
- `transaction_type` — must be exactly `"credit"` or `"debit"`
- `idempotency_key` — optional; if provided and already seen, original response is returned

**Success Response (201):**
```json
{
    "success": true,
    "transaction": {
        "transaction_id": "550e8400-e29b-41d4-a716-446655440000",
        "user_id": "user_alice",
        "amount": "500.00",
        "transaction_type": "credit",
        "description": "Monthly salary",
        "status": "success",
        "created_at": "2024-01-15T10:30:00Z"
    },
    "message": "Transaction recorded successfully."
}
```

**Error Response (400):**
```json
{
    "success": false,
    "error": "Validation failed",
    "details": {
        "amount": ["Amount must be greater than zero."]
    }
}
```

---

### GET /api/summary/:userId

Returns aggregated financial stats for a single user.

**Example:** `GET /api/summary/user_alice`

**Response (200):**
```json
{
    "success": true,
    "summary": {
        "user_id": "user_alice",
        "total_credit": "1500.00",
        "total_debit": "300.00",
        "net_balance": "1200.00",
        "transaction_count": 5,
        "reliability_score": 0.95,
        "composite_rank_score": 67.4,
        "current_rank": 2,
        "last_updated": "2024-01-15T10:30:00Z"
    }
}
```

**Error (404):** Returned when no transactions exist for the given user_id.

---

### GET /api/ranking?limit=10&offset=0

Returns the leaderboard sorted by composite score. Supports pagination.

**Query Params:**
- `limit` — number of users to return (1–100, default 10)
- `offset` — how many users to skip (for pagination, default 0)

**Response (200):**
```json
{
    "success": true,
    "total_users": 42,
    "limit": 10,
    "offset": 0,
    "scoring_factors": {
        "volume_weight": "40%",
        "activity_weight": "30%",
        "reliability_weight": "30%"
    },
    "ranking": [
        {
            "rank": 1,
            "user_id": "user_alice",
            "composite_rank_score": 85.0,
            "net_balance": "1200.00",
            "transaction_count": 5,
            "reliability_score": 1.0
        }
    ]
}
```

---

## How Ranking Is Calculated

The leaderboard uses a **weighted multi-factor composite score** (0–100):

```
score = (0.40 × volume_score) + (0.30 × activity_score) + (0.30 × reliability_score)
```

Each factor is normalized relative to the best user in that category:

| Factor | Weight | Formula |
|--------|--------|---------|
| **Volume Score** | 40% | `user_net_balance / max_net_balance_across_all_users` |
| **Activity Score** | 30% | `user_tx_count / max_tx_count_across_all_users` |
| **Reliability Score** | 30% | Starts at 1.0, drops 5% per bad request, floor at 0.1 |

**Why three factors?**

A purely volume-based ranking is easy to game — one large transaction puts you at the top.
By adding activity (frequency) and reliability (behavior quality), the system rewards
consistent, legitimate usage rather than a single big number.

**Example:**
```
User Alice: credit=1200, tx_count=5,  reliability=1.0  → score = 85.0
User Bob:   credit=800,  tx_count=10, reliability=0.8  → score = 80.7
User Spam:  credit=1100, tx_count=8,  reliability=0.1  → score = 63.7
```
Spam sent invalid requests repeatedly, so despite high volume they rank last.

**Reliability Decay:**
- Each invalid/duplicate request: `-5%` reliability
- Floor: `0.1` (never reaches 0, small mistakes aren't permanent)
- Scores are relative — adding a new top user shifts everyone else down slightly

---

## How Duplicate Requests Are Prevented

The client can send an `idempotency_key` (any unique string, typically a UUID) with each request.

**Flow:**
1. On receiving a request, we check the `idempotency_keys` table for that key
2. If found → return the **exact same response** that was returned the first time, no DB writes
3. If not found → process normally, then store the key + response

**Why this matters:**
- Network timeouts cause clients to retry. Without idempotency, a retry creates a duplicate transaction.
- With idempotency, retrying is safe — same key = same result.

**Example:**
```
Request 1 (key=abc123) → processes, stores key → returns 201
Request 2 (key=abc123) → finds key in DB → returns same 201, no new transaction
```

---

## How Concurrency Is Handled

Two Django features prevent data corruption under simultaneous requests:

### 1. `select_for_update()`
When updating a user's summary, we lock that user's row first:
```python
UserSummary.objects.select_for_update().get_or_create(user_id=...)
```
If two requests for `user_alice` arrive simultaneously, the second one waits
for the first to finish before reading or writing. No lost updates.

### 2. `F()` Expressions
We never read a value into Python and write it back. Instead:
```python
# Wrong way (race condition):
summary.total_credit += amount  # two threads both read 100, both write 150
summary.save()

# Right way (atomic):
UserSummary.objects.filter(user_id=...).update(
    total_credit=F('total_credit') + amount  # database does the math
)
```
The increment happens inside the database in a single atomic operation.

---

## Edge Cases Handled

| Scenario | Response |
|----------|----------|
| Amount is 0 or negative | 400 — "Amount must be greater than zero" |
| Amount > 1,000,000 | 400 — "Exceeds maximum allowed limit" |
| Empty or whitespace user_id | 400 — "user_id cannot be empty" |
| SQL injection attempt in user_id | 400 — "user_id contains invalid characters" |
| Duplicate idempotency_key | 200 — original response returned, no new record |
| User not found in /summary | 404 — clear error message |
| Invalid limit/offset in /ranking | 400 — "limit must be between 1 and 100" |
| Partial DB failure mid-transaction | Full rollback via atomic() block |
| Two simultaneous requests for same user | Serialized via select_for_update() |

---

## Assumptions & Trade-offs

1. **SQLite** is used for simplicity. For production at scale, switch to PostgreSQL.
   SQLite handles concurrent reads well but serializes writes — acceptable for this use case.

2. **Idempotency keys are optional.** If a client doesn't send one, every request is treated
   as unique. This is standard REST practice.

3. **Reliability penalty applies immediately.** Even a typo in the amount counts against
   reliability. This is intentional — it discourages careless automated retries.

4. **Scores are relative.** When a new high-volume user joins, everyone else's volume_score
   decreases slightly. This is a property of normalized leaderboards and is by design.

5. **No authentication.** User identity is just a string field. A production system would
   use JWT tokens or OAuth to verify user_id matches the authenticated user.

6. **Ranking is recomputed after every transaction.** This is O(n) where n = number of users.
   For large user bases, this should move to a background task (Celery) or be computed lazily.