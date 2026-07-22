from django.db import models

class JobDescription(models.Model):
    title = models.CharField(max_length=200)
    department = models.CharField(max_length=100, blank=True)
    description = models.TextField()
    requirements = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

class Candidate(models.Model):
    name = models.CharField(max_length=200)
    email = models.EmailField()
    resume_text = models.TextField(blank=True)
    skills = models.JSONField(default=list)
    missing_skills = models.JSONField(default=list)
    experience_years = models.IntegerField(default=0)
    resume_score = models.IntegerField(default=0)
    resume_summary = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class InterviewSession(models.Model):
    STAGE_CHOICES = [
        ('hr', 'HR Round'),
        ('tech', 'Technical Round'),
        ('behavioral', 'Behavioral Round'),
        ('completed', 'Completed'),
    ]

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='interviews')
    job = models.ForeignKey(JobDescription, on_delete=models.CASCADE, related_name='interviews')
    current_stage = models.CharField(max_length=20, choices=STAGE_CHOICES, default='hr')
    
    # Store chat history as list of dicts: [{"sender": "HR Agent", "text": "Question"}, {"sender": "Candidate", "text": "Answer"}]
    hr_transcript = models.JSONField(default=list)
    tech_transcript = models.JSONField(default=list)
    behavioral_transcript = models.JSONField(default=list)
    
    # Individual scores (out of 100)
    hr_score = models.FloatField(default=0.0)
    tech_score = models.FloatField(default=0.0)
    behavioral_score = models.FloatField(default=0.0)
    
    # Detailed agent feedback
    hr_feedback = models.TextField(blank=True)
    tech_feedback = models.TextField(blank=True)
    behavioral_feedback = models.TextField(blank=True)
    
    # Aggregated metrics
    final_score = models.FloatField(default=0.0)
    recommendation = models.CharField(max_length=50, blank=True) # Strong Hire, Hire, Hire with Training, Second Interview, Reject
    suggested_title = models.CharField(max_length=100, blank=True)
    training_plan = models.JSONField(default=list)
    
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Proctoring & Anti-cheating fields
    tab_focus_violations = models.IntegerField(default=0)
    copy_paste_violations = models.IntegerField(default=0)
    
    # Live Coding fields
    technical_code = models.TextField(blank=True, default='')
    technical_code_output = models.TextField(blank=True, default='')
    coding_challenge_title = models.CharField(max_length=255, blank=True, default='')
    coding_challenge_desc = models.TextField(blank=True, default='')
    coding_challenge_starter_code = models.TextField(blank=True, default='')
    
    # Recruiter Override & Notes
    recruiter_notes = models.TextField(blank=True, default='')

    def __str__(self):
        return f"{self.candidate.name} - {self.job.title}"

class SystemSetting(models.Model):
    key_name = models.CharField(max_length=100, unique=True)
    key_value = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.key_name
