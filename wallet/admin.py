from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Sum
from .models import Wallet, Recharge, Withdraw, BankDetail, ReferralCommission, Transaction


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ('user', 'deposit_balance', 'winning_balance', 'bonus_balance', 'get_total')
    search_fields = ('user__username', 'user__mobile', 'user__email')
    ordering = ('-created_at',)
    
    def get_total(self, obj):
        return obj.get_total_balance()
    get_total.short_description = 'Total Balance'


@admin.register(Recharge)
class RechargeAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'amount', 'utr_number', 'status', 'processed_by', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('user__username', 'user__mobile', 'utr_number')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')
    
    actions = ['approve_recharges', 'reject_recharges']
    
    def approve_recharges(self, request, queryset):
        for recharge in queryset.filter(status='pending'):
            recharge.approve(request.user)
    approve_recharges.short_description = 'Approve selected recharges'
    
    def reject_recharges(self, request, queryset):
        for recharge in queryset.filter(status='pending'):
            recharge.reject(request.user, 'Rejected by admin')
    reject_recharges.short_description = 'Reject selected recharges'


@admin.register(Withdraw)
class WithdrawAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'amount', 'upi_id', 'bank_name', 'account_holder_name', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('user__username', 'user__mobile', 'upi_id', 'account_holder_name')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')
    
    actions = ['approve_withdraws', 'reject_withdraws']
    
    def approve_withdraws(self, request, queryset):
        for withdraw in queryset.filter(status='pending'):
            withdraw.approve(request.user)
    approve_withdraws.short_description = 'Approve selected withdrawals'
    
    def reject_withdraws(self, request, queryset):
        for withdraw in queryset.filter(status='pending'):
            withdraw.reject(request.user, 'Rejected by admin')
    reject_withdraws.short_description = 'Reject selected withdrawals'


@admin.register(BankDetail)
class BankDetailAdmin(admin.ModelAdmin):
    list_display = ('user', 'upi_id', 'bank_name', 'account_holder_name', 'is_verified', 'verified_at')
    list_filter = ('is_verified',)
    search_fields = ('user__username', 'user__mobile', 'upi_id')


@admin.register(ReferralCommission)
class ReferralCommissionAdmin(admin.ModelAdmin):
    list_display = ('referrer', 'referred_user', 'amount', 'commission_type', 'level', 'created_at')
    list_filter = ('commission_type', 'level', 'created_at')
    search_fields = ('referrer__username', 'referred_user__username')
    ordering = ('-created_at',)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'transaction_type', 'amount', 'status', 'wallet_type', 'created_at')
    list_filter = ('transaction_type', 'status', 'wallet_type', 'created_at')
    search_fields = ('user__username', 'user__mobile', 'reference_id')
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)
    
    def has_add_permission(self, request):
        return False