from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.db.models import Sum, Q, Count
from django.utils import timezone
from decimal import Decimal

from core.models import User, PaymentSettings
from wallet.models import Wallet, Recharge, Withdraw, Transaction, BankDetail
from game.models import GameRoom, GameResult, Bet

def admin_required(view_func):
    """Decorator to restrict view access to superusers and staff members only."""
    @login_required(login_url='login')
    def _wrapped_view(request, *args, **kwargs):
        if not (request.user.is_superuser or request.user.is_staff):
            return HttpResponseForbidden("Access Denied: You are not authorized to view this page.")
        return view_func(request, *args, **kwargs)
    return _wrapped_view


@admin_required
def admin_dashboard(request):
    """Main custom Admin Dashboard overview page."""
    # User stats
    total_users = User.objects.filter(is_superuser=False, is_staff=False).count()
    total_admins = User.objects.filter(Q(is_superuser=True) | Q(is_staff=True)).count()
    blocked_users = User.objects.filter(is_superuser=False, is_blocked=True).count()
    
    # Financial stats
    total_recharged = Recharge.objects.filter(status='approved').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    total_withdrawn = Withdraw.objects.filter(status='success').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    # Wallet balances across platform
    total_deposit_balance = Wallet.objects.aggregate(total=Sum('deposit_balance'))['total'] or Decimal('0.00')
    total_winning_balance = Wallet.objects.aggregate(total=Sum('winning_balance'))['total'] or Decimal('0.00')
    total_bonus_balance = Wallet.objects.aggregate(total=Sum('bonus_balance'))['total'] or Decimal('0.00')
    platform_total_balance = total_deposit_balance + total_winning_balance + total_bonus_balance
    
    # Pending requests count
    pending_recharges = Recharge.objects.filter(status='pending').count()
    pending_withdraws = Withdraw.objects.filter(status__in=['pending', 'processing']).count()
    
    # Game rooms
    rooms = GameRoom.objects.all()
    
    # Recent activity
    recent_recharges = Recharge.objects.all().order_by('-created_at')[:5]
    recent_withdraws = Withdraw.objects.all().order_by('-created_at')[:5]
    
    # Detailed lists
    all_users = User.objects.filter(is_superuser=False, is_staff=False).order_by('-created_at')
    all_admins = User.objects.filter(Q(is_superuser=True) | Q(is_staff=True)).order_by('-created_at')
    
    context = {
        'total_users': total_users,
        'total_admins': total_admins,
        'blocked_users': blocked_users,
        'total_recharged': total_recharged,
        'total_withdrawn': total_withdrawn,
        'platform_total_balance': platform_total_balance,
        'pending_recharges': pending_recharges,
        'pending_withdraws': pending_withdraws,
        'rooms': rooms,
        'recent_recharges': recent_recharges,
        'recent_withdraws': recent_withdraws,
        'all_users': all_users,
        'all_admins': all_admins,
    }
    return render(request, 'admin_custom/dashboard.html', context)


@admin_required
def admin_users_view(request):
    """View and manage all registered users."""
    query = request.GET.get('q', '').strip()
    users_qs = User.objects.filter(is_superuser=False)

    if query:
        # Support UID search: "#123" or plain number
        uid_query = query.lstrip('#').strip()
        uid_filter = Q()
        if uid_query.isdigit():
            uid_filter = Q(uid=int(uid_query)) | Q(id=int(uid_query))

        users_qs = users_qs.filter(
            uid_filter |
            Q(username__icontains=query) |
            Q(name__icontains=query) |
            Q(mobile__icontains=query) |
            Q(email__icontains=query)
        )
        
    users_list = []
    for user in users_qs.order_by('-created_at'):
        # Get stats
        wallet, _ = Wallet.objects.get_or_create(user=user)
        recharged = Recharge.objects.filter(user=user, status='approved').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        withdrawn = Withdraw.objects.filter(user=user, status='success').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        users_list.append({
            'user': user,
            'wallet': wallet,
            'recharged': recharged,
            'withdrawn': withdrawn,
        })
        
    context = {
        'users': users_list,
        'query': query,
    }
    return render(request, 'admin_custom/users.html', context)


@admin_required
def admin_user_detail(request, user_id):
    """Detailed user profile for admin inspection and modifications."""
    user = get_object_or_404(User, id=user_id, is_superuser=False)
    wallet, _ = Wallet.objects.get_or_create(user=user)
    bank_detail = BankDetail.objects.filter(user=user).first()
    
    # Handle user edits / password reset / adjustments
    if request.method == 'POST':
        action = request.POST.get('action')
        
        # 1. Password reset
        if action == 'change_password':
            password = request.POST.get('password', '').strip()
            if len(password) >= 6:
                user.set_password(password)
                user.save()
                messages.success(request, f"Password reset successfully for {user.username}.")
            else:
                messages.error(request, "Password must be at least 6 characters.")
                
        # 2. Block/Unblock toggle
        elif action == 'toggle_block':
            if user.is_blocked:
                user.is_blocked = False
                user.blocked_reason = ''
                user.save()
                messages.success(request, f"User {user.username} has been unblocked.")
            else:
                reason = request.POST.get('reason', '').strip()
                user.is_blocked = True
                user.blocked_at = timezone.now()
                user.blocked_reason = reason
                user.save()
                messages.warning(request, f"User {user.username} has been blocked.")
                
        # 3. Wallet Balance adjustment
        elif action == 'adjust_wallet':
            wallet_type = request.POST.get('wallet_type')  # deposit, winning, bonus
            adjust_action = request.POST.get('adjust_action')  # add, deduct
            amount_str = request.POST.get('amount', '0').strip()
            
            try:
                amount = Decimal(amount_str)
                if amount <= 0:
                    raise ValueError
            except:
                messages.error(request, "Please enter a valid amount greater than 0.")
                return redirect('admin_user_detail', user_id=user.id)
                
            success = False
            if wallet_type == 'deposit':
                if adjust_action == 'add':
                    wallet.add_deposit(amount)
                    success = True
                else:
                    success = wallet.deduct_from_deposit(amount)
            elif wallet_type == 'winning':
                if adjust_action == 'add':
                    wallet.add_winning(amount)
                    success = True
                else:
                    success = wallet.deduct_from_winning(amount)
            elif wallet_type == 'bonus':
                if adjust_action == 'add':
                    wallet.add_bonus(amount)
                    success = True
                else:
                    success = wallet.deduct_from_bonus(amount)
                    
            if success:
                # Log transaction
                Transaction.objects.create(
                    user=user,
                    transaction_type='adjustment',
                    amount=amount if adjust_action == 'add' else -amount,
                    wallet_type=wallet_type,
                    description=f"Admin manual balance adjustment ({adjust_action.upper()} ₹{amount} to {wallet_type.upper()})",
                    status='completed'
                )
                messages.success(request, f"Successfully {adjust_action}ed ₹{amount} to/from user's {wallet_type} balance.")
            else:
                messages.error(request, f"Failed to deduct ₹{amount}. User has insufficient balance in {wallet_type} wallet.")
                
        # 4. Verify Bank details
        elif action == 'verify_bank':
            if bank_detail:
                bank_detail.is_verified = True
                bank_detail.verified_at = timezone.now()
                bank_detail.verified_by = request.user
                bank_detail.save()
                messages.success(request, f"Bank details verified for {user.username}.")
                
        return redirect('admin_user_detail', user_id=user.id)
        
    # Get histories for display
    recharges = Recharge.objects.filter(user=user).order_by('-created_at')[:20]
    withdraws = Withdraw.objects.filter(user=user).order_by('-created_at')[:20]
    bets = Bet.objects.filter(user=user).order_by('-created_at')[:30]
    transactions = Transaction.objects.filter(user=user).order_by('-created_at')[:30]
    
    context = {
        'target_user': user,
        'wallet': wallet,
        'bank_detail': bank_detail,
        'recharges': recharges,
        'withdraws': withdraws,
        'bets': bets,
        'transactions': transactions,
    }
    return render(request, 'admin_custom/user_detail.html', context)


@admin_required
def admin_recharges_view(request):
    """View and process recharge/deposit requests."""
    pending_recharges = Recharge.objects.filter(status='pending').order_by('-created_at')
    processed_recharges = Recharge.objects.exclude(status='pending').order_by('-created_at')[:100]
    
    context = {
        'pending_recharges': pending_recharges,
        'processed_recharges': processed_recharges,
    }
    return render(request, 'admin_custom/recharges.html', context)


@admin_required
def admin_recharge_approve(request, recharge_id):
    """Approve a deposit request and credit balance to user wallet."""
    recharge = get_object_or_404(Recharge, id=recharge_id, status='pending')
    recharge.approve(request.user)
    messages.success(request, f"Recharge request #{recharge.id} of ₹{recharge.amount} approved! Funds credited to {recharge.user.username}.")
    return redirect('admin_recharges')


@admin_required
def admin_recharge_reject(request, recharge_id):
    """Reject a deposit request with a reason."""
    recharge = get_object_or_404(Recharge, id=recharge_id, status='pending')
    reason = request.POST.get('reason', 'Invalid UTR or payment not received.').strip()
    recharge.reject(request.user, reason)
    messages.warning(request, f"Recharge request #{recharge.id} rejected. Reason: {reason}")
    return redirect('admin_recharges')


@admin_required
def admin_withdraws_view(request):
    """View all withdrawal requests."""
    pending_withdraws = Withdraw.objects.filter(status__in=['pending', 'processing']).order_by('-created_at')
    processed_withdraws = Withdraw.objects.filter(status__in=['success', 'rejected']).order_by('-created_at')[:100]
    
    context = {
        'pending_withdraws': pending_withdraws,
        'processed_withdraws': processed_withdraws,
    }
    return render(request, 'admin_custom/withdraws.html', context)


@admin_required
def admin_withdraw_update_status(request, withdraw_id):
    """Update withdrawal request status and execute logic."""
    withdraw = get_object_or_404(Withdraw, id=withdraw_id)
    new_status = request.POST.get('status')
    reason = request.POST.get('reason', '').strip()
    
    if new_status not in ['pending', 'processing', 'success', 'rejected']:
        messages.error(request, "Invalid status choice.")
        return redirect('admin_withdraws')
        
    # Standard transaction status maps: success -> complete, rejected -> reject
    if new_status == 'success':
        if withdraw.status != 'success':
            withdraw.approve(request.user)
            messages.success(request, f"Withdrawal request #{withdraw.id} marked as Success! Winning wallet balance was already deducted.")
    elif new_status == 'rejected':
        if withdraw.status != 'success' and withdraw.status != 'rejected':
            withdraw.reject(request.user, reason or "Rejected by admin.")
            messages.warning(request, f"Withdrawal request #{withdraw.id} marked as Rejected. Refunded ₹{withdraw.amount} back to user's winning wallet.")
    else:
        # pending or processing: just update DB status
        withdraw.status = new_status
        withdraw.save()
        messages.info(request, f"Withdrawal request #{withdraw.id} updated to status: {new_status.upper()}.")
        
    return redirect('admin_withdraws')


@admin_required
def admin_game_control(request):
    """Custom dashboard to configure game modes, probabilities, and preset manual outcomes."""
    rooms = GameRoom.objects.all()

    if request.method == 'POST':
        action = request.POST.get('action', 'set_mode')
        room_id = request.POST.get('room_id')
        room = get_object_or_404(GameRoom, id=room_id)

        if action == 'set_mode':
            result_mode = request.POST.get('result_mode')
            if result_mode in ['manual', 'auto_random', 'smart_profit', 'pattern']:
                room.result_mode = result_mode

                # Save pattern rule if pattern mode selected
                if result_mode == 'pattern':
                    pattern_rule = request.POST.get('pattern_rule', '1')
                    if pattern_rule in [str(i) for i in range(1, 11)]:
                        room.pattern_rule = pattern_rule
                    room.pattern_state = 0  # Reset pattern sequence on mode change

                # Save auto_random probabilities if provided
                if result_mode == 'auto_random':
                    try:
                        red_pct = int(request.POST.get('red_pct', room.red_pct))
                        green_pct = int(request.POST.get('green_pct', room.green_pct))
                        violet_pct = int(request.POST.get('violet_pct', room.violet_pct))
                        if red_pct + green_pct + violet_pct == 100 and all(v >= 0 for v in [red_pct, green_pct, violet_pct]):
                            room.red_pct = red_pct
                            room.green_pct = green_pct
                            room.violet_pct = violet_pct
                        else:
                            messages.error(request, 'Percentages must be non-negative and sum to 100.')
                            return redirect('admin_game_control')
                    except (ValueError, TypeError):
                        pass

                room.save()
                messages.success(request, f"{room.get_name_display()} ka mode {result_mode.upper()} set ho gaya!")

        elif action == 'update_probs':
            # Update only the probabilities for auto_random without changing mode
            try:
                red_pct = int(request.POST.get('red_pct', room.red_pct))
                green_pct = int(request.POST.get('green_pct', room.green_pct))
                violet_pct = int(request.POST.get('violet_pct', room.violet_pct))
                if red_pct + green_pct + violet_pct == 100 and all(v >= 0 for v in [red_pct, green_pct, violet_pct]):
                    room.red_pct = red_pct
                    room.green_pct = green_pct
                    room.violet_pct = violet_pct
                    room.save()
                    messages.success(request, f"{room.get_name_display()} ke probabilities update ho gayi: R={red_pct}% G={green_pct}% V={violet_pct}%")
                else:
                    messages.error(request, 'Percentages must be non-negative and sum to 100.')
            except (ValueError, TypeError):
                messages.error(request, 'Invalid probability values.')

        return redirect('admin_game_control')

    # Get recent outcomes for each room
    room_data = []
    for room in rooms:
        recent_results = GameResult.objects.filter(room=room).order_by('-period')[:10]
        current_period = room.get_current_game_id()

        # Calculate bets placed for current active period
        bets = Bet.objects.filter(room=room, period=current_period)
        bets_count = bets.count()
        bets_amount = bets.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        room_data.append({
            'room': room,
            'current_period': current_period,
            'recent_results': recent_results,
            'bets_count': bets_count,
            'bets_amount': bets_amount,
        })

    context = {
        'rooms_data': room_data,
        'pattern_rules': GameRoom.PATTERN_CHOICES,
    }
    return render(request, 'admin_custom/game_control.html', context)


@admin_required
def admin_game_preset_result(request):
    """Preset winning color/number outcome for the currently active period."""
    if request.method == 'POST':
        room_id = request.POST.get('room_id')
        winning_number_str = request.POST.get('winning_number')
        winning_color = request.POST.get('winning_color')
        
        room = get_object_or_404(GameRoom, id=room_id)
        current_period = room.get_current_game_id()
        
        try:
            winning_number = int(winning_number_str)
            if winning_number < 0 or winning_number > 9:
                raise ValueError
        except:
            messages.error(request, "Winning number must be between 0 and 9.")
            return redirect('admin_game_control')
            
        if winning_color not in ['red', 'green', 'violet']:
            messages.error(request, "Invalid winning color.")
            return redirect('admin_game_control')
            
        # Store in room as preset; also switch mode to manual so preset is used
        room.preset_period = current_period
        room.preset_winning_number = winning_number
        room.preset_winning_color = winning_color
        room.result_mode = 'manual'
        room.save()

        messages.success(request, f"Manual result set for {room.get_name_display()} Period {current_period}: {winning_color.upper()} ({winning_number}). Mode switched to Manual.")

    return redirect('admin_game_control')


@admin_required
def admin_payment_settings(request):
    """View and update admin payment settings (UPI ID & QR Code)."""
    settings_obj = PaymentSettings.get_settings()

    if request.method == 'POST':
        admin_upi_id = request.POST.get('admin_upi_id', '').strip()
        qr_image = request.FILES.get('admin_qr_image')
        remove_qr = request.POST.get('remove_qr') == '1'

        if admin_upi_id:
            settings_obj.admin_upi_id = admin_upi_id

        if remove_qr:
            settings_obj.admin_qr_image = None

        if qr_image:
            settings_obj.admin_qr_image = qr_image

        settings_obj.save()
        messages.success(request, 'Payment settings saved successfully!')
        return redirect('admin_payment_settings')

    context = {
        'settings': settings_obj,
    }
    return render(request, 'admin_custom/payment_settings.html', context)
