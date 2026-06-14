from django.conf import settings


def site_settings(request):
    """Add site-wide settings to template context"""
    return {
        'SITE_NAME': 'Color Prediction',
        'SITE_SETTING': {
            'admin_upi': getattr(settings, 'ADMIN_UPI', 'Not configured'),
            'admin_qr': getattr(settings, 'ADMIN_QR', ''),
        },
        'GAME_SETTINGS': settings.GAME_SETTINGS,
    }