from django.db import models
from django.conf import settings
from django.utils import timezone
from decimal import Decimal


class Wallet(models.Model):
    """
    Wallet model with 3 types of balances:
    1. Deposit Wallet - Recharge money, gameplay allowed, no withdraw
    2. Winning Wallet - Game winnings, withdraw allowed
    3. Bonus Wallet - Signup/referral bonus, can transfer to deposit
    """
    
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wallet')
    
    # Three wallet types
    deposit_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    winning_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    bonus_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = 'Wallets'
    
    def __str__(self):
        return f"Wallet - {self.user.username} (Deposit: ₹{self.deposit_balance}, Winning: ₹{self.winning_balance}, Bonus: ₹{self.bonus_balance})"
    
    def get_total_balance(self):
        """Get total balance across all wallets"""
        return self.deposit_balance + self.winning_balance + self.bonus_balance
    
    def add_deposit(self, amount):
        """Add money to deposit wallet"""
        self.deposit_balance += Decimal(str(amount))
        self.save()
    
    def add_winning(self, amount):
        """Add money to winning wallet"""
        self.winning_balance += Decimal(str(amount))
        self.save()
    
    def add_bonus(self, amount):
        """Add money directly to deposit (main) balance as per new rule"""
        self.deposit_balance += Decimal(str(amount))
        self.save()
    
    def deduct_from_deposit(self, amount):
        """Deduct money from deposit wallet"""
        if self.deposit_balance >= Decimal(str(amount)):
            self.deposit_balance -= Decimal(str(amount))
            self.save()
            return True
        return False
    
    def deduct_from_winning(self, amount):
        """Deduct money from winning wallet"""
        if self.winning_balance >= Decimal(str(amount)):
            self.winning_balance -= Decimal(str(amount))
            self.save()
            return True
        return False
    
    def deduct_from_bonus(self, amount):
        """Deduct money from bonus wallet"""
        if self.bonus_balance >= Decimal(str(amount)):
            self.bonus_balance -= Decimal(str(amount))
            self.save()
            return True
        return False
    
    def transfer_bonus_to_deposit(self, amount):
        """Transfer from bonus wallet to deposit wallet"""
        if self.deduct_from_bonus(amount):
            self.add_deposit(amount)
            # Create transaction record
            Transaction.objects.create(
                user=self.user,
                transaction_type='transfer',
                amount=amount,
                description=f'Transferred ₹{amount} from Bonus to Deposit',
                status='completed'
            )
            return True
        return False
    
    def get_playable_balance(self):
        """Get balance that can be used for betting (deposit + winning + bonus)"""
        return self.deposit_balance + self.winning_balance + self.bonus_balance
    
    def get_withdrawable_balance(self):
        """Get balance that can be withdrawn (winning only)"""
        return self.winning_balance


class Recharge(models.Model):
    """Model for user recharge/deposit requests"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='recharges')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    utr_number = models.CharField(max_length=50)
    
    # Admin QR/UPI info (stored for reference)
    qr_code_used = models.CharField(max_length=200, blank=True)
    upi_id_used = models.CharField(max_length=100, blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Admin processing
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='processed_recharges',
        limit_choices_to={'is_staff': True}
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Recharge Requests'
    
    def __str__(self):
        return f"Recharge #{self.id} - {self.user.username} - ₹{self.amount} ({self.status})"
    
    def approve(self, admin_user):
        """Approve the recharge and add balance to user's deposit wallet (with 20% bonus on first recharge)"""
        self.status = 'approved'
        self.processed_by = admin_user
        self.processed_at = timezone.now()
        self.save()
        
        # Check if this is the user's first approved recharge
        is_first_recharge = not Recharge.objects.filter(
            user=self.user, 
            status='approved'
        ).exclude(id=self.id).exists()
        
        recharge_amount = self.amount
        description_addon = ""
        
        if is_first_recharge:
            extra_bonus = self.amount * Decimal('0.20')
            recharge_amount += extra_bonus
            description_addon = f" (Includes 20% First Recharge Bonus: +₹{extra_bonus})"
            
        # Add balance to user's deposit wallet
        wallet, created = Wallet.objects.get_or_create(user=self.user)
        wallet.add_deposit(recharge_amount)
        
        # Create transaction record
        Transaction.objects.create(
            user=self.user,
            transaction_type='recharge',
            amount=recharge_amount,
            description=f'Recharge approved - UTR: {self.utr_number}{description_addon}',
            status='success',
            reference_id=f'RECHARGE_{self.id}'
        )
        
        # Check if this is the user's first recharge for referral bonus
        self._process_referral_bonus()
        
        return True
    
    def reject(self, admin_user, reason=''):
        """Reject the recharge request"""
        self.status = 'rejected'
        self.processed_by = admin_user
        self.processed_at = timezone.now()
        self.rejection_reason = reason
        self.save()
        
        # Create transaction record
        Transaction.objects.create(
            user=self.user,
            transaction_type='recharge_failed',
            amount=self.amount,
            description=f'Recharge rejected - {reason}',
            status='failed',
            reference_id=f'RECHARGE_{self.id}'
        )
        
        return True
    
    def _process_referral_bonus(self):
        """Process referral bonus if this is user's first recharge"""
        # Check if user was referred
        if not self.user.referred_by:
            return
        
        # Check if this is the user's first approved recharge
        first_recharge = Recharge.objects.filter(
            user=self.user, 
            status='approved'
        ).order_by('created_at').first()
        
        if first_recharge and first_recharge.id == self.id:
            # Give referral bonus to the referrer
            referrer = self.user.referred_by
            referrer_wallet, _ = Wallet.objects.get_or_create(user=referrer)
            referrer_wallet.add_bonus(settings.GAME_SETTINGS['REFERRAL_BONUS'])
            
            # Create referral commission record
            ReferralCommission.objects.create(
                referrer=referrer,
                referred_user=self.user,
                amount=settings.GAME_SETTINGS['REFERRAL_BONUS'],
                commission_type='signup',
                level=1,
                description=f'First recharge bonus for referring {self.user.username}'
            )
            
            # Create transaction for referrer
            Transaction.objects.create(
                user=referrer,
                transaction_type='referral_bonus',
                amount=settings.GAME_SETTINGS['REFERRAL_BONUS'],
                description=f'Referral bonus for {self.user.username}',
                status='completed',
                wallet_type='deposit'
            )


class Withdraw(models.Model):
    """Model for user withdrawal requests"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('success', 'Success'),
        ('rejected', 'Rejected'),
    ]
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='withdraws')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Bank details (snapshot at time of withdrawal)
    upi_id = models.CharField(max_length=100)
    bank_name = models.CharField(max_length=100)
    account_holder_name = models.CharField(max_length=100)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Admin processing
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_withdraws',
        limit_choices_to={'is_staff': True}
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Withdraw Requests'
    
    def __str__(self):
        return f"Withdraw #{self.id} - {self.user.username} - ₹{self.amount} ({self.status})"
    
    def approve(self, admin_user):
        """Approve the withdraw request"""
        self.status = 'success'
        self.processed_by = admin_user
        self.processed_at = timezone.now()
        self.save()
        
        # Update transaction status
        Transaction.objects.filter(
            user=self.user,
            transaction_type='withdraw',
            reference_id=f'WITHDRAW_{self.id}'
        ).update(
            status='success',
            description=f'Withdraw to {self.upi_id} ({self.bank_name})'
        )
        
        return True
    
    def reject(self, admin_user, reason=''):
        """Reject the withdraw request and refund to winning wallet"""
        self.status = 'rejected'
        self.processed_by = admin_user
        self.processed_at = timezone.now()
        self.rejection_reason = reason
        self.save()
        
        # Refund to user's winning wallet (since we deducted immediately on request)
        wallet, created = Wallet.objects.get_or_create(user=self.user)
        wallet.winning_balance += self.amount
        wallet.save()
        
        # Update transaction status
        Transaction.objects.filter(
            user=self.user,
            transaction_type='withdraw',
            reference_id=f'WITHDRAW_{self.id}'
        ).update(
            status='failed',
            description=f'Withdraw rejected - {reason} (Refunded to winning wallet)'
        )
        
        return True


class BankDetail(models.Model):
    """Model for storing user's bank details for withdrawals"""
    
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bank_detail')
    
    upi_id = models.CharField(max_length=100)
    bank_name = models.CharField(max_length=100)
    account_holder_name = models.CharField(max_length=100)
    
    # Verification status
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'is_staff': True}
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = 'Bank Details'
    
    def __str__(self):
        return f"{self.user.username} - {self.upi_id}"


class ReferralCommission(models.Model):
    """Model for tracking referral commissions (3-tier system)"""
    
    COMMISSION_TYPE_CHOICES = [
        ('signup', 'Signup Bonus'),
        ('level_1', 'Level 1 Commission (20%)'),
        ('level_2', 'Level 2 Commission (10%)'),
        ('level_3', 'Level 3 Commission (7%)'),
    ]
    
    referrer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='earned_commissions'
    )
    referred_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='commission_records',
        null=True,
        blank=True
    )
    
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    commission_type = models.CharField(max_length=20, choices=COMMISSION_TYPE_CHOICES)
    level = models.IntegerField(default=1)  # 1, 2, or 3
    
    # Source of commission (e.g., from which recharge)
    source_recharge = models.ForeignKey(
        Recharge,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='commissions'
    )
    
    description = models.TextField(blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Referral Commissions'
    
    def __str__(self):
        return f"{self.referrer.username} - ₹{self.amount} ({self.get_commission_type_display()})"


class Transaction(models.Model):
    """Model for tracking all financial transactions"""
    
    TRANSACTION_TYPE_CHOICES = [
        ('recharge', 'Recharge'),
        ('recharge_failed', 'Recharge Failed'),
        ('withdraw', 'Withdraw'),
        ('withdraw_rejected', 'Withdraw Rejected'),
        ('bet', 'Bet Placed'),
        ('win', 'Game Win'),
        ('lose', 'Game Loss'),
        ('referral_bonus', 'Referral Bonus'),
        ('signup_bonus', 'Signup Bonus'),
        ('transfer', 'Wallet Transfer'),
        ('adjustment', 'Balance Adjustment'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('success', 'Success'),
        ('failed', 'Failed'),
    ]
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPE_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Wallet affected
    wallet_type = models.CharField(max_length=20, choices=[
        ('deposit', 'Deposit'),
        ('winning', 'Winning'),
        ('bonus', 'Bonus'),
    ], null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='completed')
    description = models.TextField(blank=True)
    reference_id = models.CharField(max_length=100, blank=True)
    
    # Balance after transaction
    balance_after = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    
    @property
    def display_status(self):
        if self.status == 'completed':
            return 'success'
        return self.status

    @property
    def transaction_id(self):
        return self.reference_id or f"TXN{self.id:06d}"

    @property
    def date(self):
        return self.created_at.date()

    @property
    def time(self):
        return self.created_at.time()
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Transactions'
    
    def __str__(self):
        return f"{self.user.username} - {self.get_transaction_type_display()} - ₹{self.amount}"


def distribute_bet_commission(user, bet_amount, bet_id=None):
    """
    Distribute 10% bet tax to 3 levels of referrers:
    - Level 1: 20% of 10% tax
    - Level 2: 10% of 10% tax
    - Level 3: 7% of 10% tax
    """
    tax_pool = Decimal(str(bet_amount)) * Decimal('0.10')
    if tax_pool <= 0:
        return
        
    rates = {
        1: Decimal('0.20'),  # 20% of tax
        2: Decimal('0.10'),  # 10% of tax
        3: Decimal('0.07'),  # 7% of tax
    }
    
    current_user = user
    for level in range(1, 4):
        referrer = current_user.referred_by
        if not referrer:
            break
            
        rate = rates[level]
        commission_amount = tax_pool * rate
        
        # Round commission to 2 decimal places
        commission_amount = commission_amount.quantize(Decimal('0.01'))
        
        if commission_amount > 0:
            # Add directly to referrer's wallet (deposit_balance as main balance)
            wallet, _ = Wallet.objects.get_or_create(user=referrer)
            wallet.add_deposit(commission_amount)
            
            # Create ReferralCommission record
            ReferralCommission.objects.create(
                referrer=referrer,
                referred_user=user,
                amount=commission_amount,
                commission_type=f'level_{level}',
                level=level,
                description=f'Level {level} bet commission from {user.username}\'s bet (Bet ID: {bet_id})'
            )
            
            # Create Transaction record for referrer
            Transaction.objects.create(
                user=referrer,
                transaction_type='referral_bonus',
                amount=commission_amount,
                wallet_type='deposit',
                description=f'Level {level} bet commission from {user.username}',
                status='completed',
                reference_id=f'BET_COMM_{bet_id}' if bet_id else ''
            )
            
        current_user = referrer