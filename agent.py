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
            timeout=25
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
            errors="replace"
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


# ============================================================
# FIND SHORTS
# ============================================================

def find_shorts(user_request, quantity):

    # --------------------------------------------------------
    # VALIDATE INPUT
    # --------------------------------------------------------

    if not isinstance(user_request, str) or not user_request.strip():
        raise ValueError("user_request must be a non-empty string.")

    if not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("quantity must be an integer greater than 0.")

    user_request = user_request.strip()


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

    print("Search query:", base_search_query)
    print()


    # ========================================================
    # SEARCH QUERY VARIATIONS
    # ========================================================

    # We start with the plain search.
    # Extra searches are only used if we still need results.

    search_queries = [
        base_search_query,
        base_search_query + " funny moments",
        base_search_query + " clips",
    ]


    # ========================================================
    # STORAGE
    # ========================================================

    # All Shorts we've ever seen.
    seen_urls = set()

    # Shorts that Gemma classified as relevant.
    relevant_shorts = []


    # ========================================================
    # SEARCH LOOP
    # ========================================================

    for search_number in range(1, MAX_SEARCHES + 1):

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
        # EXECUTE SEARCH (SHORTS SHELF -> YT-DLP -> WEBCMD)
        # ====================================================

        target_count = max(quantity * 2, 20)
        print("Searching YouTube (native Shorts shelf)...")
        shorts = search_youtube_shorts_shelf(search_query, max_results=target_count)

        if not shorts:
            print("Shorts shelf returned no results. Falling back to yt-dlp fast search...")
            shorts = search_youtube_fast(search_query, max_results=target_count)

        if not shorts:
            print("Fast engine returned no results. Falling back to webcmd browser...")
            shorts = search_youtube_webcmd(search_query)


        print(
            "Found",
            len(shorts),
            "Shorts."
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

            if not url:
                continue

            if url in seen_urls:
                continue

            seen_urls.add(url)

            new_shorts.append(short)


        print(
            "New Shorts:",
            len(new_shorts)
        )

        print()


        # If YouTube returned nothing new,
        # continue to next query.
        if not new_shorts:

            print(
                "No new Shorts from this search."
            )

            continue


        # ====================================================
        # SHOW NEW SHORTS
        # ====================================================

        for i, short in enumerate(
            new_shorts,
            start=1
        ):

            safe_print(
                f"{i}. {short.get('title', 'Untitled')}"
            )

        print()


        # ====================================================
        # BATCH GEMMA CLASSIFIER / DIRECT FALLBACK
        # ====================================================

        if is_fallback:
            print("Direct Search Mode: accepting results directly without Ollama filtering...")
            existing_urls = {item.get("url") for item in relevant_shorts}
            for short in new_shorts:
                url = short.get("url")
                if url and url not in existing_urls:
                    relevant_shorts.append(short)
                    existing_urls.add(url)
                if len(relevant_shorts) >= quantity:
                    break
            if len(relevant_shorts) >= quantity:
                break
            continue

        print(
            "Sending new Shorts to Gemma..."
        )

        print()


        numbered_titles = []

        for i, short in enumerate(
            new_shorts,
            start=1
        ):

            title = short.get(
                "title",
                ""
            )

            numbered_titles.append(
                f"{i}. {title}"
            )


        titles_text = "\n".join(
            numbered_titles
        )


        # ====================================================
        # RELEVANCE CLASSIFICATION (AI ENGINE - CLOUD / LOCAL NLP)
        # ====================================================
        candidate_titles = [s.get("title", "") for s in new_shorts]
        relevant_numbers = batch_classify_relevance(user_request, plan, candidate_titles)
        print(f"AI Engine accepted {len(relevant_numbers)} relevant Shorts from {len(new_shorts)} candidates.")


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

    final_results = relevant_shorts[:quantity]


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