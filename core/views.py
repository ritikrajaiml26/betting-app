from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from .models import User, OTP
from wallet.models import Wallet
import random
import string


def generate_username():
    """Generate a unique username"""
    prefixes = ['USER', 'PLAYER', 'GAMER', 'WINNER']
    prefix = random.choice(prefixes)
    number = random.randint(1000, 9999)
    username = f"{prefix}{number}"
    
    # Ensure uniqueness
    while User.objects.filter(username=username).exists():
        number = random.randint(1000, 9999)
        username = f"{prefix}{number}"
    
    return username


def generate_referral_code():
    """Generate a unique referral code"""
    chars = string.ascii_uppercase + string.digits
    code = ''.join(random.choice(chars) for _ in range(6))
    
    # Ensure uniqueness
    while User.objects.filter(referral_code=code).exists():
        code = ''.join(random.choice(chars) for _ in range(6))
    
    return code


def register_view(request):
    """User registration view"""
    if request.user.is_authenticated:
        return redirect('home')
    
    # Get referral code from URL parameter
    ref_code = request.GET.get('ref', '')
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        mobile = request.POST.get('mobile', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        referral_code = request.POST.get('referral_code', '').strip()
        
        # Use referral from POST or URL
        if not referral_code and ref_code:
            referral_code = ref_code
        
        # Validation
        errors = []
        
        if not name or len(name) < 2:
            errors.append('Name must be at least 2 characters')
        
        if not mobile or len(mobile) < 10:
            errors.append('Please enter a valid mobile number')
        
        if not email or '@' not in email:
            errors.append('Please enter a valid email address')
        
        if not password or len(password) < 6:
            errors.append('Password must be at least 6 characters')
        
        # Check for existing mobile
        if User.objects.filter(mobile=mobile).exists():
            errors.append('Mobile number already exists')
        
        # Check for existing email
        if User.objects.filter(email=email).exists():
            errors.append('Email already exists')
        
        # Check referral code if provided
        referrer = None
        if referral_code:
            try:
                referrer = User.objects.get(referral_code=referral_code)
            except User.DoesNotExist:
                errors.append('Invalid referral code')
        
        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, 'core/register.html', {
                'ref_code': referral_code or ref_code
            })
        
        # Create user
        user = User.objects.create_user(
            mobile=mobile,
            email=email,
            password=password,
            username=generate_username(),
            name=name,
            referred_by=referrer
        )
        
        # Create wallet for user
        wallet = Wallet.objects.create(user=user)
        
        # Give signup bonus
        wallet.add_bonus(settings.GAME_SETTINGS['SIGNUP_BONUS'])
        
        # Create signup transaction
        from wallet.models import Transaction
        Transaction.objects.create(
            user=user,
            transaction_type='signup_bonus',
            amount=settings.GAME_SETTINGS['SIGNUP_BONUS'],
            description='Signup bonus',
            status='completed',
            wallet_type='bonus'
        )
        
        messages.success(request, 'Registration successful! You received ₹50 signup bonus.')
        return redirect('login')
    
    return render(request, 'core/register.html', {'ref_code': ref_code})


def login_view(request):
    """User login view"""
    if request.user.is_authenticated:
        if request.user.is_staff or request.user.is_superuser:
            return redirect('admin_dashboard')
        return redirect('home')
    
    if request.method == 'POST':
        mobile = request.POST.get('mobile', '').strip()
        password = request.POST.get('password', '')
        
        if not mobile or not password:
            messages.error(request, 'Please enter mobile number/username and password')
            return render(request, 'core/login.html')
        
        # Authenticate user using custom backend (MobileAuthBackend)
        user = authenticate(request, username=mobile, password=password)
        
        if user is None:
            # Check if user exists at all to provide better error message
            try:
                existing_user = User.objects.get(mobile=mobile)
                if not existing_user.check_password(password):
                    messages.error(request, 'Invalid password')
                else:
                    messages.error(request, 'Login failed. Please try again.')
            except User.DoesNotExist:
                # Try by username as well
                try:
                    existing_user = User.objects.get(username=mobile)
                    if not existing_user.check_password(password):
                        messages.error(request, 'Invalid password')
                    else:
                        messages.error(request, 'Login failed. Please try again.')
                except User.DoesNotExist:
                    messages.error(request, 'User not found with this mobile number or username')
            return render(request, 'core/login.html')
        
        # Check if user is blocked
        if user.is_blocked:
            messages.error(request, 'Your ID is temporarily blocked. Contact support system.')
            return render(request, 'core/login.html')
        
        # Login user
        login(request, user)
        
        # Update last login
        user.last_login_at = timezone.now()
        user.save()
        
        messages.success(request, 'Welcome back!')
        if user.is_staff or user.is_superuser:
            return redirect('admin_dashboard')
        return redirect('home')
    
    return render(request, 'core/login.html')


def logout_view(request):
    """User logout view"""
    logout(request)
    messages.success(request, 'Logged out successfully')
    return redirect('login')


def forgot_password_view(request):
    """Forgot password - verify email + mobile, then reset password directly"""
    if request.user.is_authenticated:
        return redirect('home')
    
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        mobile = request.POST.get('mobile', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')
        
        # Validate all fields
        if not email or not mobile or not password or not confirm_password:
            messages.error(request, 'All fields are required')
            return render(request, 'core/forgot_password.html')
        
        if len(password) < 6:
            messages.error(request, 'Password must be at least 6 characters')
            return render(request, 'core/forgot_password.html')
        
        if password != confirm_password:
            messages.error(request, 'Passwords do not match')
            return render(request, 'core/forgot_password.html')
        
        # Check if user exists with both email AND mobile matching
        try:
            user = User.objects.get(email__iexact=email, mobile=mobile)
        except User.DoesNotExist:
            messages.error(request, 'No account found with this registered email and mobile number')
            return render(request, 'core/forgot_password.html')
        
        # Reset password
        user.set_password(password)
        user.save()
        
        messages.success(request, 'Password changed successfully! Please login with your new password.')
        return redirect('login')
    
    return render(request, 'core/forgot_password.html')


def verify_otp_view(request, otp_id):
    """Redirect old OTP verify URL to forgot password"""
    return redirect('forgot_password')


def reset_password_view(request, otp_id):
    """Redirect old reset password URL to forgot password"""
    return redirect('forgot_password')