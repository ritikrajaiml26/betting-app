from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Sum, Count
from .models import GameRoom, GameResult, Bet


@admin.register(GameRoom)
class GameRoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'duration_seconds', 'is_active', 'result_mode', 'current_period')
    list_filter = ('is_active', 'result_mode')
    ordering = ('duration_seconds',)
    
    fieldsets = (
        ('Room Info', {'fields': ('name', 'duration_seconds', 'is_active')}),
        ('Result Settings', {'fields': ('result_mode',)}),
        ('Current Game', {'fields': ('current_period', 'current_game_start')}),
    )


@admin.register(GameResult)
class GameResultAdmin(admin.ModelAdmin):
    list_display = ('room', 'period', 'winning_number', 'winning_color', 'total_bet_amount', 'total_win_amount', 'platform_profit', 'created_at')
    list_filter = ('room', 'winning_color', 'created_at')
    search_fields = ('period', 'room__name')
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)
    
    actions = ['recalculate_results']
    
    def recalculate_results(self, request, queryset):
        # Recalculate totals from bets
        for result in queryset:
            total_bets = Bet.objects.filter(room=result.room, period=result.period).aggregate(total=Sum('amount'))['total'] or 0
            total_wins = Bet.objects.filter(room=result.room, period=result.period, status='won').aggregate(total=Sum('winning_amount'))['total'] or 0
            result.total_bet_amount = total_bets
            result.total_win_amount = total_wins
            result.platform_profit = total_bets - total_wins
            result.save()
    recalculate_results.short_description = 'Recalculate result totals'


@admin.register(Bet)
class BetAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'room', 'period', 'bet_type', 'selection', 'amount', 'status', 'winning_amount', 'created_at')
    list_filter = ('bet_type', 'status', 'room', 'created_at')
    search_fields = ('user__username', 'user__mobile', 'period', 'selection')
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)
    
    list_per_page = 50
    
    def has_change_permission(self, request, obj=None):
        return False  # Bets should not be editable