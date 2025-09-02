from django.db import models
from django.contrib.auth.models import User
import uuid
from django.utils import timezone
from .constants import ROLE
from . import utils

# Create your models here.
class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    referred_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='referrer', null=True, blank=True)
    role = models.CharField(choices=ROLE, max_length=16, default="Customer")
    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    email_verified = models.BooleanField(default=False)
    profile_is_submited = models.BooleanField(default=False)
    verification_token = models.UUIDField(default=uuid.uuid4, editable=False)
    password_reset_token = models.UUIDField(editable=False, null=True, blank=True)
    password_reset_token_is_used = models.BooleanField(default=True)
    password_reset_token_created_on = models.DateTimeField(null=True, blank=True)
    failed_login_attempts = models.PositiveIntegerField(default=0)
    created_on = models.DateTimeField(auto_now_add=True)
    updated_on = models.DateTimeField(auto_now=True)

    def generate_verification_token(self):
        return utils.generate_verification_token(self)

    def get_verification_url(self):
        return utils.get_verification_url(self)

    def generate_password_reset_token(self):
        return utils.generate_password_reset_token(self)

    def get_password_reset_token_url(self):
        return utils.get_password_reset_token_url(self)

    def is_password_reset_token_valid(self):
        return utils.is_password_reset_token_valid(self)

    def verification_progress(self):
        return utils.verification_progress(self)

class UserActivity(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    login_time = models.DateTimeField(default=timezone.now)
    logout_time = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    browser_info = models.CharField(max_length=255, null=True, blank=True)
    device_info = models.CharField(max_length=255, null=True, blank=True)
    login_successful = models.BooleanField(default=True)
    session_duration = models.DurationField(null=True, blank=True)
    failed_login_attempts = models.PositiveIntegerField(default=0)
    
    def __str__(self):
        return f"{self.user.username} - {self.login_time}"
        
    
class Address(models.Model):
    address = models.CharField(max_length=200,)
    state = models.CharField(max_length=30,)
    city = models.CharField(max_length=50,)
    apartment = models.CharField(max_length=50, null=True, blank=True)
    country = models.CharField(max_length=50,)
    zip_code = models.CharField(max_length=10,)
    is_verified = models.BooleanField(default=False)
    created_on = models.DateTimeField(auto_now_add=True)
    updated_on = models.DateTimeField(auto_now=True)

class BillingAddress(Address):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="billing_address")

class Phone(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="user_phone")
    phone = models.CharField(max_length=15, unique=True, null=True, blank=True)
    is_submitted = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    created_on = models.DateTimeField(auto_now_add=True)
    updated_on = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'phone'], name='unique_user_phone')
        ]