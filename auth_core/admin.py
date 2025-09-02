from django.contrib import admin
from .models import APIKey, Application, IPBlacklist

class ApplicationAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'created_on')

class APIKeyAdmin(admin.ModelAdmin):
    list_display = ['application', 'key', 'is_active', 'created_on']
    search_fields = ['application']
    actions = ['regenerate_selected_keys']

    @admin.action(description='Regenerate selected API keys')
    def regenerate_selected_keys(self, request, queryset):
        for obj in queryset:
            obj.regenerate_key()
        self.message_user(request, "Selected API keys have been regenerated.")

class IPBlacklistAdmin(admin.ModelAdmin):
    list_display = ("ip_address", "blacklist_count", "permanently_blacklisted", "created_on", "updated_on")
    search_fields = ("ip_address",)
    list_filter = ("permanently_blacklisted",)

admin.site.register(Application, ApplicationAdmin)
admin.site.register(APIKey, APIKeyAdmin)
admin.site.register(IPBlacklist, IPBlacklistAdmin)