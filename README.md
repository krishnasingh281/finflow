# FinFlow — Transaction Integrity & Leaderboard System

A Django REST API that handles financial transactions with built-in
idempotency, concurrent-safe updates, and a multi-factor ranking system.

---

## Project Structure

```
finflow/
├── backend/
│   ├── finflow/          # Django project config
│   ├── transactions/     # Main app (models, views, ranking)
│   └── manage.py
├── frontend/             # Static HTML/CSS/JS dashboard
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## APIs

### POST /api/transaction

Submit a credit or debit transaction.

**Request Body:**
```json
{
    "user_id": "user_alice",
    "amount": 500.00,
    "transaction_type": "credit",
    "description": "Monthly salary",
    "idempotency_key": "unique-key-per-request"
}
```

**Validation Rules:**
- `user_id`: required, non-empty, no SQL injection characters
- `amount`: required, > 0, ≤ 1,000,000
- `transaction_type`: must be "credit" or "debit"
- `idempotency_key`: optional; if provided, duplicate requests return the original response

**Concurrent Safety:**
Uses Django's `select_for_update()` to lock the user row during writes,
and `F()` expressions for atomic increments — no lost updates.

---

### GET /api/summary/:userId

Returns aggregated stats for a user.

**Response:**
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
        "current_rank": 2
    }
}
```

---

### GET /api/ranking?limit=10&offset=0

Returns the leaderboard sorted by composite score.

**Scoring Formula:**
```
score = (0.40 × volume_score) + (0.30 × activity_score) + (0.30 × reliability_score)
```

- **Volume Score (40%)**: Normalized net balance (credit - debit) vs. highest user
- **Activity Score (30%)**: Normalized transaction count vs. most active user
- **Reliability Score (30%)**: Starts at 1.0. Drops 5% per bad/duplicate request. Floor: 0.1

This multi-factor scoring prevents:
- A single whale transaction dominating the leaderboard
- Bots spamming transactions to climb ranks
- Users gaming one dimension while ignoring others

---

## Assumptions & Design Decisions

1. **SQLite** is used for simplicity. In production, switch to PostgreSQL.
2. **Idempotency keys** are optional. If not provided, every request is treated as unique.
3. **Reliability penalty** applies to the user_id in the request payload, even if the request fails validation. This means a typo in the amount still counts against you — intentional, to discourage careless retries.
4. **Scores are relative** — adding a new high-volume user will shift everyone else's scores down slightly. This is by design (normalized leaderboard).
5. **UserSummary** is a denormalized table maintained alongside transactions. This trades a small write overhead for much faster reads on `/summary` and `/ranking`.

---

## Local Setup

```bash
# create and activate virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# install dependencies
pip install -r requirements.txt

# run migrations
cd backend
python manage.py migrate

# create superuser (optional, for /admin)
python manage.py createsuperuser

# start the server
python manage.py runserver
```

Then open `frontend/index.html` in your browser (or serve it with any static server).

---

## Google Cloud Run Deployment

```bash
# 1. build the Docker image
docker build -t finflow .

# 2. tag it for Google Container Registry
docker tag finflow gcr.io/YOUR_PROJECT_ID/finflow

# 3. push to GCR
docker push gcr.io/YOUR_PROJECT_ID/finflow

# 4. deploy to Cloud Run
gcloud run deploy finflow \
    --image gcr.io/YOUR_PROJECT_ID/finflow \
    --platform managed \
    --region us-central1 \
    --allow-unauthenticated \
    --set-env-vars DJANGO_SECRET_KEY=your-secret-key-here,DEBUG=False
```

After deployment, update `API_BASE` in `frontend/app.js` with your Cloud Run URL.

For the frontend, deploy to Firebase Hosting or any static host:
```bash
firebase init hosting
firebase deploy
```

---

## Edge Cases Handled

| Scenario | How it's handled |
|----------|-----------------|
| Duplicate transaction (same idempotency key) | Returns original response, no new DB row |
| Two requests for same user at exact same time | `select_for_update()` serializes them |
| Negative amount | Rejected with 400 |
| Extremely large amount (> 1M) | Rejected with 400 |
| Empty user_id | Rejected with 400 |
| SQL injection in user_id | Detected and rejected |
| User not found in /summary | Returns 404 with clear message |
| Invalid limit/offset in /ranking | Returns 400 with clear message |
| Server error during transaction | Returns 500, no partial writes (atomic block) |
