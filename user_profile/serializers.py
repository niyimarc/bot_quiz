from rest_framework import serializers
from .models import BillingAddress

# serializers.py for user_profile app
class BillingAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillingAddress
        fields = ['address', 'state', 'city', 'apartment', 'country', 'zip_code']