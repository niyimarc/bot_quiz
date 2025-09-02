from django.db import models
from datetime import timedelta
import secrets

class Application(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_on = models.DateTimeField(auto_now_add=True)
    updated_on = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
    
class APIKey(models.Model):
    key = models.CharField(max_length=255, editable=False, unique=True)
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='api_keys')
    is_active = models.BooleanField(default=True)
    rate_limit = models.IntegerField(default=1000)  # max requests
    rate_limit_period = models.DurationField(default=timedelta(minutes=1))  # per minute
    created_on = models.DateTimeField(auto_now_add=True)
    updated_on = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)
                     
    def regenerate_key(self):
        self.key = secrets.token_urlsafe(32)
        self.save()

    def __str__(self):
        return f"{self.application.name} ({self.key})"

class IPBlacklist(models.Model):
    ip_address = models.GenericIPAddressField(unique=True)
    blacklist_count = models.PositiveIntegerField(default=1)
    permanently_blacklisted = models.BooleanField(default=False)
    created_on = models.DateTimeField(auto_now_add=True)
    updated_on = models.DateTimeField(auto_now=True)