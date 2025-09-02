from datetime import timedelta
from django.core.cache import cache
from django.utils import timezone

class IPBlacklistMixin:
    blacklist_cache_prefix = 'blacklisted_ip_'
    blacklist_threshold = 3  # How many times they can exceed the limit
    blacklist_duration = timedelta(hours=1)  # How long the IP is blacklisted

    def is_ip_blacklisted(self, ip):
        return cache.get(self.blacklist_cache_prefix + ip) is not None

    def record_violation(self, ip):
        key = f"violation_count_{ip}"
        count = cache.get(key, 0) + 1
        cache.set(key, count, timeout=3600)  # track violations for 1 hour

        if count >= self.blacklist_threshold:
            print(f"Temporarily blacklisting IP: {ip}")
            cache.set(self.blacklist_cache_prefix + ip, True, timeout=int(self.blacklist_duration.total_seconds()))
            self.record_violation_in_model(ip)

    def record_violation_in_model(self, ip):
        print(f"Recording violation in model for IP: {ip}")
        from .models import IPBlacklist
        record, created = IPBlacklist.objects.get_or_create(ip_address=ip)
        record.blacklist_count += 1
        record.updated_on = timezone.now()
        record.save()
