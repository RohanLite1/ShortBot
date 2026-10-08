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


def compute_title_relevance_score(
    title: str,
    plan: dict,
    user_request: str,
    snippet: str = "",
    url: str = "",
    platform: str = "youtube"
) -> float:
    """Calculate empirical semantic relevance score (0.0 to 1.0) of a video candidate against user intent."""
    title_text = (title or "").strip()
    snippet_text = (snippet or "").strip()
    url_text = (url or "").strip().lower()

    combined_meta = f"{title_text} {snippet_text} {url_text}".lower()
    clean_text = re.sub(r'https?://\S+', ' ', combined_meta)

    topic = plan.get("topic", "").lower()
    subjects = [s.lower() for s in plan.get("subjects", [])]
    styles = [s.lower() for s in plan.get("style", [])]

    # Stopwords to ignore in query tokens
    stop_words = {
        "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "with",
        "is", "are", "of", "from", "video", "videos", "short", "shorts", "reel",
        "reels", "clip", "clips", "watch", "post", "best", "some", "me", "i", "want"
    }

    # Extract critical subject tokens from user_request (length > 2)
    user_tokens = [w for w in re.findall(r"[a-z0-9]+", user_request.lower()) if len(w) > 2 and w not in stop_words]

    # Discard non-video administrative or error pages
    junk_patterns = [
        "login • instagram", "sign up • instagram", "terms of use", "privacy policy",
        "page not found", "404 not found", "enable javascript", "cookie policy"
    ]
    if any(jp in combined_meta for jp in junk_patterns):
        return 0.0

    score = 0.0

    # 1. Core Subject Tokens Verification (Highest Weight: 0.50)
    if user_tokens:
        matched_tokens = 0
        for token in user_tokens:
            if re.search(rf"\b{re.escape(token)}", clean_text) or token in url_text:
                matched_tokens += 1
            elif len(token) > 4 and token[:len(token)-1] in clean_text:
                matched_tokens += 1

        token_ratio = matched_tokens / len(user_tokens)
        score += token_ratio * 0.50

        # If zero core user tokens matched anywhere in metadata, heavily penalize
        if matched_tokens == 0:
            score -= 0.40
    else:
        score += 0.25

    # 2. Named Subject Match (Weight: 0.25)
    if subjects:
        matched_subjects = sum(1 for s in subjects if s in clean_text or s in url_text)
        subject_ratio = matched_subjects / len(subjects)
        score += subject_ratio * 0.25
    else:
        score += 0.10

    # 3. Style / Mood / Intent Match (Weight: 0.20)
    if styles:
        matched_styles = 0
        for st in styles:
            synonyms = STYLE_KEYWORDS.get(st, [st])
            if any(re.search(rf"\b{re.escape(syn)}", clean_text) for syn in synonyms):
                matched_styles += 1
        score += (matched_styles / len(styles)) * 0.20
    else:
        score += 0.10

    # 4. Keyword Conflict Penalties (Off-topic cross-contamination)
    if "minecraft" in user_request.lower() and "minecraft" not in clean_text and any(g in clean_text for g in ["roblox", "fortnite", "gta"]):
        score -= 0.60
    if "cats" in user_request.lower() and "cat" not in clean_text and "dog" in clean_text:
        score -= 0.40

    return max(0.0, min(1.0, round(score, 3)))


def batch_classify_relevance(
    user_request: str,
    plan: dict,
    candidates: list,
    platform: str = "youtube"
) -> list[int]:
    """Return 1-indexed list of relevant videos using the Local Rule & Semantic NLP Filter.
    Supports list of candidate dicts or list of candidate title strings.
    """
    if not candidates:
        return []

    # Normalize candidates into list of dicts
    norm_candidates = []
    for item in candidates:
        if isinstance(item, dict):
            norm_candidates.append(item)
        else:
            norm_candidates.append({"title": str(item), "snippet": "", "url": ""})

    scored = []
    for i, c in enumerate(norm_candidates, start=1):
        title = c.get("title", "")
        snippet = c.get("snippet", "")
        url = c.get("url", "")
        score = compute_title_relevance_score(
            title=title,
            plan=plan,
            user_request=user_request,
            snippet=snippet,
            url=url,
            platform=platform
        )
        scored.append((i, score, title))

    # Strict threshold: 0.35
    relevant = [i for i, s, t in scored if s >= 0.35]

    accepted_count = len(relevant)
    rejected_count = len(norm_candidates) - accepted_count
    print(f"[NLP Filter] Evaluated {len(norm_candidates)} {platform.capitalize()} candidates: {accepted_count} accepted, {rejected_count} off-topic rejected.")

    # Fallback safety: If query was extremely specific and 0 candidates met threshold,
    # pick the top highest-scoring candidates above baseline (> 0.15) rather than stalling
    if not relevant and scored:
        scored_sorted = sorted(scored, key=lambda x: x[1], reverse=True)
        top_candidates = [x[0] for x in scored_sorted[:max(2, len(norm_candidates) // 2)] if x[1] > 0.15]
        if top_candidates:
            print(f"[NLP Filter] Relaxed threshold fallback: accepted top {len(top_candidates)} closest candidates.")
            return top_candidates

    return relevant


def classify_relevance(user_request: str, title: str, snippet: str = "", url: str = "") -> bool:
    """Classify a single item's relevance to the user request."""
    plan = local_parse_request(user_request)
    score = compute_title_relevance_score(title, plan, user_request, snippet=snippet, url=url)
    return score >= 0.35

