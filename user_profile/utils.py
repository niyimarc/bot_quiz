import uuid
from datetime import timedelta
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.urls import reverse
from django.utils import timezone
from django.shortcuts import redirect
from user_agents import parse

def generate_verification_token(profile):
    if not profile.verification_token:
        profile.verification_token = uuid.uuid4()
    return str(profile.verification_token)

def get_verification_url(profile):
    token = generate_verification_token(profile)
    return reverse('user_profile:verify_email', kwargs={'token': token})

def generate_password_reset_token(profile):
    if profile.password_reset_token and is_password_reset_token_valid(profile):
        return str(profile.password_reset_token)
    profile.password_reset_token = uuid.uuid4()
    profile.password_reset_token_created_on = timezone.now()
    profile.password_reset_token_is_used = False
    profile.save()
    return str(profile.password_reset_token)

def get_password_reset_token_url(profile):
    uidb64 = urlsafe_base64_encode(force_bytes(profile.user.id))
    token = generate_password_reset_token(profile)
    return reverse('user_profile:set_password', kwargs={'uidb64': uidb64, 'token': token})

def is_password_reset_token_valid(profile):
    if profile.password_reset_token_created_on:
        expiration_time = profile.password_reset_token_created_on + timedelta(minutes=15)
        return timezone.now() <= expiration_time
    return False

def log_login_info(user, request):
    from .models import UserActivity
    last_login = user.last_login or timezone.now()
    ip_address = get_client_ip(request)
    user_agent = parse(request.META.get('HTTP_USER_AGENT', ''))
    browser_info = f"{user_agent.browser.family} {user_agent.browser.version_string}"
    os_info = f"{user_agent.os.family} {user_agent.os.version_string}"
    device_info = user_agent.device.family if user_agent.device.family else 'Unknown'
    login_duration = timezone.now() - last_login if last_login else None

    try:
        UserActivity.objects.create(
            user=user,
            ip_address=ip_address,
            browser_info=browser_info,
            os_info=os_info,
            device_info=device_info,
            login_duration=login_duration,
            login_time=timezone.now()
        )
    except Exception as e:
        # Handle or log the exception
        print(f"Error creating UserActivity: {e}")

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def increment_failed_login_attempts(username):
    from .models import Profile, User
    try:
        user = User.objects.get(username=username)
        profile = Profile.objects.get(user=user)
        profile.failed_login_attempts += 1
        profile.save()
    except Profile.DoesNotExist:
        pass
    
def login_excluded(redirect_to):
    """ This decorator kicks authenticated users out of a view """ 
    def _method_wrapper(view_method):
        def _arguments_wrapper(request, *args, **kwargs):
            if request.user.is_authenticated:
                return redirect(redirect_to) 
            return view_method(request, *args, **kwargs)
        return _arguments_wrapper
    return _method_wrapper

def strfdelta(tdelta, fmt):
    d = {"days": tdelta.days}
    d["hours"], rem = divmod(tdelta.seconds, 3600)
    d["minutes"], d["seconds"] = divmod(rem, 60)
    return fmt.format(**d)
