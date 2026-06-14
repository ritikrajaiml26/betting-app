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
    """Forgot password view - send OTP to email"""
    if request.user.is_authenticated:
        return redirect('home')
    
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        
        if not email:
            messages.error(request, 'Please enter your email address')
            return render(request, 'core/forgot_password.html')
        
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            messages.error(request, 'Email not registered')
            return render(request, 'core/forgot_password.html')
        
        # Generate OTP
        otp_code = OTP.generate_otp()
        
        # Create OTP record
        otp = OTP.objects.create(
            user=user,
            otp=otp_code,
            expires_at=timezone.now() + timedelta(minutes=10)
        )
        
        # Send email (in production, configure email settings)
        try:
            send_mail(
                'Password Reset OTP - Color Prediction',
                f'Your OTP for password reset is: {otp_code}\n\nThis OTP is valid for 10 minutes.\n\nIf you did not request this, please ignore.',
                settings.EMAIL_HOST_USER or 'noreply@colorprediction.com',
                [email],
                fail_silently=True,  # Don't fail if email not configured
            )
        except:
            pass  # Email might not be configured
        
        # For development, show OTP in message
        messages.success(request, f'OTP sent to your email. (Demo OTP: {otp_code})')
        return redirect('verify_otp', otp_id=otp.id)
    
    return render(request, 'core/forgot_password.html')


def verify_otp_view(request, otp_id):
    """Verify OTP and allow password reset"""
    if request.user.is_authenticated:
        return redirect('home')
    
    try:
        otp = OTP.objects.get(id=otp_id)
    except OTP.DoesNotExist:
        messages.error(request, 'Invalid OTP request')
        return redirect('forgot_password')
    
    if otp.is_used:
        messages.error(request, 'OTP already used')
        return redirect('forgot_password')
    
    if not otp.is_valid():
        messages.error(request, 'OTP expired')
        return redirect('forgot_password')
    
    if request.method == 'POST':
        entered_otp = request.POST.get('otp', '')
        
        if entered_otp == otp.otp:
            # OTP verified, mark as used
            otp.is_used = True
            otp.save()
            
            # Show password reset form
            return render(request, 'core/reset_password.html', {'otp_id': otp_id})
        else:
            messages.error(request, 'Invalid OTP')
    
    return render(request, 'core/verify_otp.html', {'otp_id': otp_id})


def reset_password_view(request, otp_id):
    """Reset password after OTP verification"""
    if request.user.is_authenticated:
        return redirect('home')
    
    try:
        otp = OTP.objects.get(id=otp_id)
    except OTP.DoesNotExist:
        messages.error(request, 'Invalid request')
        return redirect('forgot_password')
    
    if not otp.is_used:
        messages.error(request, 'Please verify OTP first')
        return redirect('verify_otp', otp_id=otp_id)
    
    if request.method == 'POST':
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')
        
        if len(password) < 6:
            messages.error(request, 'Password must be at least 6 characters')
            return redirect('reset_password', otp_id=otp_id)
        
        if password != confirm_password:
            messages.error(request, 'Passwords do not match')
            return redirect('reset_password', otp_id=otp_id)
        
        # Set new password
        otp.user.set_password(password)
        otp.user.save()
        
        messages.success(request, 'Password reset successful! Please login.')
        return redirect('login')
    
    return redirect('verify_otp', otp_id=otp_id)