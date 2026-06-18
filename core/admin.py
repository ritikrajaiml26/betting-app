from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from django.urls import reverse
from .models import User, OTP, SiteSetting, AdminProfile, SupportTicket



@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('uid', 'username', 'name', 'mobile', 'email', 'get_balance', 'is_blocked', 'is_staff', 'created_at')
    list_filter = ('is_blocked', 'is_staff', 'is_active', 'created_at')
    search_fields = ('uid', 'username', 'name', 'mobile', 'email')
    ordering = ('-created_at',)
    
    fieldsets = (
        (None, {'fields': ('uid', 'username', 'mobile', 'email', 'password')}),
        ('Personal Info', {'fields': ('name', 'profile_image', 'referred_by')}),
        ('Referral', {'fields': ('referral_code',)}),
        ('Permissions', {'fields': ('is_active', 'is_blocked', 'blocked_reason', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important Dates', {'fields': ('last_login_at', 'created_at', 'updated_at')}),
    )
    
    readonly_fields = ('uid', 'last_login_at', 'created_at', 'updated_at')
    
    def get_balance(self, obj):
        try:
            wallet = obj.wallet
            return format_html(
                'Deposit: ₹{} | Winning: ₹{} | Bonus: ₹{}',
                wallet.deposit_balance,
                wallet.winning_balance,
                wallet.bonus_balance
            )
        except:
            return '-'
    get_balance.short_description = 'Wallet Balance'
    
    actions = ['block_users', 'unblock_users']
    
    def block_users(self, request, queryset):
        queryset.update(is_blocked=True)
    block_users.short_description = 'Block selected users'
    
    def unblock_users(self, request, queryset):
        queryset.update(is_blocked=False, blocked_reason='')
    unblock_users.short_description = 'Unblock selected users'


@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    list_display = ('user', 'otp', 'is_used', 'is_valid', 'created_at', 'expires_at')
    list_filter = ('is_used', 'created_at')
    search_fields = ('user__email', 'user__mobile', 'otp')
    ordering = ('-created_at',)
    
    def is_valid(self, obj):
        return obj.is_valid()
    is_valid.boolean = True


@admin.register(SiteSetting)
class SiteSettingAdmin(admin.ModelAdmin):
    list_display = ('key', 'value', 'updated_at')
    search_fields = ('key',)


@admin.register(AdminProfile)
class AdminProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'can_manage_users', 'can_manage_games', 'can_manage_wallet', 'can_view_reports')
    list_filter = ('can_manage_users', 'can_manage_games', 'can_manage_wallet', 'can_view_reports')


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'category', 'status', 'subject', 'created_at', 'replied_at')
    list_filter = ('status', 'category', 'created_at')
    search_fields = ('user__username', 'user__mobile', 'subject', 'message')
    readonly_fields = ('created_at', 'updated_at')