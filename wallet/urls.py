from django.urls import path
from . import views

urlpatterns = [
    path('', views.wallet_view, name='wallet'),
    path('recharge/', views.recharge_view, name='recharge'),
    path('withdraw/', views.withdraw_view, name='withdraw'),
    path('add-bank/', views.add_bank_details, name='add_bank'),
    path('transfer-bonus/', views.transfer_bonus, name='transfer_bonus'),
    path('transactions/', views.transaction_history, name='transaction_history'),
    path('history/', views.unified_history, name='unified_history'),
    path('referrals/', views.referral_dashboard, name='referral_dashboard'),
]