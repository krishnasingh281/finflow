from django.urls import path
from .views import TransactionView, UserSummaryView, RankingView

urlpatterns = [
    path('transaction', TransactionView.as_view(), name='transaction'),
    path('summary/<str:user_id>', UserSummaryView.as_view(), name='user-summary'),
    path('ranking', RankingView.as_view(), name='ranking'),
]
