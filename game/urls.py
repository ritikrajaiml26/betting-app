from django.urls import path
from . import views

urlpatterns = [
    path('home/', views.home_view, name='game_home'),
    path('room/<str:room_name>/data/', views.get_room_data, name='room_data'),
    path('bet/place/', views.place_bet, name='place_bet'),
    path('history/', views.game_history, name='game_history'),
    path('my-bets/', views.my_bets, name='my_bets'),
]