import sys
import subprocess
import json
import requests
import tempfile
import os
import time
import re
import urllib.request
import urllib.parse
import html
import xml.etree.ElementTree as ET
import shutil
import yt_dlp

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
def get_no_window_kwargs():
    """Returns subprocess kwargs that prevent console/CMD windows from appearing on Windows."""
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = si
    return kwargs



def safe_print(*args, **kwargs):
    """Print safely even if stdout encoding cannot handle unicode/emojis."""
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


from request_parser import parse_request
from ai_engine import batch_classify_relevance


# ============================================================
# SETTINGS
# ============================================================

# Maximum number of searches if we need more results.
MAX_SEARCHES = 3

# No artificial delay between searches.
WAIT_BETWEEN_SEARCHES = 0


# ============================================================
# SEARCH RETRIEVAL ENGINES
# ============================================================

def search_youtube_shorts_shelf(search_query, max_results=20):
    """Directly fetch YouTube search results and parse the native Shorts Shelf
    (shortsLockupViewModel & reelItemRenderer).
    Extracts 100% genuine YouTube Shorts in ~0.5s with zero longform contamination."""
    try:
        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(search_query)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
        base_dir = os.path.dirname(os.path.abspath(__file__))
        cookies_file = os.path.join(base_dir, "cookies.txt")
        if os.path.isfile(cookies_file):
            try:
                cookie_parts = []
                with open(cookies_file, "r", encoding="utf-8", errors="ignore") as cf:
                    for line in cf:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            tokens = line.split("\t")
                            if len(tokens) >= 7:
                                cookie_parts.append(f"{tokens[5]}={tokens[6]}")
                if cookie_parts:
                    headers["Cookie"] = "; ".join(cookie_parts)
            except Exception:
                pass

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        start = html.find("ytInitialData = ")
        if start == -1:
            start = html.find("var ytInitialData = ")
            if start != -1:
                start += len("var ytInitialData = ")
        else:
            start += len("ytInitialData = ")

        if start == -1:
            return []

        end = html.find(";</script>", start)
        if end == -1:
            end = html.find("</script>", start)
        raw = html[start:end].strip().rstrip(";")
        data = json.loads(raw)

        def find_nodes(d, key):
            if isinstance(d, dict):
                for k, v in d.items():
                    if k == key:
                        yield v
                    else:
                        yield from find_nodes(v, key)
            elif isinstance(d, list):
                for item in d:
                    yield from find_nodes(item, key)

        results = []
        seen = set()

        # Parse shortsLockupViewModel (YouTube's modern Shorts shelf)
        for item in find_nodes(data, "shortsLockupViewModel"):
            entity_id = item.get("entityId", "")
            vid_id = ""
            if entity_id.startswith("shorts-shelf-item-"):
                vid_id = entity_id[len("shorts-shelf-item-"):]
            if not vid_id:
                on_tap = item.get("onTap", {})
                cmd = on_tap.get("innertubeCommand", {})
                vid_id = cmd.get("reelWatchEndpoint", {}).get("videoId", "")
            if not vid_id:
                m = re.search(r"/vi/([a-zA-Z0-9_-]{11})/", json.dumps(item))
                if m:
                    vid_id = m.group(1)

            if not vid_id or vid_id in seen:
                continue

            seen.add(vid_id)
            title = item.get("overlayMetadata", {}).get("primaryText", {}).get("content")
            if not title:
                title = item.get("accessibilityText", "")
                if "," in title:
                    title = title.split(",")[0].strip()
            if not title:
                title = f"Short {vid_id}"

            results.append({
                "title": title,
                "url": f"https://www.youtube.com/shorts/{vid_id}"
            })
            if len(results) >= max_results:
                break

        # Fallback to reelItemRenderer if modern shelf not found
        if len(results) < max_results:
            for item in find_nodes(data, "reelItemRenderer"):
                vid_id = item.get("videoId")
                if not vid_id or vid_id in seen:
                    continue
                seen.add(vid_id)
                title = (
                    item.get("headline", {}).get("simpleText")
                    or item.get("accessibility", {}).get("accessibilityData", {}).get("label")
                    or f"Short {vid_id}"
                )
                results.append({
                    "title": title,
                    "url": f"https://www.youtube.com/shorts/{vid_id}"
                })
                if len(results) >= max_results:
                    break

        return results
    except Exception as e:
        safe_print("Shorts shelf extraction warning:", e)
        return []


def search_youtube_fast(search_query, max_results=20):
    """Fast in-process search using yt-dlp flat-playlist extraction (~0.5s without spawning any subprocess).
    Strictly filters by duration to ensure only genuine Shorts (<= 65s) are returned."""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        cookies_file = os.path.join(base_dir, "cookies.txt")
        ydl_opts = {
            "extract_flat": True,
            "quiet": True,
            "no_warnings": True,
            "extractor_args": {"youtube": {"player_client": ["android", "ios", "web"]}},
        }
        if os.path.isfile(cookies_file):
            ydl_opts["cookiefile"] = cookies_file

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            data = ydl.extract_info(f"ytsearch{max_results * 4}:{search_query} #shorts", download=False)
            entries = data.get("entries") or []

        results = []
        seen = set()
        for item in entries:
            if not item:
                continue
            vid_id = item.get("id")
            title = item.get("title")
            duration = item.get("duration")

            # STRICT DURATION FILTER: YouTube Shorts are strictly <= 65 seconds
            if duration is not None and (duration > 65 or duration < 3):
                continue

            if not vid_id or not title:
                continue
            if vid_id in seen:
                continue
            seen.add(vid_id)
            results.append({
                "title": title,
                "url": f"https://www.youtube.com/shorts/{vid_id}"
            })
            if len(results) >= max_results:
                break
        return results
    except Exception as e:
        safe_print("Fast search error:", e)
        return []


def search_youtube_fallback_http(search_query, max_results=20):
    """Fallback search using in-process yt-dlp query with relaxed duration filters."""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        cookies_file = os.path.join(base_dir, "cookies.txt")
        ydl_opts = {
            "extract_flat": True,
            "quiet": True,
            "no_warnings": True,
            "extractor_args": {"youtube": {"player_client": ["android", "ios", "web"]}},
        }
        if os.path.isfile(cookies_file):
            ydl_opts["cookiefile"] = cookies_file

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            data = ydl.extract_info(f"ytsearch{max_results * 2}:{search_query} shorts", download=False)
            entries = data.get("entries") or []

        results = []
        seen = set()
        for item in entries:
            if not item:
                continue
            vid_id = item.get("id")
            title = item.get("title")
            duration = item.get("duration")

            if duration is not None and (duration > 90 or duration < 3):
                continue
            if not vid_id or not title:
                continue
            if vid_id in seen:
                continue
            seen.add(vid_id)
            results.append({
                "title": title,
                "url": f"https://www.youtube.com/shorts/{vid_id}"
            })
            if len(results) >= max_results:
                break
        return results
    except Exception as e:
        safe_print(f"YouTube HTTP fallback search notice: {e}")
        return []


def search_multiplatform_headless(platform, search_query, max_results=20):
    """Executes fast, 100% headless search via browser_search.js (zero popup window).
    Extracts authentic titles, rich creator snippets, and direct URLs for Instagram, X, and Reddit."""
    try:
        candidates = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser_search.js"),
            os.path.join(os.path.dirname(sys.executable), "browser_search.js"),
            os.path.join(getattr(sys, "_MEIPASS", ""), "browser_search.js") if getattr(sys, "_MEIPASS", None) else "",
        ]
        script_path = next((p for p in candidates if p and os.path.isfile(p)), None)
        if not script_path:
            return []

        node_bin = shutil.which("node") or "node"
        command = [node_bin, script_path, str(platform), str(search_query), str(max_results)]

        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=18,
            **get_no_window_kwargs()
        )
        if process.returncode != 0:
            return []

        out = process.stdout.strip()
        if not out:
            return []

        data = json.loads(out)
        if data.get("ok"):
            results = data.get("results", [])
            if isinstance(results, list) and results:
                return results[:max_results]
        return []
    except Exception as e:
        safe_print(f"Headless {platform} search notice: {e}")
        return []


def search_reddit_videos(search_query, max_results=20):
    """Fetch genuine Reddit video posts (r/... and v.redd.it).
    Primary: 100% silent headless Playwright search.
    Fallback: direct HTTP DuckDuckGo scraper & feeds."""
    # 1. Silent Headless Engine (Primary)
    results = search_multiplatform_headless("reddit", search_query, max_results=max_results)
    if results:
        return results

    # 2. HTTP Fallback via DuckDuckGo scraper (Same robust architecture as Instagram)
    results = []
    seen = set()
    try:
        q_str = f"site:reddit.com/r/ {search_query} video"
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(q_str)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5"
            }
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            page_html = resp.read().decode("utf-8", errors="ignore")

        blocks = re.findall(r'<div[^>]*class="[^"]*result[^"]*"[^>]*>(.*?)</div>\s*</div>', page_html, re.DOTALL)
        for block in blocks:
            url_m = re.search(r'uddg=([^&"\']+)', block)
            if not url_m:
                continue
            target_url = urllib.parse.unquote(url_m.group(1))
            if not (("reddit.com/r/" in target_url and "/comments/" in target_url) or "v.redd.it/" in target_url):
                continue

            clean_url = target_url.split("?")[0].rstrip("/") + "/"
            if clean_url in seen:
                continue
            seen.add(clean_url)

            link_title_m = re.search(r'<h2[^>]*>.*?<a[^>]*>(.*?)</a>', block, re.DOTALL)
            title_text = ""
            if link_title_m:
                title_text = html.unescape(re.sub(r'<[^>]+>', '', link_title_m.group(1))).strip()

            snippet_m = re.search(r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', block, re.DOTALL)
            snippet = html.unescape(re.sub(r'<[^>]+>', '', snippet_m.group(1))).strip() if snippet_m else ""

            if not title_text or "reddit.com" in title_text.lower():
                title_text = snippet[:70] if snippet else "Reddit Video"

            results.append({
                "title": title_text,
                "snippet": snippet,
                "url": clean_url,
                "platform": "reddit"
            })
            if len(results) >= max_results:
                break
    except Exception as e:
        safe_print(f"Reddit HTTP search notice: {e}")

    if results:
        return results

    # 3. RSS Fallback as secondary backup
    encoded_q = urllib.parse.quote_plus(search_query)
    endpoints = [
        f"https://www.reddit.com/r/all/search.rss?q=url%3Av.redd.it+{encoded_q}&sort=relevance",
        f"https://www.reddit.com/r/videos/search.rss?q={encoded_q}&sort=relevance",
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "application/atom+xml,application/xml,text/xml,*/*;q=0.9"
    }

    for url in endpoints:
        if len(results) >= max_results:
            break
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=6) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)
            for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
                t_elem = entry.find("{http://www.w3.org/2005/Atom}title")
                l_elem = entry.find("{http://www.w3.org/2005/Atom}link")
                if t_elem is None or l_elem is None:
                    continue
                title = html.unescape(t_elem.text or "").strip()
                link = l_elem.attrib.get("href", "").strip()
                if not link or link in seen:
                    continue
                seen.add(link)
                results.append({
                    "title": title or "Reddit Video",
                    "snippet": title,
                    "url": link,
                    "platform": "reddit"
                })
                if len(results) >= max_results:
                    break
        except Exception:
            continue

    return results


def search_instagram_reels(search_query, max_results=20):
    """Search for Instagram Reels.
    Primary: 100% silent headless Playwright search with rich snippet descriptions.
    Fallback: direct HTTP DuckDuckGo scraper."""
    # 1. Silent Headless Engine (Primary)
    results = search_multiplatform_headless("instagram", search_query, max_results=max_results)
    if results:
        return results

    # 2. HTTP Fallback
    results = []
    seen = set()
    try:
        q_str = f"site:instagram.com/reel {search_query}"
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(q_str)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5"
            }
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            page_html = resp.read().decode("utf-8", errors="ignore")

        blocks = re.findall(r'<div[^>]*class="[^"]*result[^"]*"[^>]*>(.*?)</div>\s*</div>', page_html, re.DOTALL)
        for block in blocks:
            url_m = re.search(r'uddg=([^&"\']+)', block)
            if not url_m:
                continue
            target_url = urllib.parse.unquote(url_m.group(1))
            if not ("instagram.com/reel" in target_url or "instagram.com/reels" in target_url or "instagram.com/p/" in target_url):
                continue

            clean_url = target_url.split("?")[0].rstrip("/") + "/"
            if clean_url in seen:
                continue
            seen.add(clean_url)

            link_title_m = re.search(r'<h2[^>]*>.*?<a[^>]*>(.*?)</a>', block, re.DOTALL)
            title_text = ""
            if link_title_m:
                title_text = html.unescape(re.sub(r'<[^>]+>', '', link_title_m.group(1))).strip()

            snippet_m = re.search(r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', block, re.DOTALL)
            snippet = html.unescape(re.sub(r'<[^>]+>', '', snippet_m.group(1))).strip() if snippet_m else ""

            if not title_text or "instagram.com" in title_text.lower():
                title_text = snippet[:60] if snippet else "Instagram Reel"

            results.append({
                "title": title_text,
                "snippet": snippet,
                "url": clean_url,
                "platform": "instagram"
            })
            if len(results) >= max_results:
                break
    except Exception as e:
        safe_print(f"Instagram HTTP search notice: {e}")

    return results


def search_x_videos(search_query, max_results=20):
    """Search for X / Twitter video posts.
    Primary: 100% silent headless Playwright search with rich post snippets.
    Fallback: direct HTTP DuckDuckGo scraper."""
    # 1. Silent Headless Engine (Primary)
    results = search_multiplatform_headless("x", search_query, max_results=max_results)
    if results:
        return results

    # 2. HTTP Fallback
    results = []
    seen = set()
    try:
        q_str = f"site:x.com {search_query} video"
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(q_str)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5"
            }
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            page_html = resp.read().decode("utf-8", errors="ignore")

        blocks = re.findall(r'<div[^>]*class="[^"]*result[^"]*"[^>]*>(.*?)</div>\s*</div>', page_html, re.DOTALL)
        for block in blocks:
            url_m = re.search(r'uddg=([^&"\']+)', block)
            if not url_m:
                continue
            target_url = urllib.parse.unquote(url_m.group(1))
            if not (("x.com/" in target_url or "twitter.com/" in target_url) and "/status/" in target_url):
                continue

            clean_url = target_url.split("?")[0]
            if clean_url in seen:
                continue
            seen.add(clean_url)

            link_title_m = re.search(r'<h2[^>]*>.*?<a[^>]*>(.*?)</a>', block, re.DOTALL)
            title_text = ""
            if link_title_m:
                title_text = html.unescape(re.sub(r'<[^>]+>', '', link_title_m.group(1))).strip()

            snippet_m = re.search(r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', block, re.DOTALL)
            snippet = html.unescape(re.sub(r'<[^>]+>', '', snippet_m.group(1))).strip() if snippet_m else ""

            if not title_text or "x.com" in title_text.lower() or "twitter.com" in title_text.lower():
                title_text = snippet[:60] if snippet else "X Video Post"

            results.append({
                "title": title_text,
                "snippet": snippet,
                "url": clean_url,
                "platform": "x"
            })
            if len(results) >= max_results:
                break
    except Exception as e:
        safe_print(f"X HTTP search notice: {e}")

    return results



def parse_direct_media_urls(user_input):
    """Detect if the user pasted direct media URLs from YouTube, Instagram, X, Reddit, or TikTok."""
    urls = re.findall(r"https?://[^\s,]+", user_input)
    if not urls:
        return []
    results = []
    seen = set()
    for raw_u in urls:
        clean_u = raw_u.strip().rstrip(".,;!?'\"")
        if clean_u in seen:
            continue
        seen.add(clean_u)

        p = "other"
        title = "Pasted Video"
        if "youtube.com" in clean_u or "youtu.be" in clean_u:
            p = "youtube"
            m = re.search(r"(?:shorts/|v=|youtu\.be/)([a-zA-Z0-9_-]{11})", clean_u)
            title = f"YouTube Short ({m.group(1)})" if m else "YouTube Video"
        elif "instagram.com" in clean_u:
            p = "instagram"
            m = re.search(r"instagram\.com/(?:reel|reels|p)/([a-zA-Z0-9_-]+)", clean_u)
            title = f"Instagram Reel ({m.group(1)})" if m else "Instagram Video"
        elif "twitter.com" in clean_u or "x.com" in clean_u:
            p = "x"
            m = re.search(r"(?:twitter|x)\.com/[^/]+/status/(\d+)", clean_u)
            title = f"X Video ({m.group(1)})" if m else "X Video Post"
        elif "reddit.com" in clean_u or "v.redd.it" in clean_u:
            p = "reddit"
            m = re.search(r"reddit\.com/r/([^/]+)/comments/([a-zA-Z0-9]+)", clean_u)
            title = f"Reddit Clip (r/{m.group(1)})" if m else "Reddit Video"
        elif "tiktok.com" in clean_u:
            p = "tiktok"
            title = "TikTok Video"

        results.append({
            "title": title,
            "url": clean_u,
            "platform": p
        })
    return results


def is_valid_url_for_platform(url, target_platform):
    """Enforce strict domain isolation per requested platform."""
    if not url or not isinstance(url, str):
        return False
    u = url.lower()
    p = str(target_platform).strip().lower()
    if p == "instagram":
        return ("instagram.com/reel/" in u or "instagram.com/reels/" in u or "instagram.com/p/" in u)
    elif p in ("x", "twitter"):
        return ("x.com/" in u or "twitter.com/" in u) and "/status/" in u
    elif p == "reddit":
        return ("reddit.com/r/" in u and "/comments/" in u) or "v.redd.it/" in u
    elif p == "youtube":
        return ("youtube.com/shorts/" in u or "youtu.be/" in u)
    elif p == "tiktok":
        return "tiktok.com/" in u
    return False


# ============================================================
# FIND SHORTS & VIDEOS (MULTIPLATFORM)
# ============================================================

def find_shorts(user_request, quantity, platform="youtube", exclude_urls=None, refresh=False):

    # --------------------------------------------------------
    # VALIDATE INPUT
    # --------------------------------------------------------

    if not isinstance(user_request, str) or not user_request.strip():
        raise ValueError("user_request must be a non-empty string.")

    if not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("quantity must be an integer greater than 0.")

    user_request = user_request.strip()
    platform = str(platform).strip().lower() or "youtube"

    seen_urls = set()
    if exclude_urls:
        for u in exclude_urls:
            if isinstance(u, str) and u.strip():
                seen_urls.add(u.strip())
        if seen_urls:
            safe_print(f"Refresh mode: excluding {len(seen_urls)} previously seen {platform} videos.")

    # Check for direct pasted URLs first - strictly only accept URLs matching the requested platform
    direct_items = parse_direct_media_urls(user_request)
    if direct_items:
        matching_platform_items = [
            item for item in direct_items
            if is_valid_url_for_platform(item.get("url"), platform) and item.get("url") not in seen_urls
        ]
        if matching_platform_items:
            safe_print(f"Direct {platform} URLs detected in prompt: {len(matching_platform_items)} videos.")
            return matching_platform_items[:quantity]
        else:
            other_plats = list({item.get("platform") for item in direct_items if item.get("platform") != "other"})
            plat_str = ", ".join(other_plats).title() if other_plats else "other platforms"
            safe_print(f"Pasted URLs belong to {plat_str}, but requested platform is {platform}. Preserving strict platform isolation.")
            return []


    # ========================================================
    # UNDERSTAND USER REQUEST
    # ========================================================

    print()
    print("Understanding your request...")
    print()

    plan = parse_request(user_request, platform=platform)

    if not plan:
        plan = {
            "search_query": user_request.strip(),
            "topic": user_request.strip(),
            "subjects": [],
            "style": [],
            "platform": platform,
            "fallback": True
        }

    is_fallback = plan.get("fallback", False)
    if is_fallback:
        print("Running in Direct Search Mode (Ollama offline/bypassed)...")

    base_search_query = plan.get(
        "search_query",
        user_request.strip()
    ).strip()

    if not base_search_query:
        base_search_query = user_request.strip()

    if platform != "youtube":
        cleaned = re.sub(r'(?i)\bshorts?\b', '', base_search_query).strip()
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        base_search_query = cleaned or user_request.strip()

    print(f"Search query ({platform}):", base_search_query)
    if plan.get("topic"):
        print(f"Identified Topic: {plan.get('topic')}")
    if plan.get("subjects"):
        print(f"Target Subjects: {', '.join(plan.get('subjects'))}")
    if plan.get("style"):
        print(f"Target Style: {', '.join(plan.get('style'))}")
    print()


    # ========================================================
    # SEARCH QUERY VARIATIONS
    # ========================================================

    if refresh or seen_urls:
        if platform == "youtube":
            search_queries = [
                base_search_query + " compilation",
                base_search_query + " highlights",
                base_search_query + " part 2",
                base_search_query + " clips",
                base_search_query + " funny moments",
                base_search_query + " best",
                base_search_query,
            ]
        elif platform == "reddit":
            search_queries = [
                base_search_query + " highlights",
                base_search_query + " clip",
                base_search_query + " moments",
                base_search_query + " video",
                base_search_query,
            ]
        elif platform == "instagram":
            search_queries = [
                base_search_query + " viral",
                base_search_query + " reel",
                base_search_query + " trending",
                base_search_query + " funny",
                base_search_query + " clips",
                base_search_query,
            ]
        else:  # x / twitter
            search_queries = [
                base_search_query + " clip",
                base_search_query + " moments",
                base_search_query + " video",
                base_search_query + " highlights",
                base_search_query,
            ]
    else:
        if platform == "youtube":
            search_queries = [
                base_search_query,
                base_search_query + " funny moments",
                base_search_query + " clips",
            ]
        elif platform == "reddit":
            search_queries = [
                base_search_query,
                base_search_query + " clips",
                base_search_query + " highlights",
                base_search_query + " moments",
            ]
        elif platform == "instagram":
            search_queries = [
                base_search_query,
                base_search_query + " viral",
                base_search_query + " funny",
                base_search_query + " reel",
            ]
        else:  # x / twitter
            search_queries = [
                base_search_query,
                base_search_query + " clips",
                base_search_query + " viral",
                base_search_query + " moments",
            ]


    # ========================================================
    # STORAGE
    # ========================================================

    # Shorts that Gemma classified as relevant.
    relevant_shorts = []


    # ========================================================
    # SEARCH LOOP
    # ========================================================

    max_search_rounds = max(MAX_SEARCHES + (3 if (refresh or seen_urls) else 0), len(search_queries))
    for search_number in range(1, max_search_rounds + 1):

        # ----------------------------------------------------
        # STOP AS SOON AS WE HAVE ENOUGH
        # ----------------------------------------------------

        if len(relevant_shorts) >= quantity:
            break


        # ----------------------------------------------------
        # SELECT SEARCH QUERY
        # ----------------------------------------------------

        query_index = search_number - 1

        if query_index < len(search_queries):

            search_query = search_queries[query_index]

        else:

            search_query = (
                base_search_query
                + f" {search_number}"
            )


        print()
        print("=" * 60)
        print(
            f"SEARCH {search_number}/{MAX_SEARCHES}"
        )
        print("=" * 60)
        print()

        print("Query:", search_query)
        print()


        # ====================================================
        # EXECUTE SEARCH (MULTIPLATFORM ROUTING)
        # ====================================================

        target_count = max(quantity * 2, 20)
        shorts = []

        if platform == "reddit":
            print("Searching Reddit for video posts...")
            shorts = search_reddit_videos(search_query, max_results=target_count)
        elif platform == "instagram":
            print("Searching Instagram for Reels...")
            shorts = search_instagram_reels(search_query, max_results=target_count)
        elif platform in ("x", "twitter"):
            print("Searching X / Twitter for video posts...")
            shorts = search_x_videos(search_query, max_results=target_count)
        else:
            print("Searching YouTube (native Shorts shelf)...")
            shorts = search_youtube_shorts_shelf(search_query, max_results=target_count)

            if not shorts:
                print("Shorts shelf returned no results. Falling back to yt-dlp fast search...")
                shorts = search_youtube_fast(search_query, max_results=target_count)

            if not shorts:
                print("Fast engine returned no results. Falling back to in-process search...")
                shorts = search_youtube_fallback_http(search_query, max_results=target_count)

        for s in shorts:
            if isinstance(s, dict) and "platform" not in s:
                s["platform"] = platform

        print(
            "Found",
            len(shorts),
            f"{platform.capitalize()} videos."
        )

        print()


        # ====================================================
        # REMOVE DUPLICATES
        # ====================================================

        new_shorts = []

        for short in shorts:

            if not isinstance(short, dict):
                continue

            url = short.get("url")

            if not url or url in seen_urls:
                continue

            # STRICT PLATFORM DOMAIN ISOLATION
            if not is_valid_url_for_platform(url, platform):
                continue

            seen_urls.add(url)
            short["platform"] = platform
            new_shorts.append(short)


        print(
            "New videos:",
            len(new_shorts)
        )

        print()


        # If search returned nothing new,
        # continue to next query.
        if not new_shorts:

            print(
                "No new videos from this search."
            )

            continue


        # ====================================================
        # SHOW NEW VIDEOS
        # ====================================================

        for i, short in enumerate(
            new_shorts,
            start=1
        ):

            safe_print(
                f"{i}. [{short.get('platform', platform).upper()}] {short.get('title', 'Untitled')}"
            )

        print()


        # ====================================================
        # RELEVANCE CLASSIFICATION (LOCAL RULE & SEMANTIC NLP FILTER)
        # ====================================================
        print(f"Applying Local Rule & Semantic NLP Filter to {len(new_shorts)} {platform.capitalize()} candidates...")
        relevant_numbers = batch_classify_relevance(user_request, plan, new_shorts, platform=platform)
        print(f"NLP Filter accepted {len(relevant_numbers)} relevant {platform.capitalize()} videos from {len(new_shorts)} candidates.")


        # ====================================================
        # ADD RELEVANT SHORTS
        # ====================================================

        added_this_search = 0

        existing_urls = {
            item.get("url")
            for item in relevant_shorts
        }


        for number in relevant_numbers:

            if not isinstance(number, int):
                continue

            if number < 1 or number > len(new_shorts):
                continue


            short = new_shorts[number - 1]

            url = short.get("url")

            if not url:
                continue


            if url in existing_urls:
                continue

            if not is_valid_url_for_platform(url, platform):
                continue

            short["platform"] = platform
            relevant_shorts.append(
                short
            )

            existing_urls.add(url)

            added_this_search += 1


            # Stop adding once we have enough.
            if len(relevant_shorts) >= quantity:
                break


        print(
            "Relevant added:",
            added_this_search
        )

        print(
            "Total relevant:",
            len(relevant_shorts),
            "/",
            quantity
        )

        print()


        # ====================================================
        # CHECK WHETHER WE ARE DONE
        # ====================================================

        if len(relevant_shorts) >= quantity:

            print(
                "Required number of Shorts reached!"
            )

            break


        # ====================================================
        # PREPARE FOR NEXT SEARCH
        # ====================================================

        remaining = quantity - len(
            relevant_shorts
        )

        print(
            "Still need",
            remaining,
            "more relevant Shorts."
        )


        if search_number < MAX_SEARCHES:

            print(
                "Searching again..."
            )

            if WAIT_BETWEEN_SEARCHES > 0:

                time.sleep(
                    WAIT_BETWEEN_SEARCHES
                )


    # ========================================================
    # FINAL RESULTS
    # ========================================================

    final_results = [
        s for s in relevant_shorts
        if is_valid_url_for_platform(s.get("url"), platform)
    ][:quantity]
    for s in final_results:
        s["platform"] = platform


    print()
    print("=" * 60)
    print("FINAL RESULTS")
    print("=" * 60)
    print()


    if not final_results:

        print(
            "No relevant Shorts were found."
        )

    else:

        for i, short in enumerate(
            final_results,
            start=1
        ):

            safe_print(
                f"{i}. {short.get('title', 'Untitled')}"
            )

            safe_print(
                f"   {short.get('url', '')}"
            )

            print()


    print(
        "Total relevant:",
        len(final_results)
    )

    print(
        "Requested:",
        quantity
    )


    # ========================================================
    # INCOMPLETE SEARCH WARNING
    # ========================================================

    if len(final_results) < quantity:

        print()
        print(
            "Could not find enough relevant Shorts "
            "within the search limit."
        )


    # ========================================================
    # RETURN RESULTS TO CALLER
    # ========================================================

    return final_results


# ============================================================
# COMMAND-LINE TEST
# ============================================================

if __name__ == "__main__":

    user_request = input(
        "What Shorts are you looking for?\n> "
    )


    while True:

        try:

            quantity = int(
                input(
                    "How many Shorts do you want?\n> "
                )
            )

            if quantity > 0:
                break

            print(
                "Please enter a number greater than 0."
            )

        except ValueError:

            print(
                "Please enter a valid number."
            )


    results = find_shorts(
        user_request,
        quantity
    )