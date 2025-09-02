from django.contrib.auth.models import User
from .models import Profile, UserActivity, Phone, BillingAddress
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from user_agents import parse
import threading
from concurrent.futures import ThreadPoolExecutor
get_from_email = settings.EMAIL_HOST_USER
business_name = settings.BUSINESS_NAME
business_logo = settings.BUSINESS_LOGO
contact_email = settings.CONTACT_EMAIL
from_email = business_name + "<" + get_from_email + ">"

# Create a ThreadPoolExecutor for managing threads
executor = ThreadPoolExecutor(max_workers=5)  # You can adjust the number of workers

# Define a function to send email notifications asynchronously
def send_email_notifications(profile, instance, created, new_email):
    if created or (profile.email_verified is False and profile.user.email is not None):
        send_email_verification(profile, new_email=new_email)

        # Send notification email to admin email address.
        title = "New User Created"
        details = f"A new user ({instance}) just created an account on {business_name}, go to the admin dashboard to create a deposit wallet for this user."
        send_mail(
            title, 
            details, 
            from_email, 
            [contact_email],
            fail_silently=False,
        )


@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    profile, _ = Profile.objects.get_or_create(user=instance)
    
    # Explicitly set the verification_token for new profiles
    if created:
        profile.verification_token = profile.generate_verification_token()
        profile.save()

        # Submit the email sending task to the ThreadPoolExecutor
        executor.submit(send_email_notifications, profile, instance, created, instance.email)
    
    # If the user is updated, save the profile
    elif not created:
        instance.profile.save()



def send_email_verification(profile, new_email=None):
    user_name = profile.user.username
    verification_url = profile.get_verification_url()
    base_url = settings.BASE_URL.rstrip('/')
    verification_url = f"{base_url}{verification_url}"

    title = 'Verify your email'
    context = {
        'user_name': user_name,
        'verification_url': verification_url,
        'business_name': business_name,
        'contact_email': contact_email,
        'title': title,
        'business_logo': business_logo,
        'base_url': base_url,
    }
    html_message = render_to_string('email_templates/verification_email.html', context)
    details = f"Hi {user_name} Click the link below to verify your email {verification_url}"
    to_email = new_email or profile.user.email 
    send_mail(
            title,
            details,
            from_email,
            [to_email],
            fail_silently=False,
            html_message=html_message,
        )

def send_password_reset_email(user, profile, token):
    base_url = settings.BASE_URL.rstrip('/')
    reset_link = profile.get_password_reset_token_url()
    reset_link = f"{base_url}{reset_link}"
    title = 'Password Reset'
    context = {
        'user_name': user,
        'reset_link': reset_link,
        'business_name': business_name,
        'contact_email': contact_email,
        'title': title,
        'business_logo': business_logo,
        'base_url': base_url,
    }
    html_message = render_to_string('email_templates/password_reset.html', context)
    details = f'Click the following link to reset your password: {reset_link}'
    send_mail(
        title,
        details,
        from_email,
        [user.email],
        fail_silently=False,
        html_message=html_message,
    )    

@receiver(post_save, sender=User)
def create_phone_when_user_is_created(sender, instance, created, **kwargs):
    if created:
        Phone.objects.create(user=instance)


def log_user_login_task(user, ip_address, browser_info, device_info, failed_login_attempts):
    UserActivity.objects.create(
        user=user,
        ip_address=ip_address,
        browser_info=browser_info,
        device_info=device_info,
        failed_login_attempts=failed_login_attempts,
        login_successful=True
    )

@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    try:
        ip_address = request.META.get('REMOTE_ADDR')
        browser_info = request.META.get('HTTP_USER_AGENT')
        user_agent = parse(request.META.get('HTTP_USER_AGENT', ''))
        device_info = user_agent.device.family
        failed_login_attempts = user.profile.failed_login_attempts

        # Run the logging task in a separate thread
        threading.Thread(target=log_user_login_task, args=(user, ip_address, browser_info, device_info, failed_login_attempts)).start()
    except Exception as e:
        print(f"Error logging user activity: {e}")

@receiver(user_logged_out)
def log_user_logout(sender, request, user, **kwargs):
    try:
        last_activity = UserActivity.objects.filter(user=user).latest('login_time')
        last_activity.logout_time = timezone.now()
        last_activity.session_duration = last_activity.logout_time - last_activity.login_time
        last_activity.save()
    except UserActivity.DoesNotExist:
        pass

@receiver(post_save, sender=User)
def create_billing_address(sender, instance, created, **kwargs):
    if created:
        BillingAddress.objects.create(user=instance)