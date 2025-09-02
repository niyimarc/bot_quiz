from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from .serializers import BillingAddressSerializer
from .models import BillingAddress
from auth_core.views import PrivateUserViewMixin

# Create your views here.
class UserProfileView(PrivateUserViewMixin, APIView):
    def get(self, request):
        user = request.user
        billing = getattr(user, 'billing_address', None)

        billing_data = None
        if billing:
            billing_data = {
                "address": billing.address,
                "state": billing.state,
                "city": billing.city,
                "apartment": billing.apartment,
                "country": billing.country,
                "zip_code": billing.zip_code,
                "is_verified": billing.is_verified,
            }

        return Response({
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "billing_address": billing_data
        })
    
class BillingAddressView(PrivateUserViewMixin, APIView):
    def post(self, request):
        user = request.user
        serializer = BillingAddressSerializer(data=request.data)

        if serializer.is_valid():
            validated_data = serializer.validated_data
            validated_data["is_verified"] = True 
            # Update if already exists, or create new
            billing_address, created = BillingAddress.objects.update_or_create(
                user=user,
                defaults=validated_data
            )
            return Response({
                "success": True,
                "created": created,
                "billing_address": BillingAddressSerializer(billing_address).data
            }, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)