from django.db import models
from django.utils import timezone
from django.db.models import JSONField
from .constant import STATUS_CHOICES

class Quiz(models.Model):
    name = models.CharField(max_length=255, unique=True)
    sheet_url = models.URLField()
    is_active = models.BooleanField(default=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='public')
    participant = models.ForeignKey(
        "QuizParticipant", on_delete=models.SET_NULL, null=True, blank=True, related_name="quizzes"
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
    
class QuizParticipant(models.Model):
    telegram_id = models.BigIntegerField(unique=True, db_index=True)
    username = models.CharField(max_length=150, blank=True, null=True)
    first_name = models.CharField(max_length=150, blank=True, null=True)
    last_name = models.CharField(max_length=150, blank=True, null=True)
    joined = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True, db_index=True)

    def __str__(self):
        return self.username or str(self.telegram_id)
    class Meta:
        verbose_name = "Participant"
        verbose_name_plural = "Participants"

class QuizScore(models.Model):
    participant = models.ForeignKey("QuizParticipant", on_delete=models.CASCADE, related_name="scores")
    quiz = models.ForeignKey("Quiz", on_delete=models.CASCADE, related_name="scores")
    score = models.IntegerField(default=0)
    total_questions = models.IntegerField(default=0)
    start_time = models.DateTimeField(default=timezone.now) 
    end_time = models.DateTimeField(null=True, blank=True, db_index=True) 
    attempt_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.participant} - {self.quiz.name} - {self.score}/{self.total_questions} at {self.attempt_time.strftime('%Y-%m-%d %H:%M')}"
    class Meta:
        ordering = ['-attempt_time']

class QuizSession(models.Model):
    participant = models.ForeignKey(QuizParticipant, on_delete=models.CASCADE, related_name="sessions")
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="sessions")
    score_obj = models.ForeignKey(QuizScore, on_delete=models.CASCADE, related_name="sessions")
    index = models.IntegerField(default=0)
    score = models.IntegerField(default=0)
    active = models.BooleanField(default=True, db_index=True)
    questions = JSONField(default=list)