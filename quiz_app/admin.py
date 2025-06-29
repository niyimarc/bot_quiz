from django.contrib import admin
from .models import QuizParticipant, QuizScore, Quiz, QuizSession

@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ("name", "sheet_url", "is_active", "status")
    search_fields = ("name",)
    list_filter = ("is_active", "status")

@admin.register(QuizParticipant)
class QuizParticipantAdmin(admin.ModelAdmin):
    list_display = ("telegram_id", "username", "first_name", "last_name", "joined")
    search_fields = ("telegram_id", "username", "first_name", "last_name")
    list_filter = ("joined",)
    ordering = ("-joined",)
    readonly_fields = ("telegram_id",)


@admin.register(QuizScore)
class QuizScoreAdmin(admin.ModelAdmin):
    list_display = ("participant", "quiz", "score", "total_questions", "start_time", "end_time")
    list_filter = ("start_time", "end_time")
    search_fields = ("participant__username", "participant__telegram_id")
    ordering = ("-start_time",)

@admin.register(QuizSession)
class QuizSessionAdmin(admin.ModelAdmin):
    list_display = ("participant", "quiz", "score_obj", "index", "score", "active")
