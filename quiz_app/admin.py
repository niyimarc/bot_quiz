from django.contrib import admin
from .models import (
    QuizParticipant, 
    QuizScore, 
    Quiz, 
    QuizSession, 
    QuizAccess, 
    RetryQuizScore, 
    RetrySession, 
    QuizCategory
    )

@admin.register(QuizCategory)
class QuizCategoryAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)

class QuizAccessInline(admin.TabularInline):
    model = QuizAccess
    extra = 1

@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ("name", "sheet_url", "is_active", "status")
    search_fields = ("name",)
    list_filter = ("is_active", "status")
    inlines = [QuizAccessInline]

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

@admin.register(RetryQuizScore)
class RetryQuizScoreAdmin(admin.ModelAdmin):
    list_display = ("original_score", "score", "total_questions", "index", "start_time", "end_time")
    list_filter = ("start_time", "end_time")
    search_fields = ("original_score__quiz__name", "original_score__participant__telegram_id")
    ordering = ("-start_time",)

@admin.register(RetrySession)
class RetrySessionAdmin(admin.ModelAdmin):
    list_display = ("participant", "retry", "active", "expecting_answer", "updated_at")
    list_filter = ("active", "expecting_answer")
    ordering = ("-updated_at",)
