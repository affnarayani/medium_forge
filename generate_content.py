import os
import sys
import json
import time
import random
import requests
from pathlib import Path
from typing import List, Dict, Any

from dotenv import load_dotenv

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from common.config_loader import get
from common.crypto import load_cookies, get_env_decrypt_key
from common.locator_loader import resolve_locator, apply_auto_correct
from common.screenshot import capture_error_screenshot, upload_to_onlyfiles

load_dotenv()

DECRYPT_KEY = os.getenv("DECRYPT_KEY")
if not DECRYPT_KEY:
    raise RuntimeError("DECRYPT_KEY missing")

# =========================
# CONFIG (from json/config.json)
# =========================
HEADLESS = get("headless", True)
USER_AGENT = get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
CHATGPT_URL = get("chatgpt_url", "https://chatgpt.com/")
PBKDF2_ITERATIONS = get("pbkdf2_iterations", 200000)

COOKIES_DIR = Path("chatgpt_cookies")
IMAGE_DIR = Path("image")
IMAGE_DIR.mkdir(exist_ok=True)

MIN_ABSOLUTE_WAIT = get("min_absolute_wait", 15)
MAX_ABSOLUTE_WAIT = get("max_absolute_wait", 30)
MIN_RANDOM_WAIT = get("min_random_wait", 15)
MAX_RANDOM_WAIT = get("max_random_wait", 30)
MIN_RANDOM_WAIT_LONG = get("min_random_wait_long", 30)
MAX_RANDOM_WAIT_LONG = get("max_random_wait_long", 60)
MIN_RANDOM_WAIT_SHORT = get("min_random_wait_short", 3)
MAX_RANDOM_WAIT_SHORT = get("max_random_wait_short", 5)

STATUS_FILE = Path("json/status.json")
ARTICLE_FILE = Path("json/article.json")
TOPICS_FILE = Path("data/topics.txt")
LINKS_FILE = Path("data/links.txt")

PLATFORM = "chatgpt"


# =========================
# RANDOM WAIT
# =========================
def custom_random_wait(min_sec, max_sec):
    seconds = random.uniform(min_sec, max_sec)
    print(f"[WAIT] Sleeping for {seconds:.2f} seconds...", flush=True)
    time.sleep(seconds)


# =========================
# FILE PARSERS & WRITERS
# =========================
def get_last_topic() -> str:
    print("[STEP] Reading topics.txt...", flush=True)
    if not TOPICS_FILE.exists():
        raise FileNotFoundError("❌ 'topics.txt' file not found.")
    with TOPICS_FILE.open("r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    if not lines:
        raise ValueError("❌ 'topics.txt' is empty.")
    selected_topic = lines[-1]
    print(f"[OK] Selected last topic: '{selected_topic}'", flush=True)
    return selected_topic


def remove_last_topic_from_file():
    print("[STEP] Removing the processed topic from topics.txt...", flush=True)
    if not TOPICS_FILE.exists():
        return
    with TOPICS_FILE.open("r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    if lines:
        lines.pop()
    with TOPICS_FILE.open("w", encoding="utf-8") as f:
        for line in lines:
            f.write(f"{line}\n")
    print("[OK] Topic successfully removed from topics.txt", flush=True)


def get_random_promo_link() -> str:
    print("[STEP] Reading links.txt...", flush=True)
    if not LINKS_FILE.exists():
        raise FileNotFoundError("❌ 'links.txt' file not found.")
    with LINKS_FILE.open("r", encoding="utf-8") as f:
        links = [line.strip() for line in f if line.strip()]
    if not links:
        raise ValueError("❌ 'links.txt' is empty. No promo link found.")
    selected_link = random.choice(links)
    print(f"[OK] Randomly selected promo link: '{selected_link}'", flush=True)
    return selected_link


# =========================
# MAIN
# =========================
def run():
    apply_auto_correct()
    print("[START] Script started", flush=True)

    # =========================
    # STATUS CHECK
    # =========================
    if not STATUS_FILE.exists():
        print("[ERROR] status.json file not found. Exiting...", flush=True)
        sys.exit(0)
    try:
        with STATUS_FILE.open("r", encoding="utf-8") as f:
            status_data = json.load(f)
    except Exception as e:
        print(f"[ERROR] status.json parse failed: {e}. Exiting...", flush=True)
        sys.exit(0)

    if status_data.get("generate_content") is not False or status_data.get("generate_image") is not False:
        print("[INFO] Condition did not match (both not False). Exiting safely...", flush=True)
        sys.exit(0)

    print("[OK] Status check passed. Proceeding...", flush=True)

    # File init/clear at the beginning
    ARTICLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with ARTICLE_FILE.open("w", encoding="utf-8") as f:
        f.write("")
    print("[OK] 'article.json' cleared/initialized", flush=True)

    # Get topic and promo link
    try:
        topic = get_last_topic()
        promo_link = get_random_promo_link()
    except Exception as e:
        print(f"[ERROR] Error reading config files: {e}", flush=True)
        sys.exit(1)

    encrypted_files = list(COOKIES_DIR.glob("*.encrypted"))
    if not encrypted_files:
        raise RuntimeError("❌ No .encrypted cookie files found in 'chatgpt_cookies/' folder")

    CHATGPT_COOKIES_FILE = random.choice(encrypted_files)
    print(f"[OK] Randomly selected cookie file: {CHATGPT_COOKIES_FILE.name}", flush=True)

    cookies = load_cookies(Path(CHATGPT_COOKIES_FILE))
    print(f"[OK] Total cookies loaded: {len(cookies)}", flush=True)

    # =========================
    # STEALTH SETUP & LOGIN
    # =========================
    stealth = Stealth()
    pw_cm = stealth.use_sync(sync_playwright())
    pw = pw_cm.__enter__()

    browser = None
    page = None
    try:
        browser = pw.chromium.launch(
            headless=HEADLESS,
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled"
            ]
        )

        context = browser.new_context(
            no_viewport=True,
            user_agent=USER_AGENT
        )

        context.grant_permissions(["clipboard-read", "clipboard-write"])
        print("[STEP] Adding cookies to browser context...", flush=True)
        context.add_cookies(cookies)

        page = context.new_page()
        print("[OK] Cookies added successfully", flush=True)

        print("[STEP] Opening ChatGPT Main URL...", flush=True)
        page.goto(CHATGPT_URL, wait_until="load")
        print("[OK] URL opened successfully (Logged In)", flush=True)

        # 30 to 60 seconds random wait after page load
        custom_random_wait(MIN_RANDOM_WAIT_LONG, MAX_RANDOM_WAIT_LONG)

        # ============================================
        # CHECK LOGIN SUCCESS VIA USER PROFILE BUTTON
        # ============================================
        print("[STEP] Checking login success via profile button...", flush=True)
        profile_button = resolve_locator(page, PLATFORM, "chatgpt_profile_button", "User profile/login menu button")

        if profile_button is not None and profile_button.count() > 0:
            print(f"[OK] LOGIN SUCCESS: Profile button found -> '{profile_button.first.get_attribute('aria-label') or 'User Account'}'", flush=True)
        else:
            print("[WARNING] Profile button not detected directly, proceeding with caution...", flush=True)

        # =========================
        # AUTOMATION FLOW
        # =========================
        print("[STEP] Locating chat textbox...", flush=True)
        textbox = resolve_locator(page, PLATFORM, "chatgpt_textbox", "ChatGPT chat input textbox")

        if textbox is not None and textbox.count() > 0:
            textbox.first.click()
            print("[OK] Textbox located and clicked successfully.", flush=True)
        else:
            raise RuntimeError("❌ Textbox locator could not be loaded (all strategies failed).")

        custom_random_wait(MIN_RANDOM_WAIT, MAX_RANDOM_WAIT)

        # Smart prompt engineering with specific separate paragraph format requirements
        prompt = (
            f"IMPORTANT: Your entire response must be wrapped in a single ```json code block. "
            f"Do not print any JSON outside of a code block under any circumstances. "
            f"Do not add any text, explanation, or markdown before or after the code block.\n\n"

            f"Write a highly engaging article for Medium on the topic: '{topic}'.\n"
            f"Length: 800-1200 words.\n\n"

            f"CRITICAL PROMOTION REQUIREMENT:\n"
            f"You must include a dedicated, standalone paragraph key exactly named \"p_cta\" placed at a natural narrative transition point — roughly in the middle of the article.\n"
            f"The paragraph IMMEDIATELY BEFORE \"p_cta\" must end on a curiosity-triggering note: it should tease a deeper insight, hint at a practical solution, or raise a compelling question that makes the reader feel they need more.\n"
            f"The \"p_cta\" paragraph itself must feel like a natural continuation of that curiosity — not a commercial break. It should directly echo the specific language or idea from the preceding paragraph, making the connection feel precise and inevitable. Never use generic reassuring phrases like 'you're not alone' or 'many people feel this way' — the bridge must feel sharp and specific, not comforting.\n"
            f"The value of \"p_cta\" MUST be exactly formatted in this clean structure:\n"
            f"[1-2 sentences bridging from the preceding paragraph's curiosity hook.] Click Here to Read More on This Topic: {promo_link}\n\n"

            f"OUTPUT FORMATTING:\n"
            f"You MUST deliver the entire article strictly inside a single JSON code block. No conversational text or markdown outside of it.\n"
            f"The JSON structure must match this layout exactly (the 'p_cta' key position is flexible but must be placed naturally between your content paragraphs):\n"
            f"{{\n"
            f'  "title": "{topic}",\n'
            f'  "p1": "Paragraph 1 content...",\n'
            f'  "p2": "Paragraph 2 content...",\n'
            f'  ... \n'
            f'  "p_cta": "[Bridge sentence(s) continuing from the preceding paragraph.] Click Here to Read More on This Topic: {promo_link}",\n'
            f'  ... \n'
            f'  "pn": "Paragraph n content...",\n'
            f'  "conclusion": "Conclusion content...",\n'
            f'  "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"]\n'
            f"}}\n"

            f"REMINDER 1: The 'title' value must match exactly with: '{topic}'.\n"
            f"REMINDER 2: The 'keywords' array MUST contain strictly exactly 5 relevant keywords.\n"
            f"REMINDER 3: Place 'p_cta' dynamically where it fits the narrative — not forced after a fixed paragraph number.\n"
            f"REMINDER 4: The paragraph before 'p_cta' must end with a curiosity hook. The 'p_cta' must open with 1-2 bridge sentences that directly echo the specific idea or language of that hook — never use generic filler phrases.\n"
        )

        print("[STEP] Entering prompt into textbox...", flush=True)
        textbox.first.fill(prompt)
        custom_random_wait(MIN_RANDOM_WAIT, MAX_RANDOM_WAIT)

        print("[STEP] Locating and clicking send button...", flush=True)
        send_button = resolve_locator(page, PLATFORM, "chatgpt_send_button", "ChatGPT send button")
        if send_button is not None:
            send_button.click()
        else:
            raise RuntimeError("❌ Send button locator could not be loaded (all strategies failed).")

        # Initial wait so generation properly starts
        custom_random_wait(MIN_RANDOM_WAIT_LONG, MAX_RANDOM_WAIT_LONG)

        # ============================================
        # STABLE POLLING LIVE STREAM CHECK
        # ============================================
        print("[STEP] Waiting for generated JSON code block to complete writing (periodic checks)...", flush=True)
        code_block_locator = resolve_locator(page, PLATFORM, "chatgpt_code_block", "Generated JSON code block")

        json_content = None
        max_attempts = 5
        for attempt in range(1, max_attempts + 1):
            print(f"[STEP] Checking code block locator (Attempt {attempt}/{max_attempts})...", flush=True)

            if code_block_locator is not None and code_block_locator.count() > 0:
                print("[OK] Code block visible, parsing live text size variations...", flush=True)

                last_length = 0
                max_check_cycles = get("max_code_block_check_cycles", 15)

                for cycle in range(max_check_cycles):
                    time.sleep(15)

                    current_text = code_block_locator.first.inner_text().strip()
                    current_length = len(current_text)

                    print(f"[STREAM INFO] Cycle {cycle+1}: Previous Length = {last_length}, Current Length = {current_length}", flush=True)

                    if current_length > 0 and current_length == last_length:
                        if current_text.endswith("}"):
                            json_content = current_text
                            print("[OK] Content generation is fully finished and finalized.", flush=True)
                            break
                        else:
                            print("[WARNING] Text generation paused but JSON bracket '}' is missing. Waiting further...", flush=True)

                    last_length = current_length

                if json_content:
                    break

            if attempt < max_attempts:
                print(f"[WARNING] Code block not fully written or not found. Next retry window...", flush=True)
                custom_random_wait(MIN_RANDOM_WAIT_LONG, MAX_RANDOM_WAIT_LONG)
            else:
                print("❌ Max retries reached. Streaming incomplete. Exiting script...", flush=True)
                try:
                    browser.close()
                except:
                    pass
                sys.exit(1)

        # JSON parsing, validation and Topic Cleaning
        if json_content:
            try:
                print("[STEP] Parsing content as JSON...", flush=True)
                if json_content.startswith("```json"):
                    json_content = json_content.split("```json", 1)[1]
                if json_content.endswith("```"):
                    json_content = json_content.rsplit("```", 1)[0]

                parsed_json = json.loads(json_content.strip())

                parsed_json["title"] = topic

                print("[STEP] Saving to article.json...", flush=True)
                with ARTICLE_FILE.open("w", encoding="utf-8") as f:
                    json.dump(parsed_json, f, indent=4, ensure_ascii=False)
                print("[OK] Article successfully saved with embedded promo link to article.json", flush=True)

                remove_last_topic_from_file()

                # =========================
                # UPDATE STATUS
                # =========================
                print("[STEP] Updating status.json...", flush=True)
                status_data["generate_content"] = True
                status_data["generate_image"] = False
                with STATUS_FILE.open("w", encoding="utf-8") as f:
                    json.dump(status_data, f, indent=4, ensure_ascii=False)
                print("[OK] status.json successfully updated (generate_content=True)", flush=True)

            except json.JSONDecodeError as je:
                print(f"[ERROR] Content JSON parse failed: {je}. Exiting script...", flush=True)
                try:
                    browser.close()
                except:
                    pass
                sys.exit(1)
        else:
            print("[ERROR] Save skipped because no data was fetched. Exiting script...", flush=True)
            try:
                browser.close()
            except:
                pass
            sys.exit(1)

        # Random wait before closing the browser normally
        print("[STEP] Performing random wait before normal browser closure...", flush=True)
        custom_random_wait(MIN_RANDOM_WAIT, MAX_RANDOM_WAIT)

    except SystemExit:
        raise
    except Exception as e:
        print("[ERROR]", e, flush=True)
        # Capture screenshot on error
        if page is not None:
            try:
                screenshot_path = capture_error_screenshot(page)
                upload_to_onlyfiles(screenshot_path)
            except Exception as screenshot_err:
                print(f"[WARNING] Could not capture or upload screenshot: {screenshot_err}", flush=True)
        if browser:
            try:
                browser.close()
            except:
                pass
        sys.exit(1)

    finally:
        if browser:
            try:
                browser.close()
            except:
                pass
        try:
            pw_cm.__exit__(None, None, None)
        except:
            pass
        print("[DONE] Script finished", flush=True)


if __name__ == "__main__":
    run()