from django.db import models
from django.utils import timezone
from django.db.models import JSONField

class Quiz(models.Model):
    name = models.CharField(max_length=255, unique=True)
    sheet_url = models.URLField()
    is_active = models.BooleanField(default=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
    
class QuizParticipant(models.Model):
    telegram_id = models.BigIntegerField(unique=True)
    username = models.CharField(max_length=150, blank=True, null=True)
    first_name = models.CharField(max_length=150, blank=True, null=True)
    last_name = models.CharField(max_length=150, blank=True, null=True)
    joined = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.username or str(self.telegram_id)

class QuizScore(models.Model):
    participant = models.ForeignKey("QuizParticipant", on_delete=models.CASCADE, related_name="scores")
    quiz = models.ForeignKey("Quiz", on_delete=models.CASCADE, related_name="scores")
    score = models.IntegerField(default=0)
    total_questions = models.IntegerField(default=0)
    start_time = models.DateTimeField(default=timezone.now) 
    end_time = models.DateTimeField(null=True, blank=True) 
    attempt_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.participant} - {self.quiz.name} - {self.score}/{self.total_questions} at {self.attempt_time.strftime('%Y-%m-%d %H:%M')}"

class QuizSession(models.Model):
    participant = models.ForeignKey(QuizParticipant, on_delete=models.CASCADE)
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE)
    score_obj = models.ForeignKey(QuizScore, on_delete=models.CASCADE)
    index = models.IntegerField(default=0)
    score = models.IntegerField(default=0)
    active = models.BooleanField(default=True)
    questions = JSONField(default=list)