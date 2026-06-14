from django.contrib.auth.backends import ModelBackend
from .models import User


class MobileAuthBackend(ModelBackend):
    """
    Custom authentication backend that authenticates using mobile number.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        """
        Authenticate user by mobile number (passed as 'username' by Django).
        Also checks 'mobile' kwarg as a fallback.
        """
        mobile = kwargs.get('mobile', username)
        if mobile is None:
            return None

        try:
            user = User.objects.get(mobile=mobile)
        except User.DoesNotExist:
            # Try by username as well
            try:
                user = User.objects.get(username=mobile)
            except User.DoesNotExist:
                # Run the default password hasher once to reduce the timing
                # difference between an existing and a nonexistent user.
                User().set_password(password)
                return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
