import sys
sys.path.append('.')
from actions.web_search import _gemini_search
try:
    print(_gemini_search("whats weather today in pune"))
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")
