"""
ranking.py — FinFlow's multi-factor scoring engine

The composite score uses three factors:

  Factor 1 — Net Volume Score (40% weight)
      This is the net amount a user has moved through the system.
      (total_credit - total_debit), normalized against the highest
      volume user so scores are relative, not absolute.

  Factor 2 — Activity Score (30% weight)
      How frequently a user transacts. A user with 100 small
      transactions is considered more "active" than one with
      1 large transaction. Again normalized.

  Factor 3 — Reliability Score (30% weight)
      This penalizes users who send duplicate requests, invalid
      inputs, or attempt to manipulate the system. Starts at 1.0
      and decays each time the user causes a bad request.

Final formula:
    score = (0.40 * volume_score) + (0.30 * activity_score) + (0.30 * reliability_score)

Range: 0.0 to 100.0 (we multiply by 100 at the end for readability)
"""

from decimal import Decimal


def compute_reliability_decay(current_score, failed_count):
    """
    Each time a user sends a bad/duplicate request, their reliability
    drops by 5%, but it can never go below 0.1 — we don't want to
    permanently destroy someone's score for a few mistakes.
    """

    penalty_per_failure = 0.05
    new_score = current_score - (penalty_per_failure * failed_count)

    # floor at 0.1 so even the worst abusers retain a tiny score
    if new_score < 0.1:
        new_score = 0.1

    return round(new_score, 4)


def normalize_value(value, max_value):
    """
    Simple min-max normalization where min is 0.
    Returns a float between 0.0 and 1.0.
    If max_value is 0 (nobody has any volume), return 0.
    """

    if max_value == 0:
        return 0.0

    result = float(value) / float(max_value)

    # clamp just in case of floating point weirdness
    if result > 1.0:
        result = 1.0
    if result < 0.0:
        result = 0.0

    return result


def compute_composite_score(net_volume, max_net_volume, tx_count, max_tx_count, reliability):
    """
    The main scoring function. Takes raw values and the current
    system maximums, returns a score between 0 and 100.

    net_volume    — (credit - debit) for this user, can be negative
    max_net_volume — highest net_volume across all users
    tx_count      — number of successful transactions
    max_tx_count  — highest tx_count across all users
    reliability   — float 0.1 to 1.0
    """

    WEIGHT_VOLUME = 0.40
    WEIGHT_ACTIVITY = 0.30
    WEIGHT_RELIABILITY = 0.30

    # for net volume we treat negatives as 0 — you don't get
    # credit for spending more than you earn in this system
    adjusted_volume = max(Decimal('0'), net_volume)

    volume_score = normalize_value(adjusted_volume, max_net_volume)
    activity_score = normalize_value(tx_count, max_tx_count)
    reliability_score = reliability  # already in 0.0–1.0 range

    raw_score = (
        (WEIGHT_VOLUME * volume_score)
        + (WEIGHT_ACTIVITY * activity_score)
        + (WEIGHT_RELIABILITY * reliability_score)
    )

    # multiply by 100 so the leaderboard shows readable numbers like 73.5
    final_score = raw_score * 100

    return round(final_score, 2)


def recalculate_all_scores(user_summaries):
    """
    Called after every transaction to keep all scores up to date.
    Finds the current maximums across all users, then recomputes
    each user's score.

    Returns a list of (summary_object, new_score) tuples.
    The caller is responsible for saving them.
    """

    if not user_summaries:
        return []

    # find the current maximums so we can normalize
    all_net_volumes = []
    all_tx_counts = []

    for summary in user_summaries:
        net_vol = summary.total_credit - summary.total_debit
        net_vol = max(Decimal('0'), net_vol)
        all_net_volumes.append(net_vol)
        all_tx_counts.append(summary.transaction_count)

    max_net_volume = max(all_net_volumes) if all_net_volumes else Decimal('0')
    max_tx_count = max(all_tx_counts) if all_tx_counts else 0

    results = []
    for summary in user_summaries:
        net_vol = summary.total_credit - summary.total_debit
        new_score = compute_composite_score(
            net_volume=net_vol,
            max_net_volume=max_net_volume,
            tx_count=summary.transaction_count,
            max_tx_count=max_tx_count,
            reliability=summary.reliability_score,
        )
        results.append((summary, new_score))

    return results
