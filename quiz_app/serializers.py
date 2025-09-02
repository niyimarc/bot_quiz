from rest_framework import serializers
from .models import Quiz, QuizScore, QuizSession, QuizCategory, QuizAccess, RetryQuizScore

class QuizCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = QuizCategory
        fields = ["id", "name"]

class QuizSerializer(serializers.ModelSerializer):
    category = QuizCategorySerializer(many=True, read_only=True)
    total_participants = serializers.SerializerMethodField()
    total_attempts = serializers.SerializerMethodField()
    last_attempt_time = serializers.SerializerMethodField()
    retry_count = serializers.SerializerMethodField()

    class Meta:
        model = Quiz
        fields = [
            "id", "name", "sheet_url", "status", "is_active", "created_date",
            "category", "total_participants", "total_attempts",
            "last_attempt_time", "retry_count"
        ]

    def get_total_participants(self, obj):
        return QuizScore.objects.filter(quiz=obj).values("participant_id").distinct().count()

    def get_total_attempts(self, obj):
        return QuizScore.objects.filter(quiz=obj).count()

    def get_last_attempt_time(self, obj):
        last = QuizScore.objects.filter(quiz=obj).order_by("-attempt_time").values_list("attempt_time", flat=True).first()
        return last.isoformat() if last else None

    def get_retry_count(self, obj):
        return RetryQuizScore.objects.filter(original_score__quiz=obj).count()

class QuizAccessSerializer(serializers.ModelSerializer):
    participant_username = serializers.CharField(source="participant.username", read_only=True)
    granted_by_username = serializers.CharField(source="granted_by.username", read_only=True)

    class Meta:
        model = QuizAccess
        fields = ["participant_username", "access_type", "granted_by_username", "granted_at"]

class QuizScoreSerializer(serializers.ModelSerializer):
    quiz_name = serializers.CharField(source="quiz.name", read_only=True)

    class Meta:
        model = QuizScore
        fields = ["id", "quiz_name", "score", "total_questions", "start_time", "end_time"]
