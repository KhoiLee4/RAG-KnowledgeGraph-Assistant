from google import genai
import os
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def test_gemini():
    response = client.models.generate_content(
        model="gemini-2.0-flash-lite",
        contents="Xin chào! Bạn là ai?"
    )
    print("Gemini response:", response.text)

if __name__ == "__main__":
    test_gemini()