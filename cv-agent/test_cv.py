import os, sys
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))
import tools

tools.init_db()

CV_TEXT = """
Mark Melad Attia
AI Engineer
markmelad21@outlook.com  +20 120 478 1311  Cairo, Abassia  LinkedIn: mark-melad  GitHub: mark-melad

Career Objective
Motivated biomedical informatics graduate with strong skills in computer science, programming, and data
analytics, seeking an entry-level role in Data Engineering or AI Engineering to build efficient data pipelines
and develop intelligent, data-driven solutions.

Education
Bachelor of Computer Science Biomedical Informatics, Nile University, Cairo
GPA: 3.85 — 2020-2024

Professional Experience
AI Software Engineer, Elama.ai (12/2025 - Present, Cairo)
- Designed and developed AI-powered software applications and production-ready systems
- Implemented and integrated machine learning models with backend services and APIs
- Wrote scalable, maintainable code following software engineering best practices
- Collaborated with cross-functional teams to deliver reliable, data-driven solutions

Projects
Graduation Project: Analyzing Microbiome Biomarkers for Diagnosing COPD (Meta-analysis)
- Identified COPD-associated microbial biomarkers via microbiome meta-analysis
- Built ML models achieving 82% accuracy in classifying healthy vs. COPD cases

Abdominal Trauma Detection using Image Processing and Deep Learning
- Developed an abdominal trauma detection system using image processing and CNN-based deep learning

Psychiatrist Desktop Application
- Developed a psychiatrist desktop application in C# with SQL backend

Colorectal Cancer Prediction Using Gene Expression Data
- Developed a ML model achieving 93% accuracy

Skills
Languages: Python, Java, C++, C#, SQL, R, HTML/CSS/JS
Tools: Git, Pandas, PostgreSQL, MySQL, SnowFlakeSQL
Frameworks: TensorFlow, PyTorch, Scikit-learn

Volunteering
Helmya Armed Forces Hospital - IT Support & Systems Administrator (11/2024 - 12/2025)
InsiderNU, Vice President (2023-2024)
Head of HR (2022-2023)

Certifications
DataCamp: Machine Learning Scientist with Python
DataCamp: Introduction to APIs in Python
DataCamp: Associate Data Engineer in SQL
DataCamp: Cleaning Data in Python

Languages: Arabic (Native), English (Fluent)
"""

FILENAME = "Mark_Melad_CV2025.pdf"
MSG_ID   = "test-manual-002"

print("\n-- Step 1: Extract contact info via Groq --")
contact = tools.extract_contact(CV_TEXT)
print(f"  name    : {contact['name']}")
print(f"  email   : {contact['email']}")
print(f"  phone   : {contact['phone']}")
print(f"  title   : {contact['title']}")
print(f"  summary : {str(contact['summary'])[:120]}...")

print("\n-- Step 2: Save to database --")
tools.save_candidate({
    "name":            contact["name"],
    "email":           contact["email"],
    "phone":           contact["phone"],
    "title":           contact["title"],
    "summary":         contact["summary"],
    "source_file":     FILENAME,
    "source_email_id": MSG_ID,
    "email_sent":      0,
    "error":           None,
})
print("  Saved.")

print("\n-- Step 3: Send welcome email --")
if contact["email"]:
    success = tools.send_welcome_email(contact["name"], contact["email"], contact["title"])
    if success:
        tools._update_candidate(MSG_ID, FILENAME, email_sent=1)
        print(f"  Welcome email sent to {contact['email']} - OK")
    else:
        tools._update_candidate(MSG_ID, FILENAME, error="email send failed")
        print("  Email send FAILED -- check SMTP credentials")
else:
    tools._update_candidate(MSG_ID, FILENAME, error="no email found in CV")
    print("  No email found in CV")

print("\n-- Step 4: DB stats --")
stats = tools.get_stats()
print(f"  total={stats['total']}  emailed={stats['emailed']}  pending={stats['pending']}  errors={stats['errors']}")

print("\n-- Done. Refresh http://localhost:8000 to see the result. --\n")
