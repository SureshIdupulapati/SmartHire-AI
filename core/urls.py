from django.urls import path
from . import views

urlpatterns = [
    path('', views.landing_page, name='landing'),
    path('api/update-settings/', views.update_settings, name='update_settings'),
    path('api/parse-resume/', views.parse_resume, name='parse_resume'),
    path('interview/<int:session_id>/', views.interview_room, name='interview_room'),
    path('api/interview/<int:session_id>/action/', views.interview_action, name='interview_action'),
    path('interview/<int:session_id>/completed/', views.interview_completed, name='interview_completed'),
    path('dashboard/login/', views.recruiter_login, name='recruiter_login'),
    path('dashboard/logout/', views.recruiter_logout, name='recruiter_logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/candidate/<int:candidate_id>/', views.candidate_detail, name='candidate_detail'),
    path('dashboard/compare/', views.candidate_compare, name='candidate_compare'),
    path('api/session/<int:session_id>/notes-override/', views.recruiter_notes_override, name='recruiter_notes_override'),
    path('api/job-role/add/', views.add_job_role, name='add_job_role'),
    path('api/job-role/delete/<int:job_id>/', views.delete_job_role, name='delete_job_role'),
]
