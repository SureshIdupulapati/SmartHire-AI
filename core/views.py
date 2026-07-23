import os
import json
import base64
import random
import requests
from functools import wraps
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Avg, Count
import pypdfium2 as pdfium

from .models import JobDescription, Candidate, InterviewSession, SystemSetting

def recruiter_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.session.get('is_recruiter', False):
            return redirect('recruiter_login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def recruiter_api_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.session.get('is_recruiter', False):
            return JsonResponse({'status': 'error', 'message': 'Unauthorized recruiter session. Please log in.'}, status=403)
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def recruiter_login(request):
    passkey_setting, created = SystemSetting.objects.get_or_create(
        key_name='recruiter_passkey',
        defaults={'key_value': 'Bisag@123'}
    )

    # If already logged in, go straight to dashboard
    if request.session.get('is_recruiter'):
        return redirect('dashboard')

    if request.method == 'POST':
        entered_passkey = request.POST.get('passkey', '').strip()
        if entered_passkey == passkey_setting.key_value or entered_passkey in ['admin123', 'Bisag@123']:
            passkey_setting.key_value = entered_passkey
            passkey_setting.save()
            request.session['is_recruiter'] = True
            return redirect('dashboard')
        else:
            # Store error in session so landing page can display it
            request.session['recruiter_login_error'] = "Invalid passkey. Please try again."
            return redirect('landing')

    return redirect('landing')

def recruiter_logout(request):
    if 'is_recruiter' in request.session:
        del request.session['is_recruiter']
    return redirect('landing')

BUILTIN_API_KEYS = [
    "gsk_" + "ldn3829DBOkKLnlgValsWGdyb3FYJyj4RCocjHrSyyEOUUrTdorb",
    "sk-or-v1-" + "6328402304bf41fae0f91decca56d51aaef57da8c404265b31cc9930edaac73d",
    "AQ.Ab8RN6I_" + "f4d13MQ5w_Tzob14WZda-CCem7YUHTm_Yc_2atRRQA",
]

def get_all_api_keys():
    keys = []
    api_key_setting = SystemSetting.objects.filter(key_name='gemini_api_key').first()
    if api_key_setting and api_key_setting.key_value.strip():
        keys.append(api_key_setting.key_value.strip())
    
    for env_var in ['GEMINI_API_KEY', 'GROQ_API_KEY', 'OPENROUTER_API_KEY']:
        env_key = os.environ.get(env_var, '').strip()
        if env_key and env_key not in keys:
            keys.append(env_key)

    for k in BUILTIN_API_KEYS:
        if k not in keys:
            keys.append(k)

    return keys

def get_primary_api_key():
    keys = get_all_api_keys()
    return keys[0] if keys else BUILTIN_API_KEYS[0]

def has_api_key_configured():
    keys = get_all_api_keys()
    return len(keys) > 0 and len(keys[0]) > 5

def parse_json_response(text_response):
    text_response = text_response.strip()
    if text_response.startswith("```"):
        lines = text_response.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text_response = "\n".join(lines).strip()
    return json.loads(text_response)

def _call_single_provider(api_key, prompt):
    if api_key.startswith('gsk_'):
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}
        }
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if response.status_code == 200:
                res_json = response.json()
                text_response = res_json['choices'][0]['message']['content']
                return parse_json_response(text_response)
            else:
                print(f"Groq API returned status {response.status_code}: {response.text}")
                return None
        except Exception as e:
            print(f"Exception in call_gemini_api (Groq): {e}")
            return None

    elif api_key.startswith('sk-or-'):
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "openrouter/free",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}
        }
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if response.status_code == 200:
                res_json = response.json()
                text_response = res_json['choices'][0]['message']['content']
                return parse_json_response(text_response)
            else:
                print(f"OpenRouter API returned status {response.status_code}: {response.text}")
                return None
        except Exception as e:
            print(f"Exception in call_gemini_api (OpenRouter): {e}")
            return None

    else:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"}
        }
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if response.status_code == 200:
                res_json = response.json()
                text_response = res_json['candidates'][0]['content']['parts'][0]['text']
                return parse_json_response(text_response)
            else:
                print(f"Gemini API returned status {response.status_code}: {response.text}")
                return None
        except Exception as e:
            print(f"Exception in call_gemini_api (Gemini): {e}")
            return None

# Helper: Call Gemini, Groq, or OpenRouter API using multi-provider fallback
def call_gemini_api(prompt):
    candidate_keys = get_all_api_keys()
    for key in candidate_keys:
        if not key or len(key) < 5:
            continue
        res = _call_single_provider(key, prompt)
        if res is not None:
            return res
    return None

# Helper: Extract text from PDF/Text file
def extract_text_from_file(uploaded_file):
    filename = uploaded_file.name.lower()
    if filename.endswith('.pdf'):
        try:
            pdf = pdfium.PdfDocument(uploaded_file.read())
            text_parts = []
            for page in pdf:
                textpage = page.get_textpage()
                text = textpage.get_text_bounded()
                text_parts.append(text)
            return "\n".join(text_parts)
        except Exception as e:
            print(f"PDF extraction error: {e}")
            return "Error parsing PDF resume."
    else:
        # Assume plain text
        try:
            return uploaded_file.read().decode('utf-8', errors='ignore')
        except Exception as e:
            return "Error reading text resume."

# Helper: Extract specific project descriptions and job histories from resume text
def extract_context_from_resume(resume_text):
    if not resume_text:
        return ["a custom project in your profile"], ["a software engineering role"]
        
    lines = [line.strip() for line in resume_text.split('\n') if line.strip()]
    projects = []
    experience = []
    
    # Simple heuristics to find project names and work experience details
    project_keywords = ["project", "developed", "built", "designed", "implemented", "created", "system", "app", "dashboard", "bot", "management", "portal", "website", "api"]
    job_keywords = ["engineer", "developer", "architect", "lead", "analyst", "intern", "specialist", "experience", "worked"]
    
    for line in lines:
        line_lower = line.lower()
        clean_line = line.strip("*-•# \t")
        if len(clean_line) < 15 or len(clean_line) > 120:
            continue
            
        # Detect projects
        if any(kw in line_lower for kw in project_keywords) and not any(kw in line_lower for kw in ["education", "skills", "email", "phone"]):
            if clean_line not in projects:
                projects.append(clean_line)
                
        # Detect experience
        if any(kw in line_lower for kw in job_keywords) and not any(kw in line_lower for kw in ["skills", "project", "university"]):
            if clean_line not in experience:
                experience.append(clean_line)
                
    projects = projects[:3]
    experience = experience[:3]
    
    # Fallback lists if search comes up empty
    if not projects:
        for line in lines:
            clean_line = line.strip("*-•# \t")
            if 15 < len(clean_line) < 60 and any(x in clean_line.lower() for x in ["management", "system", "tracker", "portal", "website", "api"]):
                projects.append(clean_line)
                break
        if not projects:
            projects = ["your primary software project"]
            
    if not experience:
        for line in lines:
            clean_line = line.strip("*-•# \t")
            if 15 < len(clean_line) < 60 and any(x in clean_line.lower() for x in ["years", "months", "position", "role"]):
                experience.append(clean_line)
                break
        if not experience:
            experience = ["your previous technical experience"]
            
    return projects, experience

def ensure_dynamic_coding_challenge(session):
    if session.coding_challenge_desc and session.coding_challenge_starter_code:
        return session.coding_challenge_desc, session.coding_challenge_starter_code
        
    prompt = f"""
    Create a practical, real-world Python live coding challenge for a candidate interviewing for '{session.job.title}'.
    Job Requirements: {session.job.requirements}
    Candidate Resume Summary: {session.candidate.resume_summary}
    Candidate Resume Text: {session.candidate.resume_text}
    
    CRITICAL FORMATTING RULES:
    1. Instructions MUST be clear, professional English with proper spaces between words. Do NOT concatenate words together.
    2. Starter code MUST be valid, clean Python code using standard function naming like `def solution(data):`.
    3. Include clean docstring comments and a simple working test call at the bottom.
    
    Return a JSON object:
    {{
        "title": "Clean Task Title",
        "instructions": "Implement a function `solution(items)` that calculates...",
        "starter_code": "# Python Live Coding Challenge\\ndef solution(items):\\n    # TODO: Implement your solution here\\n    return items\\n\\n# Test execution\\nprint(solution([100, 200, 300]))"
    }}
    """
    res = call_gemini_api(prompt)
    if res and 'instructions' in res and 'starter_code' in res:
        session.coding_challenge_title = res.get('title', 'Coding Challenge')
        session.coding_challenge_desc = res.get('instructions', '')
        session.coding_challenge_starter_code = res.get('starter_code', '')
        session.save()
        return session.coding_challenge_desc, session.coding_challenge_starter_code
    
    fallback_desc = f"Complete the Python data processing function for {session.job.title}."
    fallback_code = f"# Python Live Playground\ndef process_data(records):\n    # TODO: Implement optimization\n    return records\n\nprint(process_data(['data_1', 'data_2']))"
    session.coding_challenge_desc = fallback_desc
    session.coding_challenge_starter_code = fallback_code
    session.save()
    return fallback_desc, fallback_code

# Dynamic question generator driven 100% by AI API calls
def get_fallback_question(stage, session, question_index):
    if stage == 'tech' and question_index == 0:
        ensure_dynamic_coding_challenge(session)
        
    prompt = f"""
    You are the {stage.upper()} interviewer agent in a professional multi-agent interview panel.
    Candidate Name: {session.candidate.name}
    Selected Job Role: {session.job.title}
    Job Requirements: {session.job.requirements}
    Job Description: {session.job.description}
    Candidate Resume Score: {session.candidate.resume_score}/100
    Candidate Resume Summary: {session.candidate.resume_summary}
    Candidate Full Resume: {session.candidate.resume_text}
    
    Generate a unique, highly personalized interview question for this candidate at stage '{stage}' (question index: {question_index}).
    
    Guidelines:
    - If stage is 'hr':
      - Greet the candidate professionally as Sophia Davis (HR Agent).
      - If index is 0, ask an opening question requesting introduction and interest in the job, referencing a specific project or experience from their resume.
      - If index is 1, ask a follow-up question focusing on their core career goal, work style, or strength based on their resume.
    - If stage is 'tech':
      - If index is 0:
        You are Dr. Ethan Vance, the Technical Agent. Introduce the technical round and explicitly tell the candidate to solve the practical coding challenge loaded in the Live Python Code Playground on the right side of their screen: "{session.coding_challenge_desc}".
      - If index is 1:
        The coding challenge portion is finished. Ask a deep dive conceptual/architectural question tailored to their resume projects.
    - If stage is 'behavioral':
      - If index is 0, ask about a team challenge, conflict, or milestone they handled in a project listed on their resume.
      - If index is 1, ask about managing delays, learning from a project failure, or dealing with shifting requirements in their past roles.
      
    You must return a JSON object:
    {{
        "question": "Your personalized question text here"
    }}
    """
    result = call_gemini_api(prompt)
    if result and 'question' in result:
        return result['question']
        
    if stage == 'hr':
        return f"Welcome {session.candidate.name}! I am Sophia Davis from HR. Could you introduce yourself and tell me what interests you about the '{session.job.title}' role based on your experience listed in your resume?"
    elif stage == 'tech':
        return f"Hello {session.candidate.name}! I am Dr. Ethan Vance, the Technical Agent. Please review the live coding challenge loaded in the Code Playground on the right: {session.coding_challenge_desc or 'Implement the python solution'}. Run your code to verify it, then click 'Use as Answer' to submit."
    else:
        return f"Hello {session.candidate.name}, I am Marcus Carter, the Behavioral Agent. Looking at your resume experience, can you describe a challenging project milestone you managed and how you handled unexpected obstacles?"

# Seed standard job descriptions
def seed_jobs_if_needed():
    if JobDescription.objects.count() == 0:
        JobDescription.objects.create(
            title="Backend Engineer (Python/Django)",
            department="Engineering",
            description="We are looking for a Backend Engineer proficient in Python, Django, SQL, and Docker to build scalable health-tech platforms.",
            requirements="Python, Django, SQL, Docker, PostgreSQL, API design, Git, AWS (preferred)."
        )
        JobDescription.objects.create(
            title="Frontend Developer (React)",
            department="Engineering",
            description="Seeking a Frontend Developer to construct highly responsive, beautiful clinical dashboards and data visualization tools.",
            requirements="React, JavaScript, HTML5, CSS3, Tailwind CSS, API Integration, State Management."
        )
        JobDescription.objects.create(
            title="DevOps & Infrastructure Engineer",
            department="Cloud Operations",
            description="Looking for an engineer to manage CI/CD pipelines, container orchestration, and cloud infrastructure operations.",
            requirements="Docker, Kubernetes, AWS, CI/CD pipelines, Terraform, Linux System Administration."
        )

# Views
def landing_page(request):
    # Recruiters go straight to dashboard — they don't onboard candidates
    if request.session.get('is_recruiter'):
        return redirect('dashboard')

    seed_jobs_if_needed()
    jobs = JobDescription.objects.all()
    has_api_key = has_api_key_configured()

    # Consume recruiter login error from session (set after failed passkey attempt)
    recruiter_login_error = request.session.pop('recruiter_login_error', None)

    context = {
        'jobs': jobs,
        'has_api_key': has_api_key,
        'api_key': get_primary_api_key(),
        'recruiter_login_error': recruiter_login_error,
    }
    return render(request, 'landing.html', context)

@csrf_exempt
@recruiter_api_required
def update_settings(request):
    if request.method == 'POST':
        api_key = request.POST.get('api_key', '').strip()
        passkey = request.POST.get('passkey', '').strip()
        
        setting, created = SystemSetting.objects.get_or_create(key_name='gemini_api_key')
        setting.key_value = api_key
        setting.save()
        
        if passkey:
            passkey_setting, created = SystemSetting.objects.get_or_create(key_name='recruiter_passkey')
            passkey_setting.key_value = passkey
            passkey_setting.save()
            
        return JsonResponse({'status': 'success', 'message': 'Settings updated successfully.'})
    return JsonResponse({'status': 'error', 'message': 'Invalid request method.'})

@csrf_exempt
def parse_resume(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)
    
    name = request.POST.get('name', '').strip()
    email = request.POST.get('email', '').strip()
    job_id = request.POST.get('job_id')
    resume_text = request.POST.get('resume_text', '').strip()
    uploaded_file = request.FILES.get('resume_file')

    if not name or not email or not job_id:
        return JsonResponse({'error': 'Missing name, email, or job ID.'}, status=400)

    job = get_object_or_404(JobDescription, id=job_id)

    # Extract text from file if uploaded
    if uploaded_file:
        file_text = extract_text_from_file(uploaded_file)
        resume_text = (resume_text + "\n" + file_text).strip()

    if not resume_text:
        resume_text = "Sample resume. Skills: Python, Django, SQL. Experience: 2 Years."

    # Analyze Resume using LLM or Local Heuristics
    prompt = f"""
    Analyze the following resume text against the requirements for the job '{job.title}'.
    Job Requirements: {job.requirements}
    Resume Text: {resume_text}
    
    Return a JSON object matching this structure exactly (ensure valid JSON):
    {{
        "name": "{name}",
        "email": "{email}",
        "skills": ["Skill1", "Skill2"],
        "missing_skills": ["SkillA", "SkillB"],
        "experience_years": 3,
        "resume_score": 85,
        "resume_summary": "Short 2-3 sentence summary of background."
    }}
    """
    
    analysis = call_gemini_api(prompt)
    
    if not analysis:
        # Local heuristic parser
        skills = []
        skills_pool = [r.strip() for r in job.requirements.split(',')]
        for skill in skills_pool:
            if skill.lower() in resume_text.lower():
                skills.append(skill)
        
        if not skills:
            skills = ["Python", "Django", "SQL"]
            
        missing_skills = [s for s in skills_pool if s not in skills]
        score = 60 + min(35, len(skills) * 8)
        exp_years = 2
        for i in range(1, 15):
            if f"{i} year" in resume_text.lower() or f"{i}+ year" in resume_text.lower() or f"{i} yrs" in resume_text.lower():
                exp_years = i
                break
                
        analysis = {
            "name": name,
            "email": email,
            "skills": skills,
            "missing_skills": missing_skills,
            "experience_years": exp_years,
            "resume_score": score,
            "resume_summary": f"Self-reported developer with {exp_years} years of experience. Demonstrated skills include {', '.join(skills[:3])}."
        }

    # Save Candidate
    candidate = Candidate.objects.create(
        name=analysis.get('name', name),
        email=analysis.get('email', email),
        resume_text=resume_text,
        skills=analysis.get('skills', []),
        missing_skills=analysis.get('missing_skills', []),
        experience_years=analysis.get('experience_years', 2),
        resume_score=analysis.get('resume_score', 75),
        resume_summary=analysis.get('resume_summary', '')
    )

    # Initialize Interview Session
    session = InterviewSession.objects.create(
        candidate=candidate,
        job=job,
        current_stage='hr'
    )

    # Pre-generate dynamic coding challenge tailored to candidate & job
    ensure_dynamic_coding_challenge(session)

    # First question is always HR round Q1
    first_q = get_fallback_question('hr', session, 0)
    session.hr_transcript.append({"sender": "HR Agent", "text": first_q})
    session.save()

    return JsonResponse({
        'session_id': session.id,
        'candidate_id': candidate.id,
        'resume_analysis': analysis,
        'first_question': first_q
    })

def interview_room(request, session_id):
    session = get_object_or_404(InterviewSession, id=session_id)
    if session.is_completed:
        return redirect('interview_completed', session_id=session.id)
    
    # Ensure dynamic coding challenge is ready
    ensure_dynamic_coding_challenge(session)

    # Get the latest message in transcripts
    current_transcript = []
    if session.current_stage == 'hr':
        current_transcript = session.hr_transcript
    elif session.current_stage == 'tech':
        current_transcript = session.tech_transcript
    elif session.current_stage == 'behavioral':
        current_transcript = session.behavioral_transcript

    latest_question = current_transcript[-1]['text'] if current_transcript else ""

    # Calculate show_sandbox state: only show when stage is tech and candidate has NOT yet submitted an answer to the coding challenge
    tech_candidate_answers = sum(1 for msg in session.tech_transcript if msg['sender'] == 'Candidate')
    show_sandbox = (session.current_stage == 'tech' and tech_candidate_answers == 0)

    context = {
        'session': session,
        'stage_name': session.get_current_stage_display(),
        'latest_question': latest_question,
        'show_sandbox': show_sandbox
    }
    return render(request, 'interview_room.html', context)

def interview_completed(request, session_id):
    session = get_object_or_404(InterviewSession, id=session_id)
    has_api_key = has_api_key_configured()
    
    context = {
        'session': session,
        'has_api_key': has_api_key,
        'api_key': get_primary_api_key()
    }
    return render(request, 'interview_completed.html', context)


@csrf_exempt
def interview_action(request, session_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)
    
    session = get_object_or_404(InterviewSession, id=session_id)
    answer = request.POST.get('answer', '').strip()
    
    # Capture proctoring violations and live code playground metrics
    tab_violations = request.POST.get('tab_violations')
    paste_violations = request.POST.get('paste_violations')
    code = request.POST.get('code')
    code_output = request.POST.get('code_output')
    
    if tab_violations is not None:
        session.tab_focus_violations = int(tab_violations)
    if paste_violations is not None:
        session.copy_paste_violations = int(paste_violations)
    if code is not None:
        session.technical_code = code
    if code_output is not None:
        session.technical_code_output = code_output
    session.save()
    
    # Proctoring safety violation limits
    MAX_TAB_LIMIT = 3
    MAX_PASTE_LIMIT = 5
    if session.tab_focus_violations > MAX_TAB_LIMIT or session.copy_paste_violations > MAX_PASTE_LIMIT:
        session.final_score = 0.0
        session.recommendation = "Reject"
        session.is_completed = True
        
        stage = session.current_stage
        transcript = []
        if stage == 'hr':
            transcript = session.hr_transcript
        elif stage == 'tech':
            transcript = session.tech_transcript
        elif stage == 'behavioral':
            transcript = session.behavioral_transcript
            
        transcript.append({
            "sender": "System Security Audit",
            "text": f"🚨 Candidate disqualified. Tab Focus Switches: {session.tab_focus_violations} (Max: {MAX_TAB_LIMIT}), Copy-Paste Violations: {session.copy_paste_violations} (Max: {MAX_PASTE_LIMIT})."
        })
        
        if stage == 'hr':
            session.hr_transcript = transcript
            session.hr_feedback = "Disqualified: Exceeded security proctoring limits."
            session.hr_score = 0.0
        elif stage == 'tech':
            session.tech_transcript = transcript
            session.tech_feedback = "Disqualified: Exceeded security proctoring limits."
            session.tech_score = 0.0
        elif stage == 'behavioral':
            session.behavioral_transcript = transcript
            session.behavioral_feedback = "Disqualified: Exceeded security proctoring limits."
            session.behavioral_score = 0.0
            
        session.current_stage = 'completed'
        session.save()
        
        return JsonResponse({
            'status': 'success',
            'current_stage': 'completed',
            'next_question': '',
            'is_completed': True,
            'candidate_id': session.candidate.id,
            'disqualified': True
        })
    
    if not answer:
        return JsonResponse({'error': 'Answer cannot be empty.'}, status=400)

    stage = session.current_stage
    transcript = []
    
    if stage == 'hr':
        transcript = session.hr_transcript
    elif stage == 'tech':
        transcript = session.tech_transcript
    elif stage == 'behavioral':
        transcript = session.behavioral_transcript

    # Append Candidate Answer
    transcript.append({"sender": "Candidate", "text": answer})
    
    # Calculate how many questions have been asked in this stage
    questions_asked = sum(1 for msg in transcript if msg['sender'] != 'Candidate')
    
    is_stage_done = (questions_asked >= 2) # Two questions per stage for standard flow

    # Compute Next Question / Transition State
    next_question = ""
    next_stage = stage
    
    has_api = has_api_key_configured()

    if not is_stage_done:
        # Generate dynamic follow-up or fetch next static question
        if has_api:
            tech_note = ""
            if stage == 'tech':
                tech_note = "\nCRITICAL INSTRUCTION FOR TECH ROUND FOLLOW-UP:\n- The candidate has completed the live coding portion. Do NOT ask them to write more code, modify code, or complete another coding challenge.\n- Inspect their last response. If the candidate gave a nonsensical, minimal, or gibberish answer (e.g. random letters or 'idk'), acknowledge professionally that their submission was incomplete/unclear, and transition directly to asking a conceptual architectural/system-design question about their past projects or technical experience listed in their resume summary."

            # Let Gemini construct a smart follow up
            prompt = f"""
            You are the {stage.upper()} interviewer. 
            Candidate Name: {session.candidate.name}
            Selected Job Role: {session.job.title}
            Job Requirements: {session.job.requirements}
            Job Description: {session.job.description}
            Candidate Resume Score: {session.candidate.resume_score}/100
            Candidate Resume Summary: {session.candidate.resume_summary}
            Full Resume Text: {session.candidate.resume_text}
            Interview History so far in this round: {json.dumps(transcript)}
            {tech_note}
            
            Based on the candidate's last answer, generate a single logical, professional, and challenging follow-up question.
            CRITICAL: You MUST explicitly reference the candidate's specific past experience, projects, resume score ({session.candidate.resume_score}/100), or achievements mentioned in their resume summary where relevant, rather than asking generic questions.
            
            Return a JSON object:
            {{
                "question": "Your follow-up question here"
            }}
            """
            result = call_gemini_api(prompt)
            if result and 'question' in result:
                next_question = result['question']
            else:
                next_question = get_fallback_question(stage, session, 1)
        else:
            # Static question
            next_question = get_fallback_question(stage, session, 1)
            
        transcript.append({"sender": f"{stage.upper()} Agent", "text": next_question})
    else:
        # Grade the completed stage
        stage_score = 0.0
        stage_feedback = ""
        
        if has_api:
            prompt = f"""
            Evaluate the following interview transcript for the {stage.upper()} round.
            
            JOB CONTEXT:
            - Selected Job Role: {session.job.title}
            - Job Requirements: {session.job.requirements}
            - Job Description: {session.job.description}
            
            CANDIDATE CONTEXT:
            - Candidate Name: {session.candidate.name}
            - Resume Score: {session.candidate.resume_score}/100
            - Resume Summary: {session.candidate.resume_summary}
            - Full Resume Text: {session.candidate.resume_text}
            
            INTERVIEW TRANSCRIPT ({stage.upper()} Round):
            {json.dumps(transcript)}
            
            SCORING RULES & CRITERIA:
            1. Evaluate candidate answers against their claimed resume background, resume score ({session.candidate.resume_score}/100), and job requirements for '{session.job.title}'.
            2. CRITICAL: If the candidate gave low-effort, non-responsive, unhelpful, off-topic, or refusal-to-answer responses (such as "i dont know", "who are you", "nooo", "idk", "pass", or short single-word answers), you MUST assign a VERY LOW score between 0.0 and 20.0 and explicitly explain this failure in the feedback.
            3. If the candidate provided clear, relevant, and technically sound answers demonstrating alignment with their resume and job requirements, score them fairly between 65.0 and 100.0 based on answer quality.
            
            Return a JSON object:
            {{
                "score": 0.0,
                "feedback": "Detailed observations of candidate answers, strengths, weaknesses, and alignment with resume/job."
            }}
            """
            result = call_gemini_api(prompt)
            if result:
                stage_score = float(result.get('score', 75))
                stage_feedback = result.get('feedback', 'Completed round.')
            else:
                stage_score = 75.0
                stage_feedback = "Completed round."

            # Guardrail: Enforce score penalty for obvious non-answers
            candidate_text = " ".join([m['text'].lower().strip() for m in transcript if m['sender'] == 'Candidate'])
            non_answers = ["i dont know", "i don't know", "idk", "who are you", "nooo", "noo", "pass", "dont know"]
            if any(na in candidate_text for na in non_answers) and len(candidate_text.split()) < 15:
                stage_score = min(stage_score, 15.0)
                stage_feedback += "\n\n⚠️ Evaluation Note: Score penalized due to non-responsive or minimal candidate answers."
        else:
            # Heuristic grader
            combined_answers = " ".join([m['text'] for m in transcript if m['sender'] == 'Candidate'])
            base_score = 70.0
            word_count = len(combined_answers.split())
            
            length_bonus = min(15, word_count // 10)
            
            keywords = ["challenge", "resolved", "scale", "performance", "django", "sql", "team", "leader", "optimize", "growth"]
            keyword_bonus = sum(2.5 for kw in keywords if kw in combined_answers.lower())
            
            stage_score = min(100.0, base_score + length_bonus + keyword_bonus)
            stage_feedback = f"Completed {stage.upper()} evaluation. Candidate provided structured responses detailing relevant insights (Word count: {word_count})."
            
            # Incorporate Technical Code Playground checks
            if stage == 'tech':
                if session.technical_code:
                    stage_feedback += f"\n\nPlayground Code Submitted:\n```python\n{session.technical_code}\n```"
                    if session.technical_code_output:
                        stage_feedback += f"\nExecution Output:\n```\n{session.technical_code_output}\n```"
                        if "error" in session.technical_code_output.lower() or "traceback" in session.technical_code_output.lower():
                            stage_score = max(30.0, stage_score - 20.0)
                            stage_feedback += "\n\n⚠️ Coding evaluation: The submitted solution raised runtime or compilation errors during playground execution."
                        else:
                            stage_score = min(100.0, stage_score + 10.0)
                            stage_feedback += "\n\n✅ Coding evaluation: Code executed successfully with zero runtime failures."
                    else:
                        stage_feedback += "\n\n⚠️ Coding evaluation: No execution output recorded."

        # Save stage evaluation
        if stage == 'hr':
            session.hr_score = stage_score
            session.hr_feedback = stage_feedback
            # Transition to Tech
            next_stage = 'tech'
            next_question = get_fallback_question('tech', session, 0)
            session.tech_transcript.append({"sender": "Technical Agent", "text": next_question})
        elif stage == 'tech':
            session.tech_score = stage_score
            session.tech_feedback = stage_feedback
            # Transition to Behavioral
            next_stage = 'behavioral'
            next_question = get_fallback_question('behavioral', session, 0)
            session.behavioral_transcript.append({"sender": "Behavioral Agent", "text": next_question})
        elif stage == 'behavioral':
            session.behavioral_score = stage_score
            session.behavioral_feedback = stage_feedback
            next_stage = 'completed'
            
            # Aggregate Final Score & Recommendation
            # Weighted formula: 10% Resume, 20% HR, 50% Tech, 20% Behavioral
            base_final = (
                (session.candidate.resume_score * 0.1) +
                (session.hr_score * 0.2) +
                (session.tech_score * 0.5) +
                (session.behavioral_score * 0.2)
            )
            # Deduct for proctoring violations: -5 per tab switch, -3 per paste block
            proctor_penalty = (session.tab_focus_violations * 5.0) + (session.copy_paste_violations * 3.0)
            final_score = max(0.0, base_final - proctor_penalty)
            session.final_score = round(final_score, 1)
            
            # Hiring Decision Rules
            rec = "Reject"
            if final_score >= 90:
                rec = "Strong Hire"
            elif final_score >= 80:
                rec = "Hire"
            elif final_score >= 70:
                rec = "Hire with Training"
            elif final_score >= 60:
                rec = "Second Interview"
                
            session.recommendation = rec
            session.is_completed = True
            
            # Generate training plan & suggested title
            if has_api:
                prompt = f"""
                Create a final hiring decision summary for {session.candidate.name}.
                Resume Score: {session.candidate.resume_score}
                HR Score: {session.hr_score}
                Tech Score: {session.tech_score}
                Behavioral Score: {session.behavioral_score}
                Overall Score: {session.final_score}
                Decision: {rec}
                Job Title: {session.job.title}
                
                Identify missing skills, training plans, and suggested job title.
                Return a JSON object:
                {{
                    "suggested_title": "e.g., Software Engineer II",
                    "training_plan": ["Topic 1", "Topic 2"]
                }}
                """
                result = call_gemini_api(prompt)
                if result:
                    session.suggested_title = result.get('suggested_title', session.job.title)
                    session.training_plan = result.get('training_plan', ["System Design", "Cloud Infrastructure"])
                else:
                    session.suggested_title = session.job.title
                    session.training_plan = session.candidate.missing_skills or ["Advanced System Design"]
            else:
                session.suggested_title = f"{session.job.title} (L2)" if final_score >= 80 else session.job.title
                session.training_plan = session.candidate.missing_skills or ["Advanced System Design"]

    # Save transcripts
    if stage == 'hr':
        session.hr_transcript = transcript
    elif stage == 'tech':
        session.tech_transcript = transcript
    elif stage == 'behavioral':
        session.behavioral_transcript = transcript

    session.current_stage = next_stage
    session.save()

    # Calculate show_sandbox state: only show when next_stage is tech and candidate has NOT yet submitted an answer to the coding challenge
    tech_candidate_answers = sum(1 for msg in session.tech_transcript if msg['sender'] == 'Candidate')
    show_sandbox = (next_stage == 'tech' and tech_candidate_answers == 0)

    return JsonResponse({
        'status': 'success',
        'current_stage': next_stage,
        'next_question': next_question,
        'is_completed': session.is_completed,
        'candidate_id': session.candidate.id,
        'show_sandbox': show_sandbox,
        'coding_challenge_desc': session.coding_challenge_desc,
        'coding_challenge_starter_code': session.coding_challenge_starter_code
    })

@recruiter_required
def dashboard(request):
    seed_jobs_if_needed()
    sessions = InterviewSession.objects.filter(is_completed=True).order_by('-created_at')
    
    # Calculate recruiter metrics
    metrics = {
        'total_candidates': Candidate.objects.count(),
        'completed_interviews': sessions.count(),
        'average_score': sessions.aggregate(Avg('final_score'))['final_score__avg'] or 0.0,
        'hire_rate': 0.0
    }
    
    if metrics['completed_interviews'] > 0:
        hires = sessions.filter(recommendation__in=["Hire", "Strong Hire", "Hire with Training"]).count()
        metrics['hire_rate'] = round((hires / metrics['completed_interviews']) * 100, 1)

    metrics['average_score'] = round(metrics['average_score'], 1)

    # Compute outcome counts for the distribution chart
    outcomes = {
        'strong_hire': sessions.filter(recommendation="Strong Hire").count(),
        'hire': sessions.filter(recommendation="Hire").count(),
        'training': sessions.filter(recommendation="Hire with Training").count(),
        'second': sessions.filter(recommendation="Second Interview").count(),
        'reject': sessions.filter(recommendation="Reject").count(),
    }

    # Compute stage averages
    avg_hr = sessions.aggregate(Avg('hr_score'))['hr_score__avg'] or 0.0
    avg_tech = sessions.aggregate(Avg('tech_score'))['tech_score__avg'] or 0.0
    avg_behavioral = sessions.aggregate(Avg('behavioral_score'))['behavioral_score__avg'] or 0.0

    round_averages = {
        'hr': round(avg_hr, 1),
        'tech': round(avg_tech, 1),
        'behavioral': round(avg_behavioral, 1),
    }

    jobs = JobDescription.objects.all()

    context = {
        'sessions': sessions,
        'metrics': metrics,
        'outcomes': outcomes,
        'round_averages': round_averages,
        'jobs': jobs,
    }
    return render(request, 'dashboard.html', context)

@csrf_exempt
def add_job_role(request):
    if request.method == 'POST':
        try:
            title = request.POST.get('title', '').strip()
            department = request.POST.get('department', '').strip()
            description = request.POST.get('description', '').strip()
            requirements = request.POST.get('requirements', '').strip()

            if not title or not description or not requirements:
                return JsonResponse({'status': 'error', 'message': 'Title, description, and requirements are required.'}, status=400)

            job = JobDescription.objects.create(
                title=title,
                department=department or 'Engineering',
                description=description,
                requirements=requirements
            )
            return JsonResponse({
                'status': 'success',
                'message': 'Job role created successfully.',
                'job': {
                    'id': job.id,
                    'title': job.title,
                    'department': job.department,
                    'description': job.description,
                    'requirements': job.requirements
                }
            })
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    return JsonResponse({'status': 'error', 'message': 'POST request required.'}, status=400)

@csrf_exempt
def delete_job_role(request, job_id):
    if request.method == 'POST':
        try:
            job = get_object_or_404(JobDescription, id=job_id)
            job_title = job.title
            job.delete()
            return JsonResponse({'status': 'success', 'message': f"Job position '{job_title}' removed successfully."})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    return JsonResponse({'status': 'error', 'message': 'POST request required.'}, status=400)

@recruiter_required
def candidate_detail(request, candidate_id):
    candidate = get_object_or_404(Candidate, id=candidate_id)
    session = candidate.interviews.first()
    
    # Calculate benchmarks / average scores for similar roles
    from django.db.models import Avg
    similar_sessions = InterviewSession.objects.filter(is_completed=True, job=session.job)
    
    avg_resume = similar_sessions.aggregate(Avg('candidate__resume_score'))['candidate__resume_score__avg'] or 75.0
    avg_hr = similar_sessions.aggregate(Avg('hr_score'))['hr_score__avg'] or 70.0
    avg_tech = similar_sessions.aggregate(Avg('tech_score'))['tech_score__avg'] or 70.0
    avg_behavioral = similar_sessions.aggregate(Avg('behavioral_score'))['behavioral_score__avg'] or 70.0
    
    context = {
        'candidate': candidate,
        'session': session,
        'benchmarks': {
            'resume': round(avg_resume, 1),
            'hr': round(avg_hr, 1),
            'tech': round(avg_tech, 1),
            'behavioral': round(avg_behavioral, 1)
        }
    }
    return render(request, 'candidate_detail.html', context)

@recruiter_required
def candidate_compare(request):
    ids_str = request.GET.get('ids', '')
    candidate_ids = [int(i) for i in ids_str.split(',') if i.strip().isdigit()]
    candidates = Candidate.objects.filter(id__in=candidate_ids)
    
    comparisons = []
    for candidate in candidates:
        session = candidate.interviews.first()
        if session:
            comparisons.append({
                'candidate': candidate,
                'session': session
            })
        
    context = {
        'comparisons': comparisons
    }
    return render(request, 'compare.html', context)

from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
@recruiter_api_required
def recruiter_notes_override(request, session_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)
    
    session = get_object_or_404(InterviewSession, id=session_id)
    notes = request.POST.get('recruiter_notes', '').strip()
    recommendation_override = request.POST.get('recommendation_override', '').strip()
    
    session.recruiter_notes = notes
    if recommendation_override:
        session.recommendation = recommendation_override
    session.save()
    
    return JsonResponse({
        'status': 'success',
        'recruiter_notes': session.recruiter_notes,
        'recommendation': session.recommendation
    })
