from rest_framework import serializers
from .models import Quiz, QuizScore, QuizSession, QuizCategory, QuizAccess, RetryQuizScore

class QuizCategorySerializer(serializers.ModelSerializer):
    quiz_count = serializers.IntegerField(read_only=True)
    class Meta:
        model = QuizCategory
        fields = ["id", "name", "quiz_count"]

class QuizSerializer(serializers.ModelSerializer):
    category = QuizCategorySerializer(many=True, read_only=True)
    total_participants = serializers.SerializerMethodField()
    total_attempts = serializers.SerializerMethodField()
    last_attempt_time = serializers.SerializerMethodField()
    retry_count = serializers.SerializerMethodField()
    total_questions = serializers.SerializerMethodField()
    quiz_creator = serializers.SerializerMethodField()

    class Meta:
        model = Quiz
        fields = [
            "id", "name", "sheet_url", "status", "is_active", "created_date",
            "category", "total_participants", "total_attempts",
            "last_attempt_time", "retry_count", "total_questions", "quiz_creator",
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

    def get_total_questions(self, obj):
        from .utils import get_questions_from_sheet
        try:
            questions = get_questions_from_sheet(obj.sheet_url)
            return len(questions)
        except Exception:
            return 0
        
    def get_quiz_creator(self, obj):  # 👈 new method
        return obj.participant.username if obj.participant else None
        
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

class RetryableScoreSerializer(serializers.Serializer):
    score_id = serializers.IntegerField()
    quiz_name = serializers.CharField()
    missed_count = serializers.IntegerField()