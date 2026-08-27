import os
from dotenv import load_dotenv
import google.generativeai as genai

# Load .env file
load_dotenv()

# Read API key
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("❌ API key not found!")
    exit()

# Configure Gemini
genai.configure(api_key=api_key)

# Create model
model = genai.GenerativeModel("gemini-3.5-flash")

# Test prompt
response = model.generate_content("Say Hello in one sentence.")

print("Gemini Response:")
print(response.text.encode('utf-8', errors='replace').decode('ascii', errors='replace'))