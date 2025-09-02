from rest_framework.throttling import BaseThrottle
from rest_framework.exceptions import Throttled
from django.utils import timezone
from datetime import timedelta
from .models import APIKey, IPBlacklist
from django.core.cache import cache
from .security import IPBlacklistMixin

class PermanentBlacklistThrottle(BaseThrottle):
    def allow_request(self, request, view):
        ip = self.get_ident(request)
        if IPBlacklist.objects.filter(ip_address=ip, permanently_blacklisted=True).exists():
            raise Throttled(detail="Your IP has been permanently blacklisted due to repeated violations.")
        return True
    
class APIKeyRateThrottle(BaseThrottle):
    cache_format = 'throttle_{key}'

    def __init__(self):
        self._retry_after = None 

    def get_cache_key(self, request):
        api_key = self.get_api_key(request)
        if not api_key or not api_key.is_active:
            return None
        return self.cache_format.format(key=api_key.key)

    def get_api_key(self, request):
        key = request.headers.get('X-API-KEY')
        if not key:
            return None
        try:
            return APIKey.objects.get(key=key)
        except APIKey.DoesNotExist:
            return None

    def allow_request(self, request, view):
        api_key = self.get_api_key(request)
        if not api_key:
            return False

        cache_key = self.get_cache_key(request)
        if not cache_key:
            return False

        history = cache.get(cache_key, [])

        now = timezone.now()
        window_start = now - api_key.rate_limit_period

        history = [timestamp for timestamp in history if timestamp > window_start]

        if len(history) >= api_key.rate_limit:
            # Rate limit exceeded
            self._retry_after = (history[0] + api_key.rate_limit_period - now).total_seconds()
            return False

        history.append(now)
        cache.set(cache_key, history, timeout=int(api_key.rate_limit_period.total_seconds()))

        self._retry_after = None
        return True

    def wait(self):
        return self._retry_after

class UserRateThrottle(BaseThrottle):
    cache_format = 'throttle_user_{user_id}'
    rate_limit = 20  # max requests allowed
    rate_period = timedelta(minutes=1)  # time window

    def __init__(self):
        self._retry_after = None

    def get_cache_key(self, request):
        if not request.user or not request.user.is_authenticated:
            return None
        return self.cache_format.format(user_id=request.user.id)

    def allow_request(self, request, view):
        cache_key = self.get_cache_key(request)
        if not cache_key:
            # No user or not authenticated, skip throttling here
            return True

        history = cache.get(cache_key, [])
        now = timezone.now()
        window_start = now - self.rate_period
        history = [timestamp for timestamp in history if timestamp > window_start]

        if len(history) >= self.rate_limit:
            self._retry_after = (history[0] + self.rate_period - now).total_seconds()
            return False

        history.append(now)
        cache.set(cache_key, history, timeout=int(self.rate_period.total_seconds()))
        self._retry_after = None
        return True

    def wait(self):
        return self._retry_after
    
class LoginRateThrottle(BaseThrottle, IPBlacklistMixin):
    cache_format = 'throttle_login_{ip}'
    rate_limit = 3  # per IP
    rate_period = timedelta(minutes=1)

    def __init__(self):
        self._retry_after = None

    def get_cache_key(self, request):
        ip = self.get_ident(request)
        return self.cache_format.format(ip=ip)

    def allow_request(self, request, view):
        ip = self.get_ident(request)
        self.ip = ip  

        cache_key = self.get_cache_key(request)
        history = cache.get(cache_key, [])
        now = timezone.now()
        history = [ts for ts in history if ts > now - self.rate_period]

        if len(history) >= self.rate_limit:
            # Track violation here
            self.record_violation(ip)
            self._retry_after = (history[0] + self.rate_period - now).total_seconds()

            if self.is_ip_blacklisted(ip):
                raise Throttled(detail="Too many repeated attempts. Your IP has been temporarily blocked.")
            
            return False

        history.append(now)
        cache.set(cache_key, history, timeout=int(self.rate_period.total_seconds()))
        return True

    def wait(self):
        return self._retry_after

class RegisterRateThrottle(BaseThrottle, IPBlacklistMixin):
    cache_format = 'throttle_register_{ip}'
    rate_limit = 5  # allow only 3 registration attempts per minute per IP
    rate_period = timedelta(minutes=1)

    def __init__(self):
        self._retry_after = None

    def get_cache_key(self, request):
        ip = self.get_ident(request)
        return self.cache_format.format(ip=ip)

    def allow_request(self, request, view):
        ip = self.get_ident(request)
        self.ip = ip  
        
        cache_key = self.get_cache_key(request)
        history = cache.get(cache_key, [])
        now = timezone.now()
        history = [ts for ts in history if ts > now - self.rate_period]

        if len(history) >= self.rate_limit:
            self.record_violation(ip)
            self._retry_after = (history[0] + self.rate_period - now).total_seconds()

            if self.is_ip_blacklisted(ip):
                raise Throttled(detail="Too many repeated attempts. Your IP has been temporarily blocked.")
            
            return False

        history.append(now)
        cache.set(cache_key, history, timeout=int(self.rate_period.total_seconds()))
        return True

    def wait(self):
        return self._retry_after
