import uuid
from django.db import models
from django.utils import timezone


class IdempotencyKey(models.Model):
    """
    We store every idempotency key that comes in with a POST /transaction.
    If the same key comes again, we just return the original response
    instead of processing the transaction twice.

    This handles the case where a client sends the same request twice
    due to a network timeout or retry logic on their end.
    """

    key = models.CharField(max_length=255, unique=True)
    response_body = models.TextField()  # we store the JSON response as a string
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'idempotency_keys'

    def __str__(self):
        return self.key


class Transaction(models.Model):
    """
    Each row here is one transaction submitted by a user.
    We track both successful and failed transactions because
    the ranking logic penalizes users who abuse the system.
    """

    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILED, 'Failed'),
    ]

    TRANSACTION_CREDIT = 'credit'
    TRANSACTION_DEBIT = 'debit'

    TYPE_CHOICES = [
        (TRANSACTION_CREDIT, 'Credit'),
        (TRANSACTION_DEBIT, 'Debit'),
    ]

    transaction_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    user_id = models.CharField(max_length=100, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    description = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_SUCCESS)
    idempotency_key = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'transactions'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user_id} | {self.transaction_type} | {self.amount}'


class UserSummary(models.Model):
    """
    This is a denormalized summary table. Instead of computing
    totals from the transactions table every time someone calls
    GET /summary/:userId, we keep a running total here.

    We update this atomically using F() expressions so concurrent
    requests don't cause race conditions or lost updates.
    """

    user_id = models.CharField(max_length=100, unique=True, db_index=True)
    total_credit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_debit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    transaction_count = models.IntegerField(default=0)
    failed_attempt_count = models.IntegerField(default=0)

    # reliability_score goes from 0.0 to 1.0
    # it drops when a user sends bad/duplicate requests
    # this is what makes our ranking unique — spammers rank lower
    reliability_score = models.FloatField(default=1.0)

    # composite_rank_score is computed each time a transaction happens
    # so the ranking endpoint doesn't have to do heavy math on every call
    composite_rank_score = models.FloatField(default=0.0)

    last_updated = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'user_summaries'

    def __str__(self):
        return f'Summary({self.user_id}) | score={self.composite_rank_score:.2f}'
