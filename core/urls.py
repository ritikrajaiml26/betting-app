from django.urls import path
from django.shortcuts import redirect
from . import views
from . import admin_views

urlpatterns = [
    # Root URL redirects to the game home page
    path('', lambda request: redirect('game_home'), name='home'),
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),
    path('verify-otp/<int:otp_id>/', views.verify_otp_view, name='verify_otp'),
    path('reset-password/<int:otp_id>/', views.reset_password_view, name='reset_password'),
    
    # Custom Admin Dashboard routes
    path('admin-dashboard/', admin_views.admin_dashboard, name='admin_dashboard'),
    path('admin-dashboard/users/', admin_views.admin_users_view, name='admin_users'),
    path('admin-dashboard/users/<int:user_id>/', admin_views.admin_user_detail, name='admin_user_detail'),
    path('admin-dashboard/recharges/', admin_views.admin_recharges_view, name='admin_recharges'),
    path('admin-dashboard/recharges/<int:recharge_id>/approve/', admin_views.admin_recharge_approve, name='admin_recharge_approve'),
    path('admin-dashboard/recharges/<int:recharge_id>/reject/', admin_views.admin_recharge_reject, name='admin_recharge_reject'),
    path('admin-dashboard/withdraws/', admin_views.admin_withdraws_view, name='admin_withdraws'),
    path('admin-dashboard/withdraws/<int:withdraw_id>/update-status/', admin_views.admin_withdraw_update_status, name='admin_withdraw_update_status'),
    path('admin-dashboard/game-control/', admin_views.admin_game_control, name='admin_game_control'),
    path('admin-dashboard/game-control/preset/', admin_views.admin_game_preset_result, name='admin_game_preset_result'),
    path('admin-dashboard/payment-settings/', admin_views.admin_payment_settings, name='admin_payment_settings'),
]