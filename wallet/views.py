from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Sum, Q
from django.utils import timezone
from decimal import Decimal
import json

from .models import Wallet, Recharge, Withdraw, BankDetail, Transaction, ReferralCommission
from django.conf import settings


@login_required
def wallet_view(request):
    """Main wallet page"""
    wallet, created = Wallet.objects.get_or_create(user=request.user)
    
    # Get recharge history
    recharges = Recharge.objects.filter(user=request.user).order_by('-created_at')[:10]
    
    # Get withdraw history
    withdraws = Withdraw.objects.filter(user=request.user).order_by('-created_at')[:10]
    
    # Get transactions
    transactions = Transaction.objects.filter(user=request.user).order_by('-created_at')[:20]
    
    # Get referral stats
    total_referrals = request.user.referred_users.count()
    total_commission = ReferralCommission.objects.filter(
        referrer=request.user
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    # Check if user can withdraw
    can_withdraw = request.user.can_withdraw()
    
    # Check if bank details are set
    has_bank_details = BankDetail.objects.filter(user=request.user, is_verified=True).exists()
    
    context = {
        'wallet': wallet,
        'recharges': recharges,
        'withdraws': withdraws,
        'transactions': transactions,
        'total_referrals': total_referrals,
        'total_commission': total_commission,
        'can_withdraw': can_withdraw,
        'has_bank_details': has_bank_details,
    }
    
    return render(request, 'wallet/wallet.html', context)


@login_required
def recharge_view(request):
    """Recharge/deposit page"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            amount = Decimal(str(data.get('amount', 0)))
            utr_number = data.get('utr_number', '').strip()
        except:
            return JsonResponse({'error': 'Invalid data'}, status=400)
        
        # Validate amount
        if amount <= 0:
            return JsonResponse({'error': 'Invalid amount'}, status=400)
        
        # Validate UTR
        if not utr_number:
            return JsonResponse({'error': 'UTR number is required'}, status=400)
        
        # Check for duplicate UTR
        if Recharge.objects.filter(utr_number=utr_number).exists():
            return JsonResponse({'error': 'This UTR has already been used'}, status=400)
        
        # Create recharge request
        recharge = Recharge.objects.create(
            user=request.user,
            amount=amount,
            utr_number=utr_number,
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Recharge request submitted successfully',
            'recharge_id': recharge.id,
        })
    
    # Get pending recharges
    pending_recharges = Recharge.objects.filter(
        user=request.user, 
        status='pending'
    ).order_by('-created_at')
    
    # Get approved recharges
    approved_recharges = Recharge.objects.filter(
        user=request.user,
        status='approved'
    ).order_by('-created_at')[:20]
    
    # Get admin QR/UPI details from database (admin can update via payment settings panel)
    from core.models import PaymentSettings
    payment_settings = PaymentSettings.get_settings()

    context = {
        'pending_recharges': pending_recharges,
        'approved_recharges': approved_recharges,
        'payment_settings': payment_settings,
        # Legacy keys kept for backward compatibility with old templates
        'admin_upi': payment_settings.admin_upi_id,
        'admin_qr': payment_settings.admin_qr_image.url if payment_settings.admin_qr_image else '',
    }

    return render(request, 'wallet/recharge.html', context)


@login_required
def withdraw_view(request):
    """Withdraw page"""
    wallet, created = Wallet.objects.get_or_create(user=request.user)
    
    # Check if user can withdraw
    if not request.user.can_withdraw():
        messages.error(request, 'You must complete your first recharge before withdrawing')
    
    # Get or check bank details
    try:
        bank_detail = BankDetail.objects.get(user=request.user)
    except BankDetail.DoesNotExist:
        bank_detail = None
    
    # Get withdraw history
    withdraws = Withdraw.objects.filter(
        user=request.user
    ).order_by('-created_at')[:20]
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            amount = Decimal(str(data.get('amount', 0)))
        except:
            return JsonResponse({'error': 'Invalid data'}, status=400)
        
        # Check if can withdraw
        if not request.user.can_withdraw():
            return JsonResponse({
                'error': 'Complete your first recharge before withdrawing'
            }, status=400)
        
        # Check bank details
        if not bank_detail or not bank_detail.is_verified:
            return JsonResponse({
                'error': 'Please add and verify your bank details first'
            }, status=400)
        
        # Validate amount
        if amount < 50 or amount > 50000:
            return JsonResponse({'error': 'Withdrawal limit is ₹50 - ₹50,000'}, status=400)
        
        if amount > wallet.winning_balance:
            return JsonResponse({'error': 'Insufficient balance in winning wallet'}, status=400)
            
        # Check 24-hour withdrawal limit (max 3 withdrawals)
        from datetime import timedelta
        time_threshold = timezone.now() - timedelta(hours=24)
        withdrawals_last_24h = Withdraw.objects.filter(
            user=request.user,
            created_at__gte=time_threshold
        ).exclude(status='rejected').count()
        
        if withdrawals_last_24h >= 3:
            return JsonResponse({
                'error': 'You can only make up to 3 withdrawal requests in 24 hours'
            }, status=400)
        
        # Check for pending withdrawals
        pending_withdraw = Withdraw.objects.filter(
            user=request.user,
            status__in=['pending', 'processing']
        ).exists()
        
        if pending_withdraw:
            return JsonResponse({
                'error': 'You already have a pending withdrawal request'
            }, status=400)
        
        # Create withdraw request (don't deduct yet - deduct on approval)
        withdraw = Withdraw.objects.create(
            user=request.user,
            amount=amount,
            upi_id=bank_detail.upi_id,
            bank_name=bank_detail.bank_name,
            account_holder_name=bank_detail.account_holder_name,
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Withdrawal request submitted successfully',
            'withdraw_id': withdraw.id,
        })
    
    context = {
        'wallet': wallet,
        'bank_detail': bank_detail,
        'withdraws': withdraws,
        'can_withdraw': request.user.can_withdraw(),
    }
    
    return render(request, 'wallet/withdraw.html', context)


@login_required
def add_bank_details(request):
    """Add/Edit bank details for withdrawal"""
    try:
        bank_detail = BankDetail.objects.get(user=request.user)
    except BankDetail.DoesNotExist:
        bank_detail = None
        
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            upi_id = data.get('upi_id', '').strip()
            bank_name = data.get('bank_name', '').strip()
            account_holder_name = data.get('account_holder_name', '').strip()
        except:
            return JsonResponse({'error': 'Invalid data'}, status=400)
        
        # Validate
        if not upi_id or not bank_name or not account_holder_name:
            return JsonResponse({'error': 'All fields are required'}, status=400)
        
        # Check if already exists
        if not bank_detail:
            bank_detail = BankDetail(user=request.user)
            
        bank_detail.upi_id = upi_id
        bank_detail.bank_name = bank_name
        bank_detail.account_holder_name = account_holder_name
        bank_detail.is_verified = True  # Auto-verify on save as per requirements
        bank_detail.verified_at = timezone.now()
        bank_detail.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Bank details saved successfully'
        })
    
    return render(request, 'wallet/add_bank.html', {'bank_detail': bank_detail})


@login_required
def transfer_bonus(request):
    """Transfer from bonus wallet to deposit wallet"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            amount = Decimal(str(data.get('amount', 0)))
        except:
            return JsonResponse({'error': 'Invalid data'}, status=400)
        
        wallet, created = Wallet.objects.get_or_create(user=request.user)
        
        if amount <= 0:
            return JsonResponse({'error': 'Invalid amount'}, status=400)
        
        if amount > wallet.bonus_balance:
            return JsonResponse({'error': 'Insufficient bonus balance'}, status=400)
        
        # Transfer
        success = wallet.transfer_bonus_to_deposit(amount)
        
        if success:
            return JsonResponse({
                'success': True,
                'message': f'₹{amount} transferred to deposit wallet',
                'wallet': {
                    'deposit': str(wallet.deposit_balance),
                    'winning': str(wallet.winning_balance),
                    'bonus': str(wallet.bonus_balance),
                    'total': str(wallet.get_total_balance()),
                },
            })
        else:
            return JsonResponse({'error': 'Transfer failed'}, status=400)
    
    wallet, created = Wallet.objects.get_or_create(user=request.user)
    
    context = {
        'wallet': wallet,
    }
    
    return render(request, 'wallet/transfer_bonus.html', context)


@login_required
def transaction_history(request):
    """View all transactions"""
    # Get filter
    transaction_type = request.GET.get('type', '')
    
    all_transactions = Transaction.objects.filter(user=request.user)
    
    # Get summary from all transactions before filtering
    summary = {
        'total_recharge': all_transactions.filter(transaction_type='recharge').aggregate(total=Sum('amount'))['total'] or 0,
        'total_withdraw': all_transactions.filter(transaction_type='withdraw').aggregate(total=Sum('amount'))['total'] or 0,
        'total_bet': all_transactions.filter(transaction_type='bet').aggregate(total=Sum('amount'))['total'] or 0,
        'total_win': all_transactions.filter(transaction_type='win').aggregate(total=Sum('amount'))['total'] or 0,
    }
    
    transactions = all_transactions
    if transaction_type:
        transactions = transactions.filter(transaction_type=transaction_type)
    
    transactions = transactions.order_by('-created_at')[:100]
    
    context = {
        'transactions': transactions,
        'summary': summary,
        'transaction_types': Transaction.TRANSACTION_TYPE_CHOICES,
    }
    
    return render(request, 'wallet/transaction_history.html', context)


@login_required
def unified_history(request):
    """View unified history (Game bets, Deposits, and Withdrawals)"""
    from game.models import Bet
    
    # Get user's bets
    bets = Bet.objects.filter(user=request.user).order_by('-created_at')[:50]
    
    # Get user's recharges
    recharges = Recharge.objects.filter(user=request.user).order_by('-created_at')[:50]
    
    # Get user's withdrawals
    withdraws = Withdraw.objects.filter(user=request.user).order_by('-created_at')[:50]
    
    # Compute game stats
    all_bets = Bet.objects.filter(user=request.user)
    total_bets = all_bets.count()
    won_bets = all_bets.filter(status='won').count()
    lost_bets = all_bets.filter(status='lost').count()
    total_won = all_bets.filter(status='won').aggregate(total=Sum('winning_amount'))['total'] or 0
    
    stats = {
        'total': total_bets,
        'won': won_bets,
        'lost': lost_bets,
        'total_won': total_won,
    }
    
    context = {
        'bets': bets,
        'recharges': recharges,
        'withdraws': withdraws,
        'stats': stats,
    }
    
    return render(request, 'wallet/unified_history.html', context)


@login_required
def referral_dashboard(request):
    """Referral dashboard"""
    # Get referral code and link
    referral_code = request.user.referral_code
    referral_link = f"{request.scheme}://{request.get_host()}/register?ref={referral_code}"
    
    # Get referral stats
    total_referrals = request.user.referred_users.count()
    
    # Get active referrals (users who have made at least one recharge)
    active_referrals = 0
    for referred_user in request.user.referred_users.all():
        if Recharge.objects.filter(user=referred_user, status='approved').exists():
            active_referrals += 1
    
    # Get total commission
    total_commission = ReferralCommission.objects.filter(
        referrer=request.user
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    # Get pending bonus
    try:
        wallet_obj = Wallet.objects.get(user=request.user)
        pending_bonus = wallet_obj.bonus_balance
    except Wallet.DoesNotExist:
        pending_bonus = 0
    
    # Get referral list with recharge amounts
    referral_list = []
    for referred_user in request.user.referred_users.all():
        total_recharged = Recharge.objects.filter(
            user=referred_user,
            status='approved'
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        commission_earned = ReferralCommission.objects.filter(
            referrer=request.user,
            referred_user=referred_user
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        referral_list.append({
            'user': referred_user,
            'total_recharged': total_recharged,
            'commission_earned': commission_earned,
        })
    
    context = {
        'referral_code': referral_code,
        'referral_link': referral_link,
        'stats': {
            'total_referrals': total_referrals,
            'active_referrals': active_referrals,
            'total_commission': total_commission,
            'pending_bonus': pending_bonus,
        },
        'referral_list': referral_list,
        'commission_rates': {
            'level_1': '20%',
            'level_2': '10%',
            'level_3': '7%',
        },
    }
    
    return render(request, 'wallet/referral_dashboard.html', context)