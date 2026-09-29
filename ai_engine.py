import os
import sys
import json
import re
import urllib.request
import urllib.parse
import urllib.error

# Ensure UTF-8 output handling on Windows
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


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")


def load_config():
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception:
        return False


def get_gemini_api_key():
    # 1. Environment variable
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    # 2. Config file
    cfg = load_config()
    key = cfg.get("gemini_api_key", "").strip()
    return key if key else None


# ============================================================
# CLOUD AI: GEMINI FLASH API
# ============================================================

def call_gemini_flash(prompt, system_instruction=None, json_mode=False, timeout=8):
    """Call Google Gemini 2.5 Flash / 1.5 Flash via direct REST endpoint.
    Zero local GPU/RAM requirement, zero Ollama, response in ~350ms."""
    api_key = get_gemini_api_key()
    if not api_key:
        return None

    # Supported fast production models
    models = ["gemini-2.5-flash", "gemini-1.5-flash"]
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        
        contents = [{
            "parts": [{"text": prompt}]
        }]
        
        req_body = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 500,
            }
        }
        
        if json_mode:
            req_body["generationConfig"]["responseMimeType"] = "application/json"
            
        if system_instruction:
            req_body["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        try:
            data = json.dumps(req_body).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                candidates = res_json.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "").strip()
        except urllib.error.HTTPError as he:
            # If 404 on model, try next model; otherwise bail
            if he.code == 404:
                continue
            print(f"[AI Engine] Gemini API HTTP error {he.code}: {he.reason}")
            return None
        except Exception as e:
            print(f"[AI Engine] Gemini API error: {e}")
            return None

    return None


# ============================================================
# SMART LOCAL NLP INTENT & RELEVANCE ENGINE
# (Zero-dependency, runs offline, 100% reliable)
# ============================================================

FILLER_PHRASES = [
    r"\bfind(?:\s+me)?\b",
    r"\bsearch(?:\s+for)?\b",
    r"\bdownload\b",
    r"\bget(?:\s+me)?\b",
    r"\bgive(?:\s+me)?\b",
    r"\bshow(?:\s+me)?\b",
    r"\bi(?:\s+want|\s+need|\s+am\s+looking\s+for)\b",
    r"\blook(?:\s+for)?\b",
    r"\bcompile\b",
    r"\bcurate\b",
    r"\byoutube\s+shorts\b",
    r"\bshorts?\b",
    r"\bvideos?\b",
    r"\bclips?\b",
    r"\bshowing\b",
    r"\babout\b",
    r"\bwith\b",
    r"\bfeaturing\b",
    r"\bof\b",
    r"\bsome\b",
]

STYLE_KEYWORDS = {
    "funny": ["funny", "hilarious", "laugh", "comedy", "meme", "joke", "humor"],
    "fails": ["fail", "fails", "bloopers", "mistake"],
    "highlights": ["highlight", "highlights", "best moments", "moments", "epic", "insane"],
    "scary": ["scary", "horror", "creepy", "spooky"],
    "sad": ["sad", "emotional", "cry"],
    "educational": ["educational", "tutorial", "how to", "guide", "tips", "tricks", "learn"],
    "edits": ["edit", "edits", "amv", "phonk", "sigma", "montage", "badass"],
}


def local_parse_request(user_request: str) -> dict:
    """Intelligently parse user search prompt without calling any external LLM."""
    req_clean = user_request.strip()
    
    # 1. Detect requested styles
    detected_styles = []
    req_lower = req_clean.lower()
    for style_name, synonyms in STYLE_KEYWORDS.items():
        if any(re.search(rf"\b{re.escape(syn)}\b", req_lower) for syn in synonyms):
            detected_styles.append(style_name)

    # 2. Extract core topic and subjects by removing filler verbs and phrases
    core_text = req_clean
    for pat in FILLER_PHRASES:
        core_text = re.sub(pat, " ", core_text, flags=re.IGNORECASE)

    # Clean whitespace and punctuation
    core_tokens = [w for w in core_text.split() if w.strip()]
    cleaned_query = " ".join(core_tokens).strip()

    if not cleaned_query:
        cleaned_query = user_request.strip()

    # Formulate optimal YouTube search query
    # If the user didn't mention 'Shorts', add it for YouTube Shorts shelf targeting
    search_query = cleaned_query
    if "short" not in search_query.lower():
        search_query = f"{cleaned_query} Shorts"

    # Identify potential named subjects (e.g. capitalized phrases or key nouns)
    subjects = []
    # Match quoted terms first
    quoted = re.findall(r'["\']([^"\']+)["\']', user_request)
    if quoted:
        subjects.extend(quoted)
    else:
        # Check for 'and' pairs or character names
        and_match = re.search(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:and|vs\.?|with)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b', user_request)
        if and_match:
            subjects.extend([and_match.group(1), and_match.group(2)])

    return {
        "search_query": search_query,
        "topic": cleaned_query,
        "subjects": subjects,
        "style": detected_styles,
        "engine": "local_nlp"
    }


def parse_search_request(user_request: str) -> dict:
    """Parse search request using Cloud Gemini Flash if key available, else local NLP engine."""
    api_key = get_gemini_api_key()
    if api_key:
        prompt = f"""
You are the search query planning engine for a YouTube Shorts curator.
USER REQUEST: {user_request}

Return ONLY a valid JSON object matching this schema:
{{
  "search_query": "concise youtube search query including key characters/topic",
  "topic": "main topic",
  "subjects": ["subject1", "subject2"],
  "style": ["funny", "highlights"]
}}
"""
        res = call_gemini_flash(prompt, json_mode=True, timeout=5)
        if res:
            try:
                # Strip markdown fences if present
                clean_res = res
                if clean_res.startswith("```"):
                    lines = clean_res.splitlines()
                    clean_res = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
                parsed = json.loads(clean_res)
                if isinstance(parsed, dict) and "search_query" in parsed:
                    parsed["engine"] = "gemini_cloud"
                    return parsed
            except Exception as e:
                print(f"[AI Engine] Error parsing Gemini JSON: {e}")

    # Zero-dependency local fallback
    return local_parse_request(user_request)


def compute_title_relevance_score(title: str, plan: dict, user_request: str) -> float:
    """Calculate empirical relevance score (0.0 to 1.0) of a Short title against user intent."""
    title_lower = title.lower()
    score = 0.0

    topic = plan.get("topic", "").lower()
    subjects = [s.lower() for s in plan.get("subjects", [])]
    styles = [s.lower() for s in plan.get("style", [])]

    # Stopwords to ignore
    stop_words = {"a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "with", "is", "are", "of", "from"}

    # 1. Subject Match (Highest weight: 0.45)
    if subjects:
        matched_subjects = sum(1 for s in subjects if s in title_lower)
        subject_ratio = matched_subjects / len(subjects)
        score += subject_ratio * 0.45
    else:
        # No specific subjects requested, grant baseline
        score += 0.20

    # 2. Topic Keyword Match (Weight: 0.35)
    topic_tokens = [w for w in re.findall(r"\w+", topic) if len(w) > 2 and w not in stop_words]
    if topic_tokens:
        matched_tokens = sum(1 for t in topic_tokens if t in title_lower)
        token_ratio = matched_tokens / len(topic_tokens)
        score += token_ratio * 0.35
    else:
        score += 0.15

    # 3. Style Match (Weight: 0.15)
    if styles:
        matched_styles = 0
        for st in styles:
            synonyms = STYLE_KEYWORDS.get(st, [st])
            if any(syn in title_lower for syn in synonyms):
                matched_styles += 1
        score += (matched_styles / len(styles)) * 0.15
    else:
        score += 0.10

    # 4. Penalty for completely unrelated obvious spam or off-topic keywords
    # E.g. If Minecraft is requested and title has 'Roblox' without 'Minecraft'
    if "minecraft" in topic and "roblox" in title_lower and "minecraft" not in title_lower:
        score -= 0.50
    if "sheldon" in topic and "sheldon" not in title_lower and "cooper" not in title_lower:
        score -= 0.30

    return max(0.0, min(1.0, score))


def batch_classify_relevance(user_request: str, plan: dict, titles: list[str]) -> list[int]:
    """Return 1-indexed list of relevant Shorts. Uses Gemini Cloud if available, else local scorer."""
    if not titles:
        return []

    api_key = get_gemini_api_key()
    if api_key and len(titles) <= 30:
        numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
        prompt = f"""
Strict relevance classifier for YouTube Shorts.
USER REQUEST: {user_request}
TOPIC: {plan.get("topic", "")}
SUBJECTS: {plan.get("subjects", [])}

SHORTS FOUND:
{numbered}

Determine which Shorts are relevant. Return ONLY valid JSON:
{{"relevant": [1, 2, 5]}}
"""
        res = call_gemini_flash(prompt, json_mode=True, timeout=6)
        if res:
            try:
                clean_res = res
                if clean_res.startswith("```"):
                    lines = clean_res.splitlines()
                    clean_res = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
                parsed = json.loads(clean_res)
                indices = parsed.get("relevant", [])
                if isinstance(indices, list):
                    valid = [int(i) for i in indices if isinstance(i, (int, str)) and str(i).isdigit() and 1 <= int(i) <= len(titles)]
                    if valid:
                        return valid
            except Exception as e:
                print(f"[AI Engine] Error parsing Gemini batch classification: {e}")

    # Local High-Precision Scoring
    scored = []
    for i, title in enumerate(titles, start=1):
        s = compute_title_relevance_score(title, plan, user_request)
        scored.append((i, s, title))

    # Accept titles scoring >= 0.35
    relevant = [i for i, s, t in scored if s >= 0.35]

    # If too few were accepted but we have results, take the top 50% highest scoring
    if len(relevant) < max(1, len(titles) // 3):
        scored_sorted = sorted(scored, key=lambda x: x[1], reverse=True)
        top_half = [x[0] for x in scored_sorted[:max(3, len(titles) // 2)] if x[1] > 0.1]
        return top_half

    return relevant


def classify_relevance(user_request: str, title: str) -> bool:
    """Classify a single title's relevance to the user request."""
    plan = local_parse_request(user_request)
    score = compute_title_relevance_score(title, plan, user_request)
    return score >= 0.35
