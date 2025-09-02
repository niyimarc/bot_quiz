from django.http import JsonResponse
import hmac, hashlib, time
from django.conf import settings
from django.urls import resolve

class HMACAuthMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.secret_key = settings.HMAC_SECRET_KEY.encode()

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        try:
            # Skip middleware for media and admin paths
            if (
                request.path.startswith('/media/') or
                resolve(request.path).app_name == 'admin' or
                request.path == '/api/token/refresh/'
            ):
                return None
        except Exception:
            pass  # In case resolve fails, just continue to validation

        signature = request.headers.get('X-Signature')
        timestamp = request.headers.get('X-Timestamp')

        if not signature or not timestamp:
            return JsonResponse({"detail": "Missing signature or timestamp"}, status=403)

        # Reject old timestamps (prevent replay)
        if abs(int(time.time()) - int(timestamp)) > 60:
            return JsonResponse({"detail": "Request expired"}, status=403)

        message = f"{timestamp}:{request.get_full_path()}"
        
        expected_signature = hmac.new(
            self.secret_key,
            message.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected_signature, signature):
            return JsonResponse({"detail": "Invalid signature"}, status=403)

        return None