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

# How long to wait after YouTube search results load.
YOUTUBE_WAIT = 1000

WEBCMD_SESSION = "short-bot-nf"


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
    """Fast search using yt-dlp flat-playlist dump (~2s without spawning a browser).
    Strictly filters by duration to ensure only genuine Shorts (<= 65s) are returned."""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        cookies_file = os.path.join(base_dir, "cookies.txt")
        cookies_args = ["--cookies", cookies_file] if os.path.isfile(cookies_file) else []

        # Request more items to compensate for filtering out longform videos
        command = [
            sys.executable, "-m", "yt_dlp",
            *cookies_args,
            "--extractor-args", "youtube:player_client=android,ios,web",
            "--flat-playlist",
            "--dump-json",
            "--no-warnings",
            f"ytsearch{max_results * 4}:{search_query} #shorts"
        ]
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=25,
            **get_no_window_kwargs()
        )
        if process.returncode != 0:
            return []

        results = []
        seen = set()
        for line in process.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            vid_id = item.get("id")
            title = item.get("title")
            duration = item.get("duration")

            # STRICT DURATION FILTER: YouTube Shorts are strictly <= 65 seconds
            # Exclude full episodes, compilations, and long videos
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



def search_youtube_webcmd(search_query):
    """Fallback search using webcmd browser automation."""
    js_query = json.dumps(search_query)
    browser_script = f"""
await page.goto('https://www.youtube.com');

const searchBox = page.getByRole('combobox');

await searchBox.fill({js_query});

const searchButton = page.getByRole('button', {{
    name: 'Search',
    description: 'Search'
}});

await searchButton.click();

await page.waitForTimeout({YOUTUBE_WAIT});

const shortsLinks = await page.locator('a[href*="/shorts/"]').all();

const results = [];
const seen = new Set();

for (const link of shortsLinks) {{

    const url = await link.getAttribute('href');
    const title = await link.getAttribute('title');

    if (!url || url === '/shorts/' || !title) {{
        continue;
    }}

    if (seen.has(url)) {{
        continue;
    }}

    seen.add(url);

    results.push({{
        title: title,
        url: 'https://www.youtube.com' + url
    }});
}}

return results;
"""
    browser_file = None
    try:
        temp_file = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".js",
            delete=False,
            encoding="utf-8"
        )
        temp_file.write(browser_script)
        temp_file.close()
        browser_file = temp_file.name

        command = [
            "webcmd.cmd",
            "--session",
            WEBCMD_SESSION,
            "browser",
            "run",
            "--file",
            browser_file
        ]
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            **get_no_window_kwargs()
        )
        if process.returncode != 0:
            print("Webcmd error:", process.stderr)
            return []

        output = process.stdout.strip()
        data = json.loads(output)
        shorts = data.get("result", [])
        return shorts if isinstance(shorts, list) else []
    except Exception as e:
        print("Webcmd error:", e)
        return []
    finally:
        if browser_file and os.path.exists(browser_file):
            try:
                os.remove(browser_file)
            except OSError:
                pass


def search_reddit_videos(search_query, max_results=20):
    """Fetch genuine Reddit video posts (v.redd.it) using Reddit's public Atom search feed."""
    encoded_q = urllib.parse.quote_plus(search_query)
    endpoints = [
        f"https://www.reddit.com/r/all/search.rss?q=url%3Av.redd.it+{encoded_q}&sort=relevance",
        f"https://www.reddit.com/r/videos/search.rss?q={encoded_q}&sort=relevance",
        f"https://www.reddit.com/search.rss?q={encoded_q}+video&sort=relevance"
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/atom+xml,application/xml,text/xml,*/*;q=0.9"
    }

    results = []
    seen = set()

    for url in endpoints:
        if len(results) >= max_results:
            break
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
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
                    "url": link,
                    "platform": "reddit"
                })
                if len(results) >= max_results:
                    break
        except Exception as e:
            safe_print(f"Reddit video search notice: {e}")
            continue

    return results


def search_instagram_reels(search_query, max_results=20):
    """Search for Instagram Reels using webcmd browser automation or public search feeds."""
    js_query = json.dumps(f"site:instagram.com/reel {search_query}")
    browser_script = f"""
await page.goto('https://duckduckgo.com/?q=' + encodeURIComponent({js_query}));
await page.waitForTimeout(2200);
const links = await page.locator('a[href*="instagram.com"]').all();
const results = [];
const seen = new Set();
for (const link of links) {{
    let href = await link.getAttribute('href') || '';
    if (href.includes('duckduckgo.com/l/?uddg=')) {{
        try {{
            const parsed = new URL(href, 'https://duckduckgo.com');
            const target = parsed.searchParams.get('uddg');
            if (target) href = decodeURIComponent(target);
        }} catch(e) {{}}
    }}
    let text = await link.innerText() || '';
    if (href && (href.includes('instagram.com/reel/') || href.includes('instagram.com/reels/') || href.includes('instagram.com/p/'))) {{
        const cleanHref = href.split('?')[0].replace(/\\/$/, '') + '/';
        if (!seen.has(cleanHref)) {{
            seen.add(cleanHref);
            let snippet = '';
            try {{
                const parent = await link.evaluateHandle(el => el.closest('article, [data-testid="result"], li'));
                if (parent) {{
                    const snipEl = await parent.$('[data-result="snippet"], [data-testid="result-snippet"], .result__snippet');
                    if (snipEl) snippet = await snipEl.innerText();
                    const h2El = await parent.$('h2, [data-testid="result-title-a"]');
                    if (h2El && (!text || text === 'Instagram Reel')) {{
                        const h2Text = await h2El.innerText();
                        if (h2Text) text = h2Text;
                    }}
                }}
            }} catch(e) {{}}
            text = (text || '').replace(/\\s+/g, ' ').trim();
            if (!text || text.includes('instagram.com') || text.length < 3) {{
                text = 'Instagram Reel';
            }}
            results.push({{ title: text, snippet: (snippet || '').trim(), url: cleanHref, platform: 'instagram' }});
        }}
    }}
}}
return results;
"""
    browser_file = None
    try:
        temp_file = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".js",
            delete=False,
            encoding="utf-8"
        )
        temp_file.write(browser_script)
        temp_file.close()
        browser_file = temp_file.name

        command = [
            "webcmd.cmd",
            "--session",
            WEBCMD_SESSION,
            "browser",
            "run",
            "--file",
            browser_file
        ]
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            **get_no_window_kwargs()
        )
        if process.returncode == 0:
            data = json.loads(process.stdout.strip())
            reels = data.get("result", [])
            if isinstance(reels, list) and reels:
                return reels[:max_results]
    except Exception as e:
        safe_print(f"Webcmd Instagram search notice: {e}")
    finally:
        if browser_file and os.path.exists(browser_file):
            try:
                os.remove(browser_file)
            except OSError:
                pass

    # Fallback: Query Reddit for Instagram Reels crossposts
    try:
        encoded_q = urllib.parse.quote_plus(search_query)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "application/atom+xml,application/xml,text/xml,*/*;q=0.9"
        }
        endpoints = [
            f"https://www.reddit.com/r/all/search.rss?q=url%3Ainstagram.com%2Freel+{encoded_q}&sort=relevance",
            f"https://www.reddit.com/r/all/search.rss?q=url%3Ainstagram.com+{encoded_q}&sort=relevance"
        ]
        fallback_results = []
        seen = set()
        for ep in endpoints:
            if len(fallback_results) >= max_results:
                break
            try:
                req = urllib.request.Request(ep, headers=headers)
                with urllib.request.urlopen(req, timeout=8) as resp:
                    xml_data = resp.read()
                root = ET.fromstring(xml_data)
                for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
                    content = entry.find("{http://www.w3.org/2005/Atom}content")
                    c_text = content.text if content is not None else ""
                    link_elem = entry.find("{http://www.w3.org/2005/Atom}link")
                    l_href = link_elem.attrib.get("href", "") if link_elem is not None else ""
                    
                    combined = f"{c_text} {l_href}"
                    matches = re.findall(r"https?://(?:www\.)?instagram\.com/(?:reel|reels|p)/([a-zA-Z0-9_-]+)/?", combined)
                    title = entry.find("{http://www.w3.org/2005/Atom}title")
                    t_text = html.unescape(title.text or "Instagram Reel").strip() if title is not None else "Instagram Reel"
                    for code in matches:
                        clean_m = f"https://www.instagram.com/reel/{code}/"
                        if clean_m not in seen:
                            seen.add(clean_m)
                            fallback_results.append({
                                "title": t_text,
                                "url": clean_m,
                                "platform": "instagram"
                            })
                            if len(fallback_results) >= max_results:
                                break
            except Exception:
                continue
        if fallback_results:
            return fallback_results
    except Exception:
        pass

    return []


def search_x_videos(search_query, max_results=20):
    """Search for X / Twitter video posts using webcmd browser automation or public search feeds."""
    js_query = json.dumps(f"site:x.com video {search_query}")
    browser_script = f"""
await page.goto('https://duckduckgo.com/?q=' + encodeURIComponent({js_query}));
await page.waitForTimeout(2200);
const links = await page.locator('a[href*="/status/"], a[href*="x.com"], a[href*="twitter.com"]').all();
const results = [];
const seen = new Set();
for (const link of links) {{
    let href = await link.getAttribute('href') || '';
    if (href.includes('duckduckgo.com/l/?uddg=')) {{
        try {{
            const parsed = new URL(href, 'https://duckduckgo.com');
            const target = parsed.searchParams.get('uddg');
            if (target) href = decodeURIComponent(target);
        }} catch(e) {{}}
    }}
    let text = await link.innerText() || '';
    if (href && (href.includes('x.com/') || href.includes('twitter.com/')) && href.includes('/status/')) {{
        const cleanHref = href.split('?')[0];
        if (!seen.has(cleanHref)) {{
            seen.add(cleanHref);
            let snippet = '';
            try {{
                const parent = await link.evaluateHandle(el => el.closest('article, [data-testid="result"], li'));
                if (parent) {{
                    const snipEl = await parent.$('[data-result="snippet"], [data-testid="result-snippet"], .result__snippet');
                    if (snipEl) snippet = await snipEl.innerText();
                    const h2El = await parent.$('h2, [data-testid="result-title-a"]');
                    if (h2El && (!text || text === 'X Video Post')) {{
                        const h2Text = await h2El.innerText();
                        if (h2Text) text = h2Text;
                    }}
                }}
            }} catch(e) {{}}
            text = (text || '').replace(/\\s+/g, ' ').trim();
            if (!text || text.includes('x.com') || text.includes('twitter.com') || text.length < 3) {{
                text = 'X Video Post';
            }}
            results.push({{ title: text, snippet: (snippet || '').trim(), url: cleanHref, platform: 'x' }});
        }}
    }}
}}
return results;
"""
    browser_file = None
    try:
        temp_file = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".js",
            delete=False,
            encoding="utf-8"
        )
        temp_file.write(browser_script)
        temp_file.close()
        browser_file = temp_file.name

        command = [
            "webcmd.cmd",
            "--session",
            WEBCMD_SESSION,
            "browser",
            "run",
            "--file",
            browser_file
        ]
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            **get_no_window_kwargs()
        )
        if process.returncode == 0:
            data = json.loads(process.stdout.strip())
            posts = data.get("result", [])
            if isinstance(posts, list) and posts:
                return posts[:max_results]
    except Exception as e:
        safe_print(f"Webcmd X search notice: {e}")
    finally:
        if browser_file and os.path.exists(browser_file):
            try:
                os.remove(browser_file)
            except OSError:
                pass

    # Fallback: Query Reddit for X/Twitter video crossposts
    try:
        encoded_q = urllib.parse.quote_plus(search_query)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "application/atom+xml,application/xml,text/xml,*/*;q=0.9"
        }
        endpoints = [
            f"https://www.reddit.com/r/all/search.rss?q=url%3Atwitter.com+{encoded_q}+video&sort=relevance",
            f"https://www.reddit.com/r/all/search.rss?q=url%3Ax.com+{encoded_q}+video&sort=relevance"
        ]
        fallback_results = []
        seen = set()
        for ep in endpoints:
            if len(fallback_results) >= max_results:
                break
            try:
                req = urllib.request.Request(ep, headers=headers)
                with urllib.request.urlopen(req, timeout=8) as resp:
                    xml_data = resp.read()
                root = ET.fromstring(xml_data)
                for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
                    content = entry.find("{http://www.w3.org/2005/Atom}content")
                    c_text = content.text if content is not None else ""
                    matches = re.findall(r"https?://(?:www\.)?(?:twitter|x)\.com/[^/\s]+/status/\d+", c_text)
                    title = entry.find("{http://www.w3.org/2005/Atom}title")
                    t_text = html.unescape(title.text or "X Video").strip() if title is not None else "X Video"
                    for m in matches:
                        clean_m = m.split("?")[0]
                        if clean_m not in seen:
                            seen.add(clean_m)
                            fallback_results.append({
                                "title": t_text,
                                "url": clean_m,
                                "platform": "x"
                            })
                            if len(fallback_results) >= max_results:
                                break
            except Exception:
                continue
        if fallback_results:
            return fallback_results
    except Exception:
        pass

    return []


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

    plan = parse_request(user_request)

    if not plan:
        plan = {
            "search_query": user_request.strip(),
            "topic": user_request.strip(),
            "subjects": [],
            "style": [],
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
        cleaned = re.sub(r'(?i)\bshorts\b', '', base_search_query).strip()
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        base_search_query = cleaned or user_request.strip()

    print(f"Search query ({platform}):", base_search_query)
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
                base_search_query + " video",
                base_search_query + " moments",
            ]
        elif platform == "instagram":
            search_queries = [
                base_search_query,
                base_search_query + " viral",
                base_search_query + " funny",
            ]
        else:  # x / twitter
            search_queries = [
                base_search_query,
                base_search_query + " video",
                base_search_query + " clip",
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
                print("Fast engine returned no results. Falling back to webcmd browser...")
                shorts = search_youtube_webcmd(search_query)

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