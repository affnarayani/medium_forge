import os
import sys
import json
import time
import random
from pathlib import Path

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
MAX_RETRIES = get("max_retries", 10)

COOKIES_DIR = Path("chatgpt_cookies")
IMAGE_DIR = Path("image")
IMAGE_DIR.mkdir(exist_ok=True)

MIN_RANDOM_WAIT = get("min_random_wait", 15)
MAX_RANDOM_WAIT = get("max_random_wait", 30)
MIN_RANDOM_WAIT_LONG = get("min_random_wait_long", 30)
MAX_RANDOM_WAIT_LONG = get("max_random_wait_long", 60)
MIN_RANDOM_WAIT_SHORT = get("min_random_wait_short", 3)
MAX_RANDOM_WAIT_SHORT = get("max_random_wait_short", 5)

STATUS_FILE = Path("json/status.json")
ARTICLE_FILE = Path("json/article.json")

PLATFORM = "chatgpt"


# =========================
# RANDOM WAIT
# =========================
def custom_random_wait(min_sec, max_sec):
    seconds = random.uniform(min_sec, max_sec)
    print(f"[WAIT] Sleeping for {seconds:.2f} seconds...", flush=True)
    time.sleep(seconds)


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

    # Runs only when generate_content == True and generate_image == False
    if status_data.get("generate_content") is not True or status_data.get("generate_image") is not False:
        print("[INFO] Condition did not match (generate_content True and generate_image False required). Exiting safely...", flush=True)
        sys.exit(0)

    print("[OK] Status check passed. Proceeding to image generation...", flush=True)

    # Load article data
    print("[STEP] Loading article JSON...", flush=True)
    ARTICLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with ARTICLE_FILE.open("r", encoding="utf-8") as json_file:
        article_data = json.load(json_file)
    article_title = article_data["title"]
    print(f"[OK] Article Title extracted: {article_title}", flush=True)

    article_keywords = article_data["keywords"]
    print(f"[OK] Article Keywords extracted: {article_keywords}", flush=True)

    encrypted_files = list(COOKIES_DIR.glob("*.encrypted"))
    if not encrypted_files:
        raise RuntimeError("❌ No .encrypted cookie files found in 'chatgpt_cookies/' folder")

    CHATGPT_COOKIES_FILE = random.choice(encrypted_files)
    print(f"[OK] Randomly selected cookie file: {CHATGPT_COOKIES_FILE.name}", flush=True)

    cookies = load_cookies(Path(CHATGPT_COOKIES_FILE))
    print(f"[OK] Total cookies loaded: {len(cookies)}", flush=True)

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

        # Image generation prompt (must not be changed)
        prompt = (
            "You are an expert AI image engineer specializing in editorial and article cover visuals. "
            "Based on the following article details, generate a highly descriptive, cinematic, and emotionally resonant image "
            "suitable for a Medium article header image. The image should NOT look like a book cover. "
            "Instead, it should feel like a high-quality editorial photograph or digital artwork — "
            "think conceptual, atmospheric, and thought-provoking, the kind used in top Medium publications. "
            "The scene should metaphorically represent the core theme without showing any text, titles, or book covers. "
            "Vary the visual style intentionally — choose ONE of the following that best fits the article's emotional tone: "
            "surreal illustration, cinematic photography, abstract art, minimalist concept art, or moody atmospheric scene. "
            "Do NOT default to clichéd imagery like figures surrounded by swirling thoughts or cracked heads. "
            "Push toward unexpected, elegant, and original visual metaphors that feel fresh and premium. "
            "Respond ONLY with the final optimized image. Do not include any introduction, explanation, or markdown.\n\n"
            "Article Details:\n"
            f"Title: {article_title}\n"
            f"Core Keywords: {', '.join(article_keywords)}\n"
            "STRICT RULES: No text, no words, no letters, no book covers, no logos anywhere in the image. "
            "Suitable as a Medium article hero image."
        )

        print("[STEP] Opening ChatGPT Main URL...", flush=True)
        page.goto(CHATGPT_URL, wait_until="load")
        print("[OK] URL opened", flush=True)

        # Initial random wait (30-60 seconds)
        print("[STEP] Performing initial random wait (30-60 seconds)...", flush=True)
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

        # Step 1: Open image creation mode
        print("[STEP] Locating 'Create an image' button...", flush=True)
        create_image_btn = resolve_locator(page, PLATFORM, "chatgpt_create_image_button", "Create an image button")

        if create_image_btn is not None and create_image_btn.count() > 0:
            create_image_btn.first.click()
            print("[STEP] Create an image button clicked!", flush=True)
            custom_random_wait(MIN_RANDOM_WAIT_SHORT, MAX_RANDOM_WAIT_SHORT)
        else:
            print("[INFO] 'Create an image' button not found, proceeding to chat input anyway.", flush=True)

        # Step 2: Locate chat box and type prompt (with fallbacks via resolve_locator)
        print("[STEP] Locating chat textbox...", flush=True)
        chat_box = resolve_locator(page, PLATFORM, "chatgpt_textbox", "ChatGPT chat input textbox")

        if chat_box is not None and chat_box.count() > 0:
            chat_box.first.click()
            print("[OK] Textbox located and clicked successfully.", flush=True)
        else:
            raise RuntimeError("❌ Textbox locator could not be loaded (all strategies failed).")

        prompt_text = f"Generate a photorealistic or artistic editorial image with a size strictly of 1672x941 px at a 16:9 aspect ratio. The image should serve as a compelling Medium article header — no text, no overlays, no book covers. Depict the following scene in high detail and cinematic quality: {prompt}"
        print(f"[STEP] Filling prompt: '{prompt_text}'", flush=True)
        chat_box.first.fill(prompt_text)
        custom_random_wait(MIN_RANDOM_WAIT_SHORT, MAX_RANDOM_WAIT_SHORT)

        page.keyboard.press("Enter")
        print("[OK] Prompt sent successfully", flush=True)

        # Step 3: Wait for image generation -> Share button -> Download
        share_button = None
        found_share = False

        for attempt in range(1, MAX_RETRIES + 1):
            print(f"[STEP] Waiting for image generation... Attempt {attempt}/{MAX_RETRIES}", flush=True)
            custom_random_wait(MIN_RANDOM_WAIT_LONG, MAX_RANDOM_WAIT_LONG)

            try:
                locator = resolve_locator(page, PLATFORM, "chatgpt_share_image_button", "Share this image button")
                if locator is not None and locator.is_visible():
                    share_button = locator
                    found_share = True
                    print("✅ 'Share this image' button located successfully!", flush=True)
                    break
            except Exception as loc_err:
                print(f"[INFO] Share locator exception: {loc_err}", flush=True)

            print(f"[WARNING] Share button not visible on attempt {attempt}. Retrying...", flush=True)

        if not found_share or share_button is None:
            print("❌ Error: 'Share this image' button not found after retries. Exiting program.", flush=True)
            if page is not None:
                try:
                    screenshot_path = capture_error_screenshot(page)
                    upload_to_onlyfiles(screenshot_path)
                except Exception as screenshot_err:
                    print(f"[WARNING] Could not capture or upload screenshot: {screenshot_err}", flush=True)
            sys.exit(1)

        print("[STEP] Clicking 'Share this image' button...", flush=True)
        share_button.click()
        custom_random_wait(MIN_RANDOM_WAIT_SHORT, MAX_RANDOM_WAIT_SHORT)

        print("[STEP] Clicking 'Download' button...", flush=True)
        download_btn = resolve_locator(page, PLATFORM, "chatgpt_download_button", "Download button")

        if download_btn is None or download_btn.count() == 0:
            print("❌ Error: 'Download' button not found. Exiting program.", flush=True)
            if page is not None:
                try:
                    screenshot_path = capture_error_screenshot(page)
                    upload_to_onlyfiles(screenshot_path)
                except Exception as screenshot_err:
                    print(f"[WARNING] Could not capture or upload screenshot: {screenshot_err}", flush=True)
            sys.exit(1)

        with page.expect_download(timeout=60000) as download_info:
            download_btn.click()

        download = download_info.value
        local_filename = IMAGE_DIR / "pin.png"
        download.save_as(local_filename)
        print(f"✅ Image downloaded successfully: {local_filename}", flush=True)

        # Final random wait before exit
        print("[STEP] Performing final random wait before exit (30-60 seconds)...", flush=True)
        custom_random_wait(MIN_RANDOM_WAIT_LONG, MAX_RANDOM_WAIT_LONG)

        # Update status to both True
        status_data["generate_content"] = True
        status_data["generate_image"] = True
        with STATUS_FILE.open("w", encoding="utf-8") as f:
            json.dump(status_data, f, indent=4, ensure_ascii=False)

        print("[DONE] Image download successfully processed.", flush=True)

    except SystemExit:
        raise
    except Exception as e:
        print("[ERROR]", e, flush=True)
        if page is not None:
            try:
                screenshot_path = capture_error_screenshot(page)
                upload_to_onlyfiles(screenshot_path)
            except Exception as screenshot_err:
                print(f"[WARNING] Could not capture or upload screenshot: {screenshot_err}", flush=True)
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