from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import (
                    UserProfileView,
                    BillingAddressView
                    )

app_name = 'user_profile'

urlpatterns = [
    path('api/user/profile/', UserProfileView.as_view(), name="profile"),
    path('api/billing_address/', BillingAddressView.as_view(), name="billing_address"),
]