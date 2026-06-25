from django.contrib import admin
from .models import Transaction, UserSummary, IdempotencyKey


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['transaction_id', 'user_id', 'amount', 'transaction_type', 'status', 'created_at']
    list_filter = ['transaction_type', 'status']
    search_fields = ['user_id', 'transaction_id']
    ordering = ['-created_at']


@admin.register(UserSummary)
class UserSummaryAdmin(admin.ModelAdmin):
    list_display = ['user_id', 'total_credit', 'total_debit', 'transaction_count', 'reliability_score', 'composite_rank_score']
    ordering = ['-composite_rank_score']


@admin.register(IdempotencyKey)
class IdempotencyKeyAdmin(admin.ModelAdmin):
    list_display = ['key', 'created_at']
    ordering = ['-created_at']
