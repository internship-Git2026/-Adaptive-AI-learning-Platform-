# AI Adaptive Learning Platform 🎓

> An intelligent education platform for **GATE** and **NEET** exam preparation, powered by AI/LLM technology.

## 🔗 Live Demo

> *Deploy your own instance — see [Deployment](#-deployment) below.*

## 🌟 Core Features

### 1. 🤖 AI-Powered Quizzes
- Upload PDF study materials and auto-generate quizzes using **Groq LLM**
- AI analyzes PDF content and creates contextual MCQ questions
- Topic-wise question organization
- Detailed explanations for every answer

### 2. 🧠 Adaptive Practice Engine
- Subject-wise practice sessions for GATE and NEET
- **Spaced repetition** system — revisits weak topics at optimal intervals
- Adaptive difficulty based on your performance
- Server-side question caching for fast loading

### 3. 💡 AI Doubt Solver
- Ask questions about your uploaded PDFs
- AI extracts relevant pages and generates answers using **Groq LLM**
- Keyword overlap ranking for finding the best PDF pages
- Doubt history with saved conversations

### 4. 📚 Course Management
- **GATE** courses (CS, ECE, ME, CE, EE, etc.)
- **NEET** courses (Physics, Chemistry, Biology)
- **GATE+NEET** combo plans
- Course access control with payment verification

### 5. 📄 PDF Management
- Upload and store PDF study materials
- Automatic text extraction using **pdfplumber** and **pdf2image + pytesseract** (OCR)
- PDF page indexing for AI search
- Migration tools for PDF storage

### 6. 📊 Progress Tracking
- Per-course and per-subject progress visualization
- Quiz attempt history and analytics
- Activity timeline
- Performance metrics

### 7. 🔐 Security
- Password hashing with Werkzeug (scrypt/pbkdf2/sha256)
- CSRF protection on all forms
- Google OAuth 2.0 sign-in
- Brute-force lockout (per-account + per-IP)
- Secure session cookies (HttpOnly, SameSite)
- Rate limiting for free trial abuse prevention

## 🏗️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python, Flask, SQLite |
| **AI/LLM** | Groq API (LLaMA/Mixtral), Google Gemini |
| **PDF Processing** | pdfplumber, pdf2image, pytesseract (OCR) |
| **Auth** | Flask-Login, Google OAuth 2.0, Werkzeug security |
| **Frontend** | HTML5, Jinja2 templates, CSS3 |
| **Deployment** | Gunicorn, Nginx (recommended) |

## 📁 Project Structure

```
AI_Adaptive_Learning_Platform/
├── Main_page.py              # Flask app entry point
├── database.py               # SQLite schema & helpers
├── auth.py                   # Password hashing, brute-force lockout
├── google_auth.py            # Google OAuth 2.0 integration
│
├── Signin_page.py            # Login routes
├── Signup_Page.py            # Registration routes
├── profile.py                # User profile management
├── edit_profile.py           # Profile editing
├── settings.py               # App settings
├── Dashboard_Page.py         # Main dashboard
│
├── ai_quiz.py                # AI quiz generation routes
├── quiz.py                   # Standard quiz routes
├── quiz_service.py           # Quiz save/load logic
├── quiz_activity.py          # Quiz attempt tracking
├── question_generator.py     # LLM question generation
│
├── practice.py               # Adaptive practice engine
├── spaced_repetition.py      # Spaced repetition scheduler
│
├── doubt_solver.py           # AI doubt solver
├── llm.py                    # Groq LLM client wrapper
│
├── gate_course.py            # GATE course management
├── neet_course.py            # NEET course management
├── courses.py                # Course listing
├── course_access.py          # Access control & payments
├── my_courses.py             # Enrolled courses
├── add_course.py             # Add new courses
│
├── pdf_upload.py             # PDF upload handling
├── pdf_storage.py            # PDF file storage
├── pdf_text_extraction.py    # Text/OCR extraction
├── pdf_migration.py          # PDF migration tools
├── embeddings.py             # Embedding generation
│
├── notifications.py          # Notification system
├── notification_rout.py      # Notification routes
├── progress.py               # Progress tracking
├── activity.py               # Activity logging
├── plans.py                  # Pricing plans
├── trial.py                  # Free trial management
│
├── templates/                # Jinja2 HTML templates
├── static/                   # CSS stylesheets
├── uploads/                  # User-uploaded PDFs (gitignored)
├── tests/                    # Pytest test suite
├── .env                      # Environment variables (gitignored)
├── requirements.txt          # Python dependencies
└── README.md
```

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- pip
- Tesseract OCR (for PDF text extraction)

### Installation

```bash
# Clone the repository
git clone https://github.com/shreeharichandrakumar24-maker/AI_Adaptive_Learning_Platform.git
cd AI_Adaptive_Learning_Platform

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Environment Setup

Create a `.env` file in the project root:

```env
# Required
GROQ_API_KEY=your_groq_api_key
SECRET_KEY=your_secret_key_here

# Optional (for AI features)
GEMINI_API_KEY=your_gemini_api_key

# Optional (for Google Sign-In)
GOOGLE_CLIENT_ID=your_google_client_id

# Optional (for YouTube integration)
YOUTUBE_API_KEY=your_youtube_api_key
```

### Run the App

```bash
python Main_page.py
```

The app will start on `http://localhost:5000`.

## 📱 How It Works

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Sign Up    │────▶│  Choose Plan  │────▶│  Dashboard   │
│  (Email/G)   │     │ GATE/NEET/Both│     │              │
└──────────────┘     └──────────────┘     └──────┬───────┘
                                                  │
                    ┌─────────────────────────────┼─────────────────────┐
                    │                             │                     │
              ┌─────▼─────┐              ┌───────▼──────┐     ┌───────▼──────┐
              │  Upload   │              │   Practice   │     │  AI Doubt    │
              │   PDFs    │              │    Engine    │     │   Solver     │
              └─────┬─────┘              └───────┬──────┘     └───────┬──────┘
                    │                             │                     │
              ┌─────▼─────┐              ┌───────▼──────┐     ┌───────▼──────┐
              │ AI Quiz   │              │   Spaced     │     │  AI Answers  │
              │ Generate  │              │ Repetition   │     │  from PDFs   │
              └───────────┘              └──────────────┘     └──────────────┘
```

## 🎯 Pricing Plans

Pricing will be decided based on outcome — no fixed plans upfront.

Free trial available with device fingerprint + per-IP caps to prevent abuse.

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_ai_quiz_pipeline.py
```

## 🔧 Configuration

### Required Environment Variables

| Variable | Description |
|----------|-------------|
| `GROQ_API_KEY` | Groq API key for LLM features |
| `SECRET_KEY` | Flask session signing key |

### Optional Environment Variables

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` | Google Gemini API key |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `YOUTUBE_API_KEY` | YouTube Data API key |
| `GOOGLE_AUTH_DEBUG` | Enable Google auth debug mode |
| `SESSION_COOKIE_SECURE` | Force HTTPS-only cookies |
| `TRUSTED_PROXIES` | Number of reverse proxy hops to trust |

## 🌍 SDG Alignment

This project aligns with **UN Sustainable Development Goal 4: Quality Education** by:
- Making exam preparation accessible with AI-powered tools
- Providing adaptive learning paths for GATE and NEET aspirants
- Offering affordable pricing for students
- Using AI to democratize access to quality study materials

## 📄 License

MIT License

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
