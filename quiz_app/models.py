from django.db import models
from django.utils import timezone
from django.db.models import JSONField
from .constant import STATUS_CHOICES, ACCESS_TYPE_CHOICES

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
    
    def get_access_type(self, participant):
        if self.participant == participant:
            return "full_access"
        access = self.accesses.filter(participant=participant).first()
        return access.access_type if access else None

    def is_accessible_by(self, participant):
        return (
            self.status == "public" or
            self.participant == participant or
            self.accesses.filter(participant=participant).exists()
        )

    def can_participant_edit(self, participant):
        if self.participant == participant:
            return True
        access = self.accesses.filter(participant=participant, access_type="full_access").first()
        return bool(access)
    
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

class QuizAccess(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="accesses")
    participant = models.ForeignKey(QuizParticipant, on_delete=models.CASCADE, related_name="accessible_quizzes")
    granted_by = models.ForeignKey(QuizParticipant, on_delete=models.SET_NULL, null=True, blank=True, related_name="granted_accesses")
    access_type = models.CharField(max_length=20, choices=ACCESS_TYPE_CHOICES, default="participate_access")
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("quiz", "participant")
        verbose_name = "Quiz Access"
        verbose_name_plural = "Quiz Accesses"

    def __str__(self):
        return f"{self.participant} has {self.access_type} to {self.quiz.name}"

class QuizScore(models.Model):
    participant = models.ForeignKey("QuizParticipant", on_delete=models.CASCADE, related_name="scores")
    quiz = models.ForeignKey("Quiz", on_delete=models.CASCADE, related_name="scores")
    score = models.IntegerField(default=0)
    total_questions = models.IntegerField(default=0)
    missed_questions = JSONField(default=list, blank=True)
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

class RetryQuizScore(models.Model):
    original_score = models.ForeignKey(QuizScore, on_delete=models.CASCADE, related_name="retry_attempts")
    score = models.IntegerField(default=0)
    total_questions = models.IntegerField(default=0, editable=False)
    missed_questions = models.JSONField(default=list, blank=True)
    index = models.IntegerField(default=0)
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.total_questions:
            self.total_questions = len(self.original_score.missed_questions or [])
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Retry by {self.original_score.participant} on {self.original_score.quiz.name} – {self.score}/{self.total_questions}"
    
class RetrySession(models.Model):
    participant = models.ForeignKey(QuizParticipant, on_delete=models.CASCADE)
    retry = models.ForeignKey(RetryQuizScore, on_delete=models.CASCADE)
    active = models.BooleanField(default=True)
    expecting_answer = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

