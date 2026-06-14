from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Sum, Q
from django.utils import timezone
from decimal import Decimal
import json

from .models import GameRoom, GameResult, Bet
from wallet.models import Wallet, Transaction
from django.conf import settings


def home_view(request):
    """Home page - main game interface"""
    if not request.user.is_authenticated:
        return redirect('login')
    if request.user.is_staff or request.user.is_superuser:
        return redirect('admin_dashboard')
    
    # Get or create user wallet
    wallet, created = Wallet.objects.get_or_create(user=request.user)
    
    # Get active game rooms
    game_rooms = GameRoom.objects.filter(is_active=True)
    
    # Get recent game results for each room
    recent_results = {}
    for room in game_rooms:
        recent_results[room.name] = GameResult.objects.filter(
            room=room
        ).order_by('-created_at')[:10]
    
    # Get user's recent bets
    user_bets = Bet.objects.filter(
        user=request.user
    ).order_by('-created_at')[:20]
    
    context = {
        'wallet': wallet,
        'game_rooms': game_rooms,
        'recent_results': recent_results,
        'user_bets': user_bets,
        'color_multipliers': settings.COLOR_MULTIPLIERS,
        'number_colors': settings.NUMBER_COLORS,
        'min_bet': settings.GAME_SETTINGS['MIN_BET'],
        'max_bet': settings.GAME_SETTINGS['MAX_BET'],
        'quick_amounts': [5, 10, 20, 50, 100, 300, 500, 1000],
    }
    
    return render(request, 'game/home.html', context)


def get_room_data(request, room_name):
    """Get current room data (AJAX)"""
    try:
        room = GameRoom.objects.get(name=room_name)
    except GameRoom.DoesNotExist:
        return JsonResponse({'error': 'Room not found'}, status=404)
    
    # Get or start new game
    if not room.current_game_start or room.get_time_remaining() <= 0:
        room.start_new_game()
    
    # Get current game data
    game_id = room.get_current_game_id()
    time_remaining = room.get_time_remaining()
    is_betting_open = room.is_betting_open()
    
    # Get recent results
    recent_results = GameResult.objects.filter(
        room=room
    ).order_by('-created_at')[:20]
    
    results_data = []
    for result in recent_results:
        results_data.append({
            'period': result.period,
            'number': result.winning_number,
            'color': result.winning_color,
        })
    
    # Get user's bets for current period
    user_bets = []
    if request.user.is_authenticated:
        user_bets_query = Bet.objects.filter(
            user=request.user,
            room=room,
            period=game_id
        )
        for bet in user_bets_query:
            user_bets.append({
                'id': bet.id,
                'type': bet.bet_type,
                'selection': bet.selection,
                'amount': str(bet.amount),
                'status': bet.status,
            })
            
    # Get user's bets for previous period to show win/loss results
    prev_period = recent_results[0].period if recent_results.exists() else None
    previous_bets = []
    if request.user.is_authenticated and prev_period:
        prev_bets_query = Bet.objects.filter(
            user=request.user,
            room=room,
            period=prev_period
        )
        for bet in prev_bets_query:
            previous_bets.append({
                'id': bet.id,
                'type': bet.bet_type,
                'selection': bet.selection,
                'amount': str(bet.amount),
                'status': bet.status,
                'winning_amount': str(bet.winning_amount),
            })
    
    # Get wallet balance
    wallet = None
    if request.user.is_authenticated:
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
    
    return JsonResponse({
        'room': room.name,
        'room_display': room.get_name_display(),
        'game_id': game_id,
        'time_remaining': round(time_remaining, 1),
        'is_betting_open': is_betting_open,
        'results': results_data,
        'user_bets': user_bets,
        'previous_period': prev_period,
        'previous_bets': previous_bets,
        'wallet': {
            'deposit': str(wallet.deposit_balance) if wallet else '0',
            'winning': str(wallet.winning_balance) if wallet else '0',
            'bonus': str(wallet.bonus_balance) if wallet else '0',
            'total': str(wallet.get_total_balance()) if wallet else '0',
        } if wallet else None,
    })


@require_POST
@login_required
def place_bet(request):
    """Place a bet on a game room"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Login required'}, status=401)
    
    try:
        data = json.loads(request.body)
        room_name = data.get('room')
        bet_type = data.get('bet_type')  # 'color' or 'number'
        selection = data.get('selection')  # color name or number
        amount = Decimal(str(data.get('amount', 0)))
    except:
        return JsonResponse({'error': 'Invalid data'}, status=400)
    
    # Validate room
    try:
        room = GameRoom.objects.get(name=room_name, is_active=True)
    except GameRoom.DoesNotExist:
        return JsonResponse({'error': 'Room not found'}, status=404)
    
    # Validate bet type
    if bet_type not in ['color', 'number']:
        return JsonResponse({'error': 'Invalid bet type'}, status=400)
    
    # Validate selection
    if bet_type == 'color':
        if selection not in ['red', 'green', 'violet']:
            return JsonResponse({'error': 'Invalid color selection'}, status=400)
    else:
        try:
            num = int(selection)
            if num < 0 or num > 9:
                return JsonResponse({'error': 'Invalid number'}, status=400)
        except (ValueError, TypeError):
            return JsonResponse({'error': 'Invalid number'}, status=400)
    
    # Validate amount
    min_bet = settings.GAME_SETTINGS['MIN_BET']
    max_bet = settings.GAME_SETTINGS['MAX_BET']
    
    if amount < min_bet or amount > max_bet:
        return JsonResponse({
            'error': f'Bet amount must be between ₹{min_bet} and ₹{max_bet}'
        }, status=400)
    
    # Check if betting is open
    if not room.is_betting_open():
        return JsonResponse({'error': 'Betting is closed for this round'}, status=400)
    
    # Get current period
    if not room.current_game_start or room.get_time_remaining() <= 0:
        room.start_new_game()
    
    period = room.get_current_game_id()
    
    # Get user wallet
    wallet, created = Wallet.objects.get_or_create(user=request.user)
    
    # Check balance (use deposit first, then bonus, then winning)
    playable_balance = wallet.get_playable_balance()
    
    if amount > playable_balance:
        return JsonResponse({'error': 'Insufficient Balance'}, status=400)
    
    # Deduct from wallet (deposit first, then bonus, then winning)
    temp_amount = amount
    deductions = []
    
    if wallet.deposit_balance > 0:
        dep_deduct = min(wallet.deposit_balance, temp_amount)
        wallet.deduct_from_deposit(dep_deduct)
        temp_amount -= dep_deduct
        deductions.append('deposit')
        
    if temp_amount > 0 and wallet.bonus_balance > 0:
        bon_deduct = min(wallet.bonus_balance, temp_amount)
        wallet.deduct_from_bonus(bon_deduct)
        temp_amount -= bon_deduct
        deductions.append('bonus')
        
    if temp_amount > 0 and wallet.winning_balance > 0:
        win_deduct = min(wallet.winning_balance, temp_amount)
        wallet.deduct_from_winning(win_deduct)
        temp_amount -= win_deduct
        deductions.append('winning')
        
    wallet_type = '+'.join(deductions) if deductions else 'deposit'
    
    # Create bet
    bet = Bet.objects.create(
        user=request.user,
        room=room,
        period=period,
        bet_type=bet_type,
        selection=str(selection),
        amount=amount,
    )
    
    # Distribute referral commission from the 10% tax
    try:
        from wallet.models import distribute_bet_commission
        distribute_bet_commission(request.user, amount, bet.id)
    except Exception as e:
        pass
    
    # Create transaction
    Transaction.objects.create(
        user=request.user,
        transaction_type='bet',
        amount=amount,
        description=f'Bet placed on {room.get_name_display()} - {selection}',
        status='completed',
        wallet_type=wallet_type,
        reference_id=f'BET_{bet.id}'
    )
    
    return JsonResponse({
        'success': True,
        'message': f'₹{amount} bet placed on {selection}',
        'bet': {
            'id': bet.id,
            'type': bet.bet_type,
            'selection': bet.selection,
            'amount': str(bet.amount),
        },
        'wallet': {
            'deposit': str(wallet.deposit_balance),
            'winning': str(wallet.winning_balance),
            'bonus': str(wallet.bonus_balance),
            'total': str(wallet.get_total_balance()),
        },
    })


def game_history(request):
    """View game history"""
    if not request.user.is_authenticated:
        return redirect('login')
    
    room_name = request.GET.get('room', 'wingo_30s')
    
    try:
        room = GameRoom.objects.get(name=room_name)
    except GameRoom.DoesNotExist:
        room = GameRoom.objects.first()
    
    # Get game results
    results = GameResult.objects.filter(
        room=room
    ).order_by('-created_at')[:50]
    
    context = {
        'room': room,
        'results': results,
        'game_rooms': GameRoom.objects.filter(is_active=True),
    }
    
    return render(request, 'game/history.html', context)


def my_bets(request):
    """View user's betting history"""
    if not request.user.is_authenticated:
        return redirect('login')
    
    # Get user's bets (unsliced for stats)
    all_bets = Bet.objects.filter(
        user=request.user
    ).select_related('room').order_by('-created_at')
    
    # Calculate stats BEFORE slicing
    total_bets = all_bets.count()
    won_bets = all_bets.filter(status='won').count()
    lost_bets = all_bets.filter(status='lost').count()
    total_won = all_bets.filter(status='won').aggregate(total=Sum('winning_amount'))['total'] or 0
    total_lost = all_bets.filter(status='lost').aggregate(total=Sum('amount'))['total'] or 0
    
    # Now slice for display
    bets = all_bets[:100]
    
    context = {
        'bets': bets,
        'stats': {
            'total': total_bets,
            'won': won_bets,
            'lost': lost_bets,
            'total_won': total_won,
            'total_lost': total_lost,
        }
    }
    
    return render(request, 'game/my_bets.html', context)