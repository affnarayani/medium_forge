import os
import sys
import json
import time
import random
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
MEDIUM_URL = get("medium_url", "https://medium.com/")
PBKDF2_ITERATIONS = get("pbkdf2_iterations", 200000)

MEDIUM_COOKIES_FILE = Path("medium_cookies/medium_cookies.json.encrypted")
ARTICLE_FILE = Path("json/article.json")
IMAGE_PATH = Path("image/pin.png")

STATUS_FILE = Path("json/status.json")

PLATFORM = "medium"

MIN_RANDOM_WAIT = get("min_random_wait", 15)
MAX_RANDOM_WAIT = get("max_random_wait", 30)
MIN_RANDOM_WAIT_SHORT = get("min_random_wait_short", 3)
MAX_RANDOM_WAIT_SHORT = get("max_random_wait_short", 5)
MIN_RANDOM_WAIT_PUBLISH = get("min_random_wait_publish", 15)
MAX_RANDOM_WAIT_PUBLISH = get("max_random_wait_publish", 30)
MIN_RANDOM_WAIT_KEYWORD = get("min_random_wait_keyword", 3)
MAX_RANDOM_WAIT_KEYWORD = get("max_random_wait_keyword", 6)
MIN_RANDOM_WAIT_SHORT_2 = get("min_random_wait_short_2", 2)
MAX_RANDOM_WAIT_SHORT_2 = get("max_random_wait_short_2", 4)
MIN_RANDOM_WAIT_SHORT_3 = get("min_random_wait_short_3", 6)
MAX_RANDOM_WAIT_SHORT_3 = get("max_random_wait_short_3", 12)


# =========================
# DYNAMIC WAITS
# =========================
def custom_random_wait(min_sec=6, max_sec=12):
    seconds = random.uniform(min_sec, max_sec)
    print(f"[WAIT] Sleeping for {seconds:.2f} seconds...", flush=True)
    time.sleep(seconds)


def long_publish_wait():
    seconds = random.uniform(MIN_RANDOM_WAIT_PUBLISH, MAX_RANDOM_WAIT_PUBLISH)
    print(f"[WAIT] Publishing phase delay: Sleeping for {seconds:.2f} seconds...", flush=True)
    time.sleep(seconds)


def keyword_short_wait():
    seconds = random.uniform(MIN_RANDOM_WAIT_KEYWORD, MAX_RANDOM_WAIT_KEYWORD)
    print(f"[WAIT] Keyword input delay: Sleeping for {seconds:.2f} seconds...", flush=True)
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

    # Runs only when both are True
    if status_data.get("generate_content") is not True or status_data.get("generate_image") is not True:
        print("[INFO] Condition did not match (both True required). Exiting safely...", flush=True)
        sys.exit(0)

    print("[OK] Status check passed. Proceeding to Medium publishing...", flush=True)

    if not IMAGE_PATH.exists():
        print(f"[ERROR] Required image file not found at: {IMAGE_PATH}. Exiting process.", flush=True)
        sys.exit(1)

    cookies = load_cookies(MEDIUM_COOKIES_FILE)
    print(f"[OK] Total cookies loaded: {len(cookies)}", flush=True)

    print("[STEP] Reading article content from {ARTICLE_FILE}...", flush=True)
    with open(ARTICLE_FILE, "r", encoding="utf-8") as f:
        article_data = json.load(f)

    article_title = article_data.get("title", "Untitled Story")
    chosen_keywords = article_data.get("keywords", [])
    print(f"[OK] Extracted keywords from JSON: {chosen_keywords}", flush=True)

    raw_keys = [k for k in article_data.keys() if k not in ["title", "keywords"]]
    content_keys = [key for key in raw_keys]

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

        print("[STEP] Opening Medium URL...", flush=True)
        page.goto(MEDIUM_URL, wait_until="load")
        print("[OK] Medium URL opened completely (Logged In)", flush=True)
        custom_random_wait(MIN_RANDOM_WAIT, MAX_RANDOM_WAIT)

        # Click write button
        header_write_btn = resolve_locator(page, PLATFORM, "medium_header_write_button", "Medium header write button")
        if header_write_btn is not None:
            header_write_btn.click()
        custom_random_wait(MIN_RANDOM_WAIT, MAX_RANDOM_WAIT)

        # ============================================
        # EDITOR WORKFLOW
        # ============================================

        # 1. Title Input
        print("[STEP] Entering Title...", flush=True)
        title_para = resolve_locator(page, PLATFORM, "medium_title_paragraph", "Medium editor title paragraph")
        if title_para is not None:
            title_para.wait_for(state="visible")
            title_para.click()

        for char in article_title:
            page.keyboard.type(char)
            time.sleep(random.uniform(0.05, 0.15))

        print("[OK] Title entered successfully", flush=True)
        custom_random_wait(MIN_RANDOM_WAIT_SHORT, MAX_RANDOM_WAIT_SHORT)

        print("[STEP] Pressing Enter after title to shift to body...", flush=True)
        page.keyboard.press("Enter")
        custom_random_wait(MIN_RANDOM_WAIT_SHORT, MAX_RANDOM_WAIT_SHORT)

        # 2. Image Upload
        print("[STEP] Clicking Add Button for Image...", flush=True)
        add_btn = resolve_locator(page, PLATFORM, "medium_editor_add_button", "Medium editor add button")
        if add_btn is not None:
            add_btn.wait_for(state="visible")
            add_btn.click()
        print("[OK] Add button clicked", flush=True)
        custom_random_wait(MIN_RANDOM_WAIT_SHORT, MAX_RANDOM_WAIT_SHORT)

        print("[STEP] Uploading Image...", flush=True)
        image_btn = resolve_locator(page, PLATFORM, "medium_add_image_button", "Medium add image button")
        if image_btn is not None:
            image_btn.wait_for(state="visible")

        with page.expect_file_chooser() as fc_info:
            image_btn.click()

        file_chooser = fc_info.value
        file_chooser.set_files(str(IMAGE_PATH))
        print("[OK] Image attached successfully", flush=True)
        custom_random_wait(MIN_RANDOM_WAIT_SHORT, MAX_RANDOM_WAIT_SHORT)

        # 3. Image Caption / Alt Text Input
        print("[STEP] Entering Image Caption...", flush=True)
        caption_element = resolve_locator(page, PLATFORM, "medium_image_caption", "Medium image caption field")
        if caption_element is not None:
            caption_element.wait_for(state="visible")
            caption_element.click()
        custom_random_wait(MIN_RANDOM_WAIT_SHORT, MAX_RANDOM_WAIT_SHORT)

        for char in article_title:
            page.keyboard.type(char)
            time.sleep(random.uniform(0.05, 0.15))

        print("[OK] Image caption added successfully", flush=True)
        custom_random_wait(MIN_RANDOM_WAIT_SHORT, MAX_RANDOM_WAIT_SHORT)

        print("[STEP] Pressing Enter to move past image into paragraph blocks...", flush=True)
        page.keyboard.press("Enter")
        custom_random_wait(MIN_RANDOM_WAIT_SHORT, MAX_RANDOM_WAIT_SHORT)

        # 4. Dynamic Paragraphs Typing
        for key in content_keys:
            para_text = article_data[key]
            if not para_text.strip():
                continue

            print(f"[STEP] Processing paragraph node ({key})...", flush=True)

            if key == "p_cta" and "http" in para_text:
                print(f"[STEP] Hyperlink formatting detected for p_cta", flush=True)

                parts = para_text.split("http")
                display_text = parts[0].strip()
                target_url = "http" + parts[1].strip()

                clean_display_text = display_text.replace(":", "").strip()

                for char in clean_display_text:
                    page.keyboard.type(char)
                    time.sleep(random.uniform(0.03, 0.12))

                custom_random_wait(MIN_RANDOM_WAIT_SHORT_2, MAX_RANDOM_WAIT_SHORT_2)

                target_selection = "Click Here to Read More on This Topic"

                if target_selection in clean_display_text:
                    print(f"[STEP] Targeting exact anchor text string for selection...", flush=True)
                    page.keyboard.down("Shift")
                    for _ in range(len(target_selection)):
                        page.keyboard.press("ArrowLeft")
                        time.sleep(0.02)
                    page.keyboard.up("Shift")
                else:
                    print(f"[WARNING] Exact anchor match not found, falling back to full block selection...", flush=True)
                    page.keyboard.down("Shift")
                    for _ in range(len(clean_display_text)):
                        page.keyboard.press("ArrowLeft")
                        time.sleep(0.02)
                    page.keyboard.up("Shift")

                custom_random_wait(MIN_RANDOM_WAIT_SHORT_2, MAX_RANDOM_WAIT_SHORT_2)

                print(f"[STEP] Clicking hyperlink action button...", flush=True)
                link_btn = resolve_locator(page, PLATFORM, "medium_link_action_button", "Medium hyperlink action button")
                if link_btn is not None:
                    link_btn.wait_for(state="visible")
                    link_btn.click()
                custom_random_wait(MIN_RANDOM_WAIT_SHORT, MAX_RANDOM_WAIT_SHORT)

                print(f"[STEP] Filling URL into link input textbox...", flush=True)
                link_input = resolve_locator(page, PLATFORM, "medium_link_url_input", "Medium link URL input")
                if link_input is not None:
                    link_input.wait_for(state="visible")
                    link_input.fill(target_url)
                custom_random_wait(MIN_RANDOM_WAIT_SHORT, MAX_RANDOM_WAIT_SHORT)

                print(f"[STEP] Pressing 1st Enter to embed/save the link...", flush=True)
                if link_input is not None:
                    link_input.press("Enter")
                custom_random_wait(MIN_RANDOM_WAIT_SHORT, MAX_RANDOM_WAIT_SHORT)

                page.keyboard.press("ArrowRight")
                time.sleep(0.5)

                custom_random_wait(MIN_RANDOM_WAIT_SHORT_3, MAX_RANDOM_WAIT_SHORT_3)

                print(f"[OK] Paragraph ({key}) finished typing (hyperlink handled)", flush=True)
                continue

            elif key == "conclusion":
                subheading_text = "Conclusion"
                print(f"[STEP] Typing heading text: '{subheading_text}'...", flush=True)
                for char in subheading_text:
                    page.keyboard.type(char)
                    time.sleep(random.uniform(0.04, 0.12))
                custom_random_wait(MIN_RANDOM_WAIT_SHORT_2, MAX_RANDOM_WAIT_SHORT_2)

                print(f"[STEP] Selecting heading text...", flush=True)
                page.keyboard.down("Shift")
                for _ in range(len(subheading_text)):
                    page.keyboard.press("ArrowLeft")
                    time.sleep(0.03)
                page.keyboard.up("Shift")
                custom_random_wait(MIN_RANDOM_WAIT_SHORT_2, MAX_RANDOM_WAIT_SHORT_2)

                print("[STEP] Pressing Control+Alt+2 shortcut to increase font...", flush=True)
                page.keyboard.press("Control+Alt+2")
                custom_random_wait(MIN_RANDOM_WAIT_SHORT_2, MAX_RANDOM_WAIT_SHORT_2)

                print("[STEP] Deselecting header text to prevent block deletion...", flush=True)
                page.keyboard.press("ArrowRight")
                time.sleep(0.5)

                print("[STEP] Pressing Enter to break line...", flush=True)
                page.keyboard.press("Enter")
                custom_random_wait(MIN_RANDOM_WAIT_SHORT_2, MAX_RANDOM_WAIT_SHORT_2)

                print("[STEP] Injecting main conclusion body paragraphs...", flush=True)
                for char in para_text:
                    page.keyboard.type(char)
                    time.sleep(random.uniform(0.03, 0.10))

                print("[OK] Conclusion block handled successfully", flush=True)
                custom_random_wait(MIN_RANDOM_WAIT_SHORT_3, MAX_RANDOM_WAIT_SHORT_3)

                print(f"[STEP] Pressing Enter to create next section break...", flush=True)
                page.keyboard.press("Enter")
                custom_random_wait(MIN_RANDOM_WAIT_SHORT_3, MAX_RANDOM_WAIT_SHORT_3)
                continue

            else:
                for char in para_text:
                    page.keyboard.type(char)
                    time.sleep(random.uniform(0.03, 0.12))

            print(f"[OK] Paragraph ({key}) finished typing", flush=True)
            custom_random_wait(MIN_RANDOM_WAIT_SHORT_3, MAX_RANDOM_WAIT_SHORT_3)

            print(f"[STEP] Pressing Enter to create next section break...", flush=True)
            page.keyboard.press("Enter")
            custom_random_wait(MIN_RANDOM_WAIT_SHORT_3, MAX_RANDOM_WAIT_SHORT_3)

        print("[SUCCESS] All dynamic contents appended safely.", flush=True)

        # ============================================
        # PUBLISHING WORKFLOW
        # ============================================
        print("[STEP] Post-writing cool down phase...", flush=True)
        long_publish_wait()

        # 1. Click First Publish Button
        print("[STEP] Clicking primary 'Publish' drop-down button...", flush=True)
        publish_trigger = resolve_locator(page, PLATFORM, "medium_publish_button", "Medium publish button")
        if publish_trigger is not None:
            publish_trigger.wait_for(state="visible")
            publish_trigger.click()
        print("[OK] Publish panel opened", flush=True)

        long_publish_wait()

        # 2. Add Topics / Keywords
        if chosen_keywords:
            print("[STEP] Locating 'Add a topic...' combobox input...", flush=True)
            topic_input = resolve_locator(page, PLATFORM, "medium_topic_combobox", "Medium topic combobox")
            if topic_input is not None:
                topic_input.wait_for(state="visible")
                topic_input.click()

            for index, kw in enumerate(chosen_keywords, start=1):
                print(f"[STEP] Inserting keyword {index}/{len(chosen_keywords)}: '{kw}'", flush=True)

                for char in kw:
                    page.keyboard.type(char)
                    time.sleep(random.uniform(0.05, 0.15))

                keyword_short_wait()
                print(f"[STEP] Pressing Enter to lock tag '{kw}'...", flush=True)
                page.keyboard.press("Enter")
                keyword_short_wait()

            long_publish_wait()
        else:
            print("[WARNING] No keywords found in JSON metadata, skipping tags injection phase...", flush=True)

        # 3. Click Final Publish Button
        print("[STEP] Executing final story submission button click...", flush=True)
        final_publish_btn = resolve_locator(page, PLATFORM, "medium_publish_confirm_button", "Medium publish confirmation button")
        if final_publish_btn is not None:
            final_publish_btn.wait_for(state="visible")
            final_publish_btn.click()
        print("[SUCCESS] Article successfully published!", flush=True)

        # =========================
        # RESET STATUS TO FALSE
        # =========================
        print("[STEP] Resetting status.json to false...", flush=True)
        status_data["generate_content"] = False
        status_data["generate_image"] = False
        with STATUS_FILE.open("w", encoding="utf-8") as f:
            json.dump(status_data, f, indent=4, ensure_ascii=False)
        print("[OK] status.json successfully reset (content=False, image=False)", flush=True)

        long_publish_wait()

    except SystemExit:
        raise
    except Exception as e:
        print("[ERROR] Automation cycle broke or publish failed due to runtime trace:", e, flush=True)
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

        print("[DONE] Script execution phase closed. Terminating process context cleanly.", flush=True)


if __name__ == "__main__":
    run()