from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import IPBlacklist
from django.contrib.sessions.models import Session
from django.contrib.auth.models import User
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from django.utils.timezone import now
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=IPBlacklist)
def check_blacklist_count(sender, instance, **kwargs):
    if instance.blacklist_count >= 15 and not instance.permanently_blacklisted:
        instance.permanently_blacklisted = True
        instance.save()
