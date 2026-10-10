import sys
from ai_engine import parse_search_request

# Ensure UTF-8 output handling on Windows to prevent charmap/emoji encoding crashes
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except (UnicodeEncodeError, OSError):
        safe_args = []
        for a in args:
            if isinstance(a, str):
                safe_args.append(a.encode("ascii", errors="replace").decode("ascii"))
            else:
                safe_args.append(a)
        try:
            print(*safe_args, **kwargs)
        except Exception:
            pass


def parse_request(user_request: str, platform: str = "youtube"):
    """Parse user request into structured search plan using AI engine (Cloud Gemini or local NLP)."""
    return parse_search_request(user_request, platform=platform)


if __name__ == "__main__":
    plan = parse_request("Find funny Young Sheldon Shorts about Sheldon and Missy")
    safe_print("Parsed Plan:", plan)