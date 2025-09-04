from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import (
                    RegisterView, 
                    LoginAPIView, 
                    LogoutView, 
                    DebugTokenRefreshView,
                    )

app_name = 'auth_core'

urlpatterns = [
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', DebugTokenRefreshView.as_view(), name='token_refresh'),
    path('api/register/', RegisterView.as_view(), name="register"),
    path('api/login/', LoginAPIView.as_view(), name="login"),
    path('api/logout/', LogoutView.as_view(), name='token_blacklist'),
]