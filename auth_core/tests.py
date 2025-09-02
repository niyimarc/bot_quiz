from django.test import TestCase, RequestFactory
from django.utils import timezone
from datetime import timedelta
from auth_core.models import APIKey, Application
from auth_core.throttling import APIKeyRateThrottle

class APIKeyRateThrottleTest(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.app = Application.objects.create(name='Test App', description='For tests')
        self.api_key = APIKey.objects.create(
            application=self.app,
            name='Test Key',
            rate_limit=3,  # allow 3 requests
            rate_limit_period=timedelta(seconds=10),  # per 10 seconds
            is_active=True,
        )
        self.throttle = APIKeyRateThrottle()

    def make_request(self, key):
        request = self.factory.get('/some-url')
        request.headers = {'X-API-KEY': key}
        return request

    def test_allow_request_within_limit(self):
        request = self.make_request(self.api_key.key)
        for _ in range(3):
            allowed = self.throttle.allow_request(request, None)
            self.assertTrue(allowed)
            self.assertIsNone(self.throttle.wait())

    def test_throttle_blocks_after_limit(self):
        request = self.make_request(self.api_key.key)
        # hit the limit
        for _ in range(3):
            allowed = self.throttle.allow_request(request, None)
            self.assertTrue(allowed)

        # next request should be denied
        allowed = self.throttle.allow_request(request, None)
        self.assertFalse(allowed)
        wait_time = self.throttle.wait()
        self.assertIsNotNone(wait_time)
        self.assertGreater(wait_time, 0)

    def test_throttle_resets_after_period(self):
        request = self.make_request(self.api_key.key)
        # hit the limit
        for _ in range(3):
            allowed = self.throttle.allow_request(request, None)
            self.assertTrue(allowed)

        # simulate passage of time > rate_limit_period
        # by clearing cache or adjusting timestamps

        cache_key = self.throttle.get_cache_key(request)
        history = self.throttle.get_api_key(request) 
        from django.core.cache import cache

        # Clear cache to simulate expiration
        cache.delete(cache_key)

        allowed = self.throttle.allow_request(request, None)
        self.assertTrue(allowed)
