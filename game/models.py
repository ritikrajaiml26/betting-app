from django.db import models
from django.conf import settings
from django.utils import timezone
from decimal import Decimal
import random
from datetime import datetime, timedelta


class GameRoom(models.Model):
    """Model for game rooms (WinGo 30sec, 1 Min, 3 Min)"""
    
    ROOM_TYPE_CHOICES = [
        ('wingo_30s', 'WinGo 30 Sec'),
        ('wingo_1min', 'WinGo 1 Min'),
        ('wingo_3min', 'WinGo 3 Min'),
    ]
    
    RESULT_MODE_CHOICES = [
        ('manual', 'Manual (Admin Selects)'),
        ('auto_random', 'Auto Random (Weighted %)'),
        ('smart_profit', 'Least Bet Wins (Platform Profit)'),
        ('pattern', 'Pattern-wise (Rules 1-10)'),
    ]

    PATTERN_CHOICES = [
        ('1', 'Rule 1: ABABAB'),
        ('2', 'Rule 2: AABBAABB'),
        ('3', 'Rule 3: AAABBBAAABBB'),
        ('4', 'Rule 4: AAAABBBBAAAA'),
        ('5', 'Rule 5: ABAAB'),
        ('6', 'Rule 6: AAAAAA'),
        ('7', 'Rule 7: AAB'),
        ('8', 'Rule 8: AAAB'),
        ('9', 'Rule 9: AAABB'),
        ('10', 'Rule 10: ABBAAABBBB'),
    ]

    # Pattern sequences: A=Red, B=Green
    PATTERN_SEQUENCES = {
        '1':  ['red', 'green', 'red', 'green', 'red', 'green'],
        '2':  ['red', 'red', 'green', 'green', 'red', 'red', 'green', 'green'],
        '3':  ['red', 'red', 'red', 'green', 'green', 'green', 'red', 'red', 'red', 'green', 'green', 'green'],
        '4':  ['red', 'red', 'red', 'red', 'green', 'green', 'green', 'green', 'red', 'red', 'red', 'red'],
        '5':  ['red', 'green', 'red', 'red', 'green'],
        '6':  ['red', 'red', 'red', 'red', 'red', 'red'],
        '7':  ['red', 'red', 'green'],
        '8':  ['red', 'red', 'red', 'green'],
        '9':  ['red', 'red', 'red', 'green', 'green'],
        '10': ['red', 'green', 'green', 'red', 'red', 'red', 'green', 'green', 'green', 'green'],
    }
    
    name = models.CharField(max_length=50, choices=ROOM_TYPE_CHOICES, unique=True)
    duration_seconds = models.IntegerField()
    is_active = models.BooleanField(default=True)
    
    # Result mode for this room
    result_mode = models.CharField(max_length=20, choices=RESULT_MODE_CHOICES, default='auto_random')
    
    # Current game tracking
    current_period = models.CharField(max_length=20, blank=True)
    current_game_start = models.DateTimeField(null=True, blank=True)
    
    # Manual result preset
    preset_period = models.CharField(max_length=20, null=True, blank=True)
    preset_winning_number = models.IntegerField(null=True, blank=True)
    preset_winning_color = models.CharField(max_length=10, null=True, blank=True)

    # Pattern mode settings
    pattern_rule = models.CharField(max_length=5, choices=[], null=True, blank=True, default='1')
    pattern_state = models.IntegerField(default=0)  # Current position in pattern sequence

    # Auto random weighted probabilities (percentages, must sum to 100)
    red_pct = models.IntegerField(default=45, help_text='Red % probability (auto_random mode)')
    green_pct = models.IntegerField(default=45, help_text='Green % probability (auto_random mode)')
    violet_pct = models.IntegerField(default=10, help_text='Violet % probability (auto_random mode)')

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = 'Game Rooms'
    
    def __str__(self):
        return self.get_name_display()
    
    def get_current_game_id(self):
        """Generate current game ID based on date and period"""
        now = timezone.localtime(timezone.now())
        date_str = now.strftime('%Y%m%d')
        
        total_seconds_today = now.hour * 3600 + now.minute * 60 + now.second
        period_index = total_seconds_today // self.duration_seconds + 1
        expected_period = f"{date_str}{period_index:05d}"
        
        if not self.current_game_start or self.current_period != expected_period:
            self.start_new_game()
            
        return self.current_period
    
    def get_time_remaining(self):
        """Get time remaining in current round (in seconds)"""
        now = timezone.localtime(timezone.now())
        total_seconds_today = now.hour * 3600 + now.minute * 60 + now.second
        elapsed = total_seconds_today % self.duration_seconds
        remaining = self.duration_seconds - elapsed
        if remaining <= 0:
            return 0
        return remaining
    
    def is_betting_open(self):
        """Check if betting is currently open (last 5 seconds are closed)"""
        remaining = self.get_time_remaining()
        return remaining > 5
    
    def start_new_game(self):
        """Start a new game round"""
        from django.db import transaction
        
        with transaction.atomic():
            # Lock the row to prevent race conditions from concurrent requests
            room = GameRoom.objects.select_for_update().get(id=self.id)
            
            now = timezone.localtime(timezone.now())
            date_str = now.strftime('%Y%m%d')
            
            # Calculate current period index
            total_seconds_today = now.hour * 3600 + now.minute * 60 + now.second
            period_index = total_seconds_today // room.duration_seconds + 1
            new_period = f"{date_str}{period_index:05d}"
            
            # If the current period in DB is already the calculated one, just align context
            if room.current_period == new_period:
                self.current_period = room.current_period
                self.current_game_start = room.current_game_start
                return room.current_period
                
            old_period = room.current_period
            
            # Update room to the new period
            room.current_period = new_period
            period_start_seconds = (period_index - 1) * room.duration_seconds
            start_time = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(seconds=period_start_seconds)
            room.current_game_start = start_time
            room.save()
            
            # Settle the old period and generate intermediate results
            if old_period:
                from datetime import datetime as dt_class
                import datetime as dt_module
                
                try:
                    old_date = dt_class.strptime(old_period[:8], '%Y%m%d').date()
                    old_idx = int(old_period[8:])
                    new_date = dt_class.strptime(new_period[:8], '%Y%m%d').date()
                    new_idx = int(new_period[8:])
                    
                    duration = room.duration_seconds
                    max_idx = 86400 // duration
                    
                    days_diff = (new_date - old_date).days
                    total_gap = 0
                    if days_diff == 0:
                        total_gap = new_idx - old_idx - 1
                    elif days_diff > 0:
                        total_gap = (max_idx - old_idx) + ((days_diff - 1) * max_idx) + (new_idx - 1)
                    
                    intermediate_periods = []
                    if total_gap > 0:
                        if total_gap > 50:
                            # Limit to generating the last 50 missing periods to avoid database overhead
                            curr_idx = new_idx - 1
                            curr_dt = new_date
                            for _ in range(50):
                                if curr_idx < 1:
                                    curr_dt = curr_dt - dt_module.timedelta(days=1)
                                    curr_idx = max_idx
                                intermediate_periods.append(f"{curr_dt.strftime('%Y%m%d')}{curr_idx:05d}")
                                curr_idx -= 1
                            intermediate_periods.reverse()
                        else:
                            curr_dt = old_date
                            curr_idx = old_idx + 1
                            while len(intermediate_periods) < total_gap:
                                if curr_idx > max_idx:
                                    curr_dt = curr_dt + dt_module.timedelta(days=1)
                                    curr_idx = 1
                                intermediate_periods.append(f"{curr_dt.strftime('%Y%m%d')}{curr_idx:05d}")
                                curr_idx += 1
                except Exception:
                    intermediate_periods = []
                
                # Settle the main old period first
                room.settle_game_period(old_period)
                
                # Settle all intermediate periods so they appear in history
                for p in intermediate_periods:
                    room.settle_game_period(p)
                
            # Settle any other older pending periods that need settlement
            from game.models import Bet
            unsettled_bets = Bet.objects.filter(room=room, status='pending').exclude(period=new_period)
            unsettled_periods = unsettled_bets.values_list('period', flat=True).distinct()
            for p in unsettled_periods:
                room.settle_game_period(p)
                
            # Update self attributes to match database state
            self.current_period = room.current_period
            self.current_game_start = room.current_game_start
            
            return room.current_period

    def settle_game_period(self, period):
        """Settle all bets for a given period and create a GameResult if it doesn't exist"""
        # Prevent double settlement
        if GameResult.objects.filter(room=self, period=period).exists():
            result = GameResult.objects.get(room=self, period=period)
            bets = Bet.objects.filter(room=self, period=period, status='pending')
            for bet in bets:
                bet.settle(result.winning_number, result.winning_color)
            return

        # Check for preset manual result
        if self.preset_period == period and self.preset_winning_number is not None and self.preset_winning_color:
            winning_number = self.preset_winning_number
            winning_color = self.preset_winning_color
            
            # Clear preset fields
            self.preset_period = None
            self.preset_winning_number = None
            self.preset_winning_color = None
            self.save()
        else:
            # Determine mode
            mode = self.result_mode
            # Calculate winning number and color
            winning_number, winning_color = GameResult.calculate_result(mode, room=self)
            if winning_number is None:
                # Fallback for manual or error cases — use smart_profit
                winning_number, winning_color = GameResult.calculate_result('smart_profit', room=self)
            if winning_number is None:
                # Final fallback
                winning_number, winning_color = GameResult.calculate_result('auto_random', room=self)
        
        # Calculate total bets
        total_bets = Bet.objects.filter(room=self, period=period).aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')
        
        # Create the GameResult first
        result = GameResult.objects.create(
            room=self,
            period=period,
            winning_number=winning_number,
            winning_color=winning_color,
            total_bet_amount=total_bets,
            total_win_amount=Decimal('0.00'),
            platform_profit=total_bets
        )
        
        # Settle all bets
        bets = Bet.objects.filter(room=self, period=period, status='pending')
        total_wins = Decimal('0.00')
        for bet in bets:
            is_winner = bet.settle(winning_number, winning_color)
            if is_winner:
                total_wins += bet.winning_amount
                
        # Update result totals
        result.total_win_amount = total_wins
        result.platform_profit = total_bets - total_wins
        result.save()
        
        # Calculate and set the exact end time for created_at to keep game history times sequential
        try:
            from datetime import datetime as dt_class
            import datetime as dt_module
            from django.utils import timezone
            
            period_date = dt_class.strptime(period[:8], '%Y%m%d').date()
            period_index = int(period[8:])
            
            period_end_seconds = period_index * self.duration_seconds
            period_date_datetime = timezone.make_aware(
                dt_class.combine(period_date, dt_class.min.time()),
                timezone.get_current_timezone()
            )
            exact_end_time = period_date_datetime + dt_module.timedelta(seconds=period_end_seconds)
            
            # Bypassing auto_now_add using update()
            GameResult.objects.filter(id=result.id).update(created_at=exact_end_time)
            result.created_at = exact_end_time
        except Exception:
            pass



class GameResult(models.Model):
    """Model for storing game results"""
    
    COLOR_CHOICES = [
        ('red', 'Red'),
        ('green', 'Green'),
        ('violet', 'Violet'),
    ]
    
    room = models.ForeignKey(GameRoom, on_delete=models.CASCADE, related_name='results')
    period = models.CharField(max_length=20)  # Game ID like 20260517100052175
    winning_number = models.IntegerField()  # 0-9
    winning_color = models.CharField(max_length=10, choices=COLOR_CHOICES)
    
    # Additional info
    total_bet_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_win_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    platform_profit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-period']
        unique_together = ['room', 'period']
        verbose_name_plural = 'Game Results'
    
    def __str__(self):
        return f"{self.room.name} - {self.period} - {self.get_winning_color_display()} ({self.winning_number})"
    
    @staticmethod
    def get_number_color(number):
        """Get color(s) for a number based on game rules"""
        color_map = {
            0: ['violet'],
            1: ['green'],
            2: ['red'],
            3: ['green'],
            4: ['red'],
            5: ['violet'],
            6: ['red'],
            7: ['green'],
            8: ['red'],
            9: ['green'],
        }
        return color_map.get(number, ['green'])
    
    @staticmethod
    def calculate_result(mode='auto_random', room=None):
        """
        Calculate game result based on mode:
        - manual: Admin selects (handled by admin)
        - auto_random: Random with configurable weighted probabilities (Red%, Green%, Violet%)
        - smart_profit: Compare Red vs Green payouts, lower payout color wins (Violet excluded)
        - pattern: Follow a predefined pattern sequence (Rules 1-10, A=Red, B=Green)
        """
        if mode == 'manual':
            # Admin will set the result manually via preset
            return None, None

        elif mode == 'auto_random':
            # Random result with weighted probabilities from room settings (or defaults)
            red_pct = room.red_pct if room else 45
            green_pct = room.green_pct if room else 45
            violet_pct = room.violet_pct if room else 10
            total = red_pct + green_pct + violet_pct or 100

            rand = random.random() * total

            if rand < red_pct:
                winning_number = random.choice([2, 4, 6, 8])
                winning_color = 'red'
            elif rand < red_pct + green_pct:
                winning_number = random.choice([1, 3, 7, 9])
                winning_color = 'green'
            else:
                winning_number = random.choice([0, 5])
                winning_color = 'violet'

            return winning_number, winning_color

        elif mode == 'smart_profit':
            # Smart profit logic — lower payout color wins; violet excluded from auto-win
            if not room:
                return GameResult.calculate_result('auto_random')

            current_period = room.get_current_game_id()
            red_total = Bet.objects.filter(
                room=room, period=current_period, bet_type='color', selection='red'
            ).aggregate(total=models.Sum('amount'))['total'] or 0

            green_total = Bet.objects.filter(
                room=room, period=current_period, bet_type='color', selection='green'
            ).aggregate(total=models.Sum('amount'))['total'] or 0

            red_number_bets = Bet.objects.filter(
                room=room, period=current_period, bet_type='number', selection__in=['2', '4', '6', '8']
            ).aggregate(total=models.Sum('amount'))['total'] or 0

            green_number_bets = Bet.objects.filter(
                room=room, period=current_period, bet_type='number', selection__in=['1', '3', '7', '9']
            ).aggregate(total=models.Sum('amount'))['total'] or 0

            # Calculate total payout for each color (including number bets)
            red_payout = (red_total * 2) + (red_number_bets * 2)
            green_payout = (green_total * 2) + (green_number_bets * 2)

            # Lower payout color wins (better for platform) — violet never auto-wins here
            if red_payout <= green_payout:
                winning_number = random.choice([2, 4, 6, 8])
                winning_color = 'red'
            else:
                winning_number = random.choice([1, 3, 7, 9])
                winning_color = 'green'

            return winning_number, winning_color

        elif mode == 'pattern':
            # Pattern-wise result: follows a predefined color sequence (A=Red, B=Green)
            # Violet is never part of the pattern
            if not room:
                return GameResult.calculate_result('auto_random')

            rule = str(room.pattern_rule or '1')
            sequence = GameRoom.PATTERN_SEQUENCES.get(rule, ['red', 'green'])
            seq_len = len(sequence)

            # Get current position and advance (circular)
            state = room.pattern_state or 0
            winning_color = sequence[state % seq_len]

            # Advance and save state
            room.pattern_state = (state + 1) % seq_len
            room.save(update_fields=['pattern_state'])

            if winning_color == 'red':
                winning_number = random.choice([2, 4, 6, 8])
            else:
                winning_number = random.choice([1, 3, 7, 9])

            return winning_number, winning_color

        return None, None


class Bet(models.Model):
    """Model for user bets"""
    
    BET_TYPE_CHOICES = [
        ('color', 'Color Bet'),
        ('number', 'Number Bet'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('won', 'Won'),
        ('lost', 'Lost'),
        ('cancelled', 'Cancelled'),
    ]
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bets')
    room = models.ForeignKey(GameRoom, on_delete=models.CASCADE, related_name='bets')
    period = models.CharField(max_length=20)  # Game ID
    
    # Bet details
    bet_type = models.CharField(max_length=10, choices=BET_TYPE_CHOICES)
    selection = models.CharField(max_length=10)  # Color name or number
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Result
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    winning_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Bets'
    
    def __str__(self):
        return f"{self.user.username} - {self.amount} on {self.selection} ({self.get_status_display()})"
    
    def get_multiplier(self):
        """Get the multiplier for this bet"""
        if self.bet_type == 'color':
            if self.selection == 'violet':
                return 3
            return 2
        else:  # number bet
            num = int(self.selection)
            if num in [0, 5]:  # Violet numbers
                return 3
            return 2
    
    def settle(self, winning_number, winning_color):
        """Settle the bet based on game result"""
        is_winner = False
        
        if self.bet_type == 'color':
            is_winner = self.selection == winning_color
        else:  # number bet
            is_winner = int(self.selection) == winning_number
        
        if is_winner:
            self.status = 'won'
            multiplier = self.get_multiplier()
            # Calculate win based on 90% of bet amount (10% tax)
            net_bet_amount = Decimal(str(self.amount)) * Decimal('0.90')
            self.winning_amount = net_bet_amount * Decimal(str(multiplier))
            
            # Add winnings to user's wallet
            wallet, _ = Wallet.objects.get_or_create(user=self.user)
            wallet.add_winning(self.winning_amount)
            
            # Create transaction
            Transaction.objects.create(
                user=self.user,
                transaction_type='win',
                amount=self.winning_amount,
                description=f'Won on {self.room.name} - {self.period}',
                status='completed',
                wallet_type='winning',
                reference_id=f'BET_{self.id}'
            )
        else:
            self.status = 'lost'
            self.winning_amount = 0
            
            # Create transaction for loss
            Transaction.objects.create(
                user=self.user,
                transaction_type='lose',
                amount=self.amount,
                description=f'Lost on {self.room.name} - {self.period}',
                status='completed',
                reference_id=f'BET_{self.id}'
            )
        
        self.save()
        return is_winner


# Import Wallet and Transaction for Bet settlement
from wallet.models import Wallet, Transaction