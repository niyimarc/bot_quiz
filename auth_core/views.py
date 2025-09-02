from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from django.contrib.auth import authenticate
from .authentication import APIKeyAuthentication
from .throttling import APIKeyRateThrottle, UserRateThrottle, LoginRateThrottle, RegisterRateThrottle, PermanentBlacklistThrottle
from .serializers import RegisterSerializer
from rest_framework_simplejwt.views import TokenRefreshView

class DebugTokenRefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        try:
            return super().post(request, *args, **kwargs)
        except InvalidToken as e:
            print("❌ InvalidToken:", str(e))
            return Response({'detail': str(e)}, status=403)
        except TokenError as e:
            print("❌ TokenError:", str(e))
            return Response({'detail': str(e)}, status=403)
        
class PublicViewMixin:
    authentication_classes = [APIKeyAuthentication]
    permission_classes = []
    throttle_classes = [PermanentBlacklistThrottle, APIKeyRateThrottle]

    def dispatch(self, *args, **kwargs):
        if not self.request.headers.get("X-API-KEY"):
            return Response({"detail": "API key missing."}, status=403)
        return super().dispatch(*args, **kwargs)
    
class PrivateUserViewMixin:
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [PermanentBlacklistThrottle, APIKeyRateThrottle, UserRateThrottle]

class LoginAPIView(PublicViewMixin, APIView):
    throttle_classes = [PermanentBlacklistThrottle, APIKeyRateThrottle, LoginRateThrottle]
    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        user = authenticate(username=username, password=password)
        if not user:
            raise AuthenticationFailed('Invalid credentials')
        
        refresh = RefreshToken.for_user(user)
        return Response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        })

class RegisterView(PublicViewMixin, APIView):    
    throttle_classes = [PermanentBlacklistThrottle, APIKeyRateThrottle, RegisterRateThrottle]
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response({
                "message": "User registered successfully",
                "username": user.username,
                "email": user.email
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class LogoutView(PrivateUserViewMixin, APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = []

    def post(self, request):
        refresh_token = request.data.get("refresh")
        print(refresh_token)
        if not refresh_token:
            return Response({"detail": "Refresh token required"}, status=400)

        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({"detail": "Logout successful"})
        except TokenError:
            return Response({"detail": "Invalid or expired token"}, status=400)