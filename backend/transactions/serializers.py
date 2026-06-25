from rest_framework import serializers
from decimal import Decimal
from .models import Transaction, UserSummary


class TransactionInputSerializer(serializers.Serializer):
    """
    Validates the incoming POST /transaction payload.
    We're being strict here — every field must be present and correct.
    """

    user_id = serializers.CharField(max_length=100)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    transaction_type = serializers.ChoiceField(choices=['credit', 'debit'])
    description = serializers.CharField(max_length=255, required=False, default='', allow_blank=True)
    idempotency_key = serializers.CharField(max_length=255, required=False, default='', allow_blank=True)

    def validate_user_id(self, value):
        # strip whitespace and make sure it's not just spaces
        value = value.strip()
        if len(value) == 0:
            raise serializers.ValidationError("user_id cannot be empty or just whitespace.")

        # prevent SQL-injection-style abuse in user IDs
        forbidden_chars = [';', '--', '/*', '*/', 'DROP', 'SELECT']
        for bad in forbidden_chars:
            if bad.lower() in value.lower():
                raise serializers.ValidationError("user_id contains invalid characters.")

        return value

    def validate_amount(self, value):
        if value <= Decimal('0'):
            raise serializers.ValidationError("Amount must be greater than zero.")

        # upper limit to prevent obviously fake transactions
        if value > Decimal('1000000'):
            raise serializers.ValidationError("Amount exceeds the maximum allowed limit of 1,000,000.")

        return value


class TransactionOutputSerializer(serializers.ModelSerializer):
    """
    What we return after a successful transaction.
    """

    class Meta:
        model = Transaction
        fields = [
            'transaction_id',
            'user_id',
            'amount',
            'transaction_type',
            'description',
            'status',
            'created_at',
        ]


class UserSummarySerializer(serializers.ModelSerializer):
    """
    Response for GET /summary/:userId
    We compute net_balance on the fly here instead of storing it.
    """

    net_balance = serializers.SerializerMethodField()

    class Meta:
        model = UserSummary
        fields = [
            'user_id',
            'total_credit',
            'total_debit',
            'net_balance',
            'transaction_count',
            'reliability_score',
            'composite_rank_score',
            'last_updated',
        ]

    def get_net_balance(self, obj):
        return obj.total_credit - obj.total_debit


class RankingEntrySerializer(serializers.ModelSerializer):
    """
    Each entry in the GET /ranking response.
    We add a rank field dynamically in the view.
    """

    net_balance = serializers.SerializerMethodField()
    rank = serializers.IntegerField(read_only=True)

    class Meta:
        model = UserSummary
        fields = [
            'rank',
            'user_id',
            'composite_rank_score',
            'total_credit',
            'total_debit',
            'net_balance',
            'transaction_count',
            'reliability_score',
        ]

    def get_net_balance(self, obj):
        return obj.total_credit - obj.total_debit
