import json
import logging

from django.db import transaction as db_transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import Transaction, UserSummary, IdempotencyKey
from .serializers import (
    TransactionInputSerializer,
    TransactionOutputSerializer,
    UserSummarySerializer,
    RankingEntrySerializer,
)
from .ranking import compute_reliability_decay, recalculate_all_scores

logger = logging.getLogger(__name__)


class TransactionView(APIView):
    """
    POST /api/transaction

    This endpoint does a few things in order:
    1. Validates the request body
    2. Checks if this idempotency_key was already used (if provided)
    3. Wraps everything in a DB transaction so partial writes can't happen
    4. Updates the user's running summary atomically
    5. Recomputes ranking scores for all users
    """

    def post(self, request):

        serializer = TransactionInputSerializer(data=request.data)

        if not serializer.is_valid():
            # log failed attempts — we track these for abuse detection
            user_id = request.data.get('user_id', 'unknown')
            logger.warning(f"Validation failed for user_id={user_id}: {serializer.errors}")

            # if we know who the user is, penalize their reliability score
            if user_id != 'unknown':
                self._penalize_user_reliability(user_id)

            return Response(
                {
                    'success': False,
                    'error': 'Validation failed',
                    'details': serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        validated = serializer.validated_data
        idempotency_key = validated.get('idempotency_key', '').strip()

        # --- Idempotency Check ---
        # if the client sent an idempotency_key, we check if we've seen it before
        if idempotency_key:
            try:
                existing = IdempotencyKey.objects.get(key=idempotency_key)
                # we've seen this before — return the cached response
                # this way the client gets the same result without us
                # creating a duplicate transaction in the DB
                logger.info(f"Duplicate request detected for idempotency_key={idempotency_key}")
                cached_response = json.loads(existing.response_body)
                return Response(cached_response, status=status.HTTP_200_OK)
            except IdempotencyKey.DoesNotExist:
                pass  # first time seeing this key, continue normally

        # --- Atomic DB Transaction ---
        # select_for_update on UserSummary prevents two concurrent requests
        # for the same user from both reading the same old value and
        # both writing their incremented version (lost update problem)
        try:
            with db_transaction.atomic():

                # lock this user's summary row while we update it
                user_summary, created = UserSummary.objects.select_for_update().get_or_create(
                    user_id=validated['user_id'],
                    defaults={
                        'total_credit': 0,
                        'total_debit': 0,
                        'transaction_count': 0,
                        'failed_attempt_count': 0,
                        'reliability_score': 1.0,
                        'composite_rank_score': 0.0,
                    }
                )

                # create the transaction record
                txn = Transaction.objects.create(
                    user_id=validated['user_id'],
                    amount=validated['amount'],
                    transaction_type=validated['transaction_type'],
                    description=validated.get('description', ''),
                    idempotency_key=idempotency_key,
                    status=Transaction.STATUS_SUCCESS,
                )

                # update the summary using F() expressions
                # F() tells Django to do the math in the database itself,
                # not in Python — this avoids race conditions where two
                # threads both read value=100, both add 50, and both write 150
                # instead of the correct 200
                if validated['transaction_type'] == Transaction.TRANSACTION_CREDIT:
                    UserSummary.objects.filter(user_id=validated['user_id']).update(
                        total_credit=F('total_credit') + validated['amount'],
                        transaction_count=F('transaction_count') + 1,
                        last_updated=timezone.now(),
                    )
                else:
                    UserSummary.objects.filter(user_id=validated['user_id']).update(
                        total_debit=F('total_debit') + validated['amount'],
                        transaction_count=F('transaction_count') + 1,
                        last_updated=timezone.now(),
                    )

                # refresh so we have the updated values for ranking
                user_summary.refresh_from_db()

        except Exception as e:
            logger.error(f"DB error during transaction creation: {str(e)}")
            return Response(
                {'success': False, 'error': 'An internal error occurred. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # --- Recompute Rankings ---
        # do this outside the locked atomic block so we don't hold
        # the lock longer than necessary
        self._recompute_all_rankings()

        # build the response
        response_data = {
            'success': True,
            'transaction': TransactionOutputSerializer(txn).data,
            'message': 'Transaction recorded successfully.',
        }

        # make amounts serializable (Decimal isn't JSON serializable by default)
        response_data['transaction']['amount'] = str(response_data['transaction']['amount'])
        response_data['transaction']['transaction_id'] = str(response_data['transaction']['transaction_id'])
        response_data['transaction']['created_at'] = str(response_data['transaction']['created_at'])

        # store this response against the idempotency_key so future
        # duplicate requests get the same answer back
        if idempotency_key:
            IdempotencyKey.objects.create(
                key=idempotency_key,
                response_body=json.dumps(response_data),
            )

        return Response(response_data, status=status.HTTP_201_CREATED)

    def _penalize_user_reliability(self, user_id):
        """
        When a user sends invalid data, we knock their reliability
        score down a little. We use update() with F() here too
        to avoid race conditions.
        """
        try:
            summary, _ = UserSummary.objects.get_or_create(
                user_id=user_id,
                defaults={'reliability_score': 1.0, 'failed_attempt_count': 0}
            )
            UserSummary.objects.filter(user_id=user_id).update(
                failed_attempt_count=F('failed_attempt_count') + 1,
            )
            summary.refresh_from_db()

            new_reliability = compute_reliability_decay(
                summary.reliability_score,
                failed_count=1
            )
            UserSummary.objects.filter(user_id=user_id).update(
                reliability_score=new_reliability,
            )
        except Exception as e:
            logger.error(f"Could not penalize user {user_id}: {str(e)}")

    def _recompute_all_rankings(self):
        """
        Fetches all user summaries and recomputes composite scores.
        Since scores are relative (normalized against each other),
        a new user joining changes everyone else's score slightly.
        """
        try:
            all_summaries = list(UserSummary.objects.all())
            scored_pairs = recalculate_all_scores(all_summaries)

            for summary_obj, new_score in scored_pairs:
                UserSummary.objects.filter(user_id=summary_obj.user_id).update(
                    composite_rank_score=new_score,
                )
        except Exception as e:
            logger.error(f"Ranking recomputation failed: {str(e)}")


class UserSummaryView(APIView):
    """
    GET /api/summary/<user_id>

    Returns the aggregated stats for a single user.
    If the user doesn't exist, we return a 404 with a clear message.
    """

    def get(self, request, user_id):
        user_id = user_id.strip()

        if not user_id:
            return Response(
                {'success': False, 'error': 'user_id cannot be empty.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            summary = UserSummary.objects.get(user_id=user_id)
        except UserSummary.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'error': f"No transactions found for user '{user_id}'.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # get this user's rank position in the leaderboard
        rank = (
            UserSummary.objects.filter(
                composite_rank_score__gt=summary.composite_rank_score
            ).count() + 1
        )

        data = UserSummarySerializer(summary).data
        data['current_rank'] = rank

        return Response({'success': True, 'summary': data}, status=status.HTTP_200_OK)


class RankingView(APIView):
    """
    GET /api/ranking

    Returns a paginated leaderboard sorted by composite_rank_score.
    Supports optional ?limit= and ?offset= query params.

    The ranking is based on three factors — see ranking.py for details.
    """

    def get(self, request):
        # simple pagination so nobody accidentally fetches 10,000 rows
        try:
            limit = int(request.query_params.get('limit', 10))
            offset = int(request.query_params.get('offset', 0))
        except ValueError:
            return Response(
                {'success': False, 'error': 'limit and offset must be integers.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if limit < 1 or limit > 100:
            return Response(
                {'success': False, 'error': 'limit must be between 1 and 100.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if offset < 0:
            return Response(
                {'success': False, 'error': 'offset cannot be negative.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        total_users = UserSummary.objects.count()
        summaries = UserSummary.objects.order_by('-composite_rank_score')[offset: offset + limit]

        # assign rank numbers starting from offset + 1
        ranked_list = []
        for index, summary in enumerate(summaries):
            summary.rank = offset + index + 1
            ranked_list.append(summary)

        serialized = RankingEntrySerializer(ranked_list, many=True).data

        return Response(
            {
                'success': True,
                'total_users': total_users,
                'limit': limit,
                'offset': offset,
                'ranking': serialized,
                'scoring_factors': {
                    'volume_weight': '40%',
                    'activity_weight': '30%',
                    'reliability_weight': '30%',
                },
            },
            status=status.HTTP_200_OK,
        )
