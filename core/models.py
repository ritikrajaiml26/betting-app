from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils import timezone
import random
import string


def generate_username():
    """Generate a unique username like USER2045 or PLAYER9321"""
    prefixes = ['USER', 'PLAYER', 'GAMER', 'WINNER']
    prefix = random.choice(prefixes)
    number = random.randint(1000, 9999)
    username = f"{prefix}{number}"
    # Ensure uniqueness - try up to 100 times
    try:
        for _ in range(100):
            if not User.objects.filter(username=username).exists():
                return username
            number = random.randint(1000, 9999)
            prefix = random.choice(prefixes)
            username = f"{prefix}{number}"
    except:
        pass
    return username


def generate_referral_code():
    """Generate a unique referral code"""
    chars = string.ascii_uppercase + string.digits
    code = ''.join(random.choice(chars) for _ in range(6))
    # Ensure uniqueness - try up to 100 times
    try:
        for _ in range(100):
            if not User.objects.filter(referral_code=code).exists():
                return code
            code = ''.join(random.choice(chars) for _ in range(6))
    except:
        pass
    return code


def generate_uid():
    """Generate a unique serial user ID starting from 1"""
    try:
        last_user = User.objects.order_by('-uid').first()
        if last_user:
            return last_user.uid + 1
        return 1
    except:
        return 1


class CustomUserManager(BaseUserManager):
    """Custom manager for User model with mobile as USERNAME_FIELD"""

    def create_user(self, mobile, email, password=None, **extra_fields):
        if not mobile:
            raise ValueError('The Mobile number must be set')
        if not email:
            raise ValueError('The Email must be set')
        email = self.normalize_email(email)
        if 'username' not in extra_fields or not extra_fields['username']:
            extra_fields['username'] = generate_username()
        user = self.model(mobile=mobile, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, mobile, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('name', 'Admin')

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(mobile, email, password, **extra_fields)


class User(AbstractUser):
    """Custom User model for the Color Prediction Platform"""
    
    # Unique identifiers
    uid = models.IntegerField(unique=True, editable=False, default=generate_uid)
    username = models.CharField(max_length=20, unique=True, default=generate_username)
    
    # Profile information
    name = models.CharField(max_length=100)
    mobile = models.CharField(max_length=15, unique=True)
    email = models.EmailField(unique=True)
    
    # Referral system
    referral_code = models.CharField(max_length=10, unique=True, default=generate_referral_code)
    referred_by = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='referred_users')
    
    # Account status
    is_blocked = models.BooleanField(default=False)
    blocked_at = models.DateTimeField(null=True, blank=True)
    blocked_reason = models.TextField(null=True, blank=True)
    
    # Profile
    profile_image = models.ImageField(upload_to='profile_images/', null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    
    # Mark this as the field used for authentication
    USERNAME_FIELD = 'mobile'
    REQUIRED_FIELDS = ['email', 'name']

    # Use custom manager
    objects = CustomUserManager()
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.username} ({self.mobile})"
    
    def save(self, *args, **kwargs):
        if not self.referral_code:
            self.referral_code = generate_referral_code()
        super().save(*args, **kwargs)
    
    def get_referral_link(self):
        """Get the referral link for this user"""
        return f"/register?ref={self.referral_code}"
    
    def is_active_user(self):
        """Check if user is active and not blocked"""
        return self.is_active and not self.is_blocked
    
    def get_total_balance(self):
        """Get total balance across all wallets"""
        from wallet.models import Wallet
        wallet = Wallet.objects.filter(user=self).first()
        if wallet:
            return wallet.deposit_balance + wallet.winning_balance + wallet.bonus_balance
        return 0
    
    def can_withdraw(self):
        """Check if user can withdraw (must have made first recharge)"""
        from wallet.models import Recharge
        return Recharge.objects.filter(user=self, status='approved').exists()


class OTP(models.Model):
    """Model for storing OTPs for password reset"""
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"OTP for {self.user.email} - {self.otp}"
    
    def is_valid(self):
        """Check if OTP is still valid"""
        return not self.is_used and timezone.now() < self.expires_at
    
    @staticmethod
    def generate_otp():
        """Generate a 6-digit OTP"""
        return ''.join(random.choices(string.digits, k=6))


class SiteSetting(models.Model):
    """Model for site-wide settings"""
    
    key = models.CharField(max_length=50, unique=True)
    value = models.TextField()
    description = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = 'Site Settings'
    
    def __str__(self):
        return f"{self.key}: {self.value}"


class PaymentSettings(models.Model):
    """Singleton model for admin payment settings (UPI ID and QR Code)"""
    
    admin_upi_id = models.CharField(
        max_length=150,
        default='admin@upi',
        help_text='Admin UPI ID shown to users during recharge'
    )
    admin_qr_image = models.ImageField(
        upload_to='qr_codes/',
        null=True,
        blank=True,
        help_text='QR Code image shown to users during recharge'
    )
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Payment Settings'
        verbose_name_plural = 'Payment Settings'
    
    def __str__(self):
        return f'Payment Settings (UPI: {self.admin_upi_id})'
    
    @classmethod
    def get_settings(cls):
        """Get or create the singleton payment settings row"""
        obj, _ = cls.objects.get_or_create(id=1)
        return obj


class AdminProfile(models.Model):
    """Extended admin profile information"""
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='admin_profile')
    can_manage_users = models.BooleanField(default=True)
    can_manage_games = models.BooleanField(default=True)
    can_manage_wallet = models.BooleanField(default=True)
    can_view_reports = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name_plural = 'Admin Profiles'
    
    def __str__(self):
        return f"Admin: {self.user.username}"