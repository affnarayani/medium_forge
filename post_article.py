import os
import sys
import json
import time
import base64
import random
import requests
from pathlib import Path
from typing import List, Dict, Any

from dotenv import load_dotenv

from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth


# =========================
# CONFIG
# =========================
HEADLESS = True

MEDIUM_COOKIES_FILE = "medium_cookies.json.encrypted"
ARTICLE_FILE = "article.json"
IMAGE_PATH = "image/pin.png"

PBKDF2_ITERATIONS = 200_000

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


# =========================
# DYNAMIC WAITS
# =========================
def custom_random_wait(min_sec=6, max_sec=12):
    seconds = random.uniform(min_sec, max_sec)
    print(f"[WAIT] Sleeping for {seconds:.2f} seconds...", flush=True)
    time.sleep(seconds)


def long_publish_wait():
    seconds = random.uniform(15, 30)
    print(f"[WAIT] Publishing phase delay: Sleeping for {seconds:.2f} seconds...", flush=True)
    time.sleep(seconds)


def keyword_short_wait():
    seconds = random.uniform(3, 6)
    print(f"[WAIT] Keyword input delay: Sleeping for {seconds:.2f} seconds...", flush=True)
    time.sleep(seconds)


# =========================
# CRYPTO
# =========================
def _derive_key(password: bytes, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(password)


def _decrypt_payload(payload: Dict[str, Any], password: str) -> bytes:
    salt = base64.b64decode(payload["s"])
    nonce = base64.b64decode(payload["n"])
    ciphertext = base64.b64decode(payload["ct"])

    key = _derive_key(password.encode("utf-8"), salt)
    aesgcm = AESGCM(key)

    try:
        return aesgcm.decrypt(nonce, ciphertext, None)
    except InvalidTag:
        raise RuntimeError("❌ Decryption failed (InvalidTag)")


def load_cookies(file_path: Path) -> List[Dict[str, Any]]:
    print("[STEP] Loading cookies...", flush=True)

    with file_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    plaintext = _derive_key(DECRYPT_KEY.encode("utf-8"), base64.b64decode(payload["s"]))
    aesgcm = AESGCM(plaintext)
    
    try:
        plaintext = aesgcm.decrypt(base64.b64decode(payload["n"]), base64.b64decode(payload["ct"]), None)
    except InvalidTag:
        raise RuntimeError("❌ Decryption failed (InvalidTag)")

    cookies = json.loads(plaintext.decode("utf-8"))

    for c in cookies:
        if "partitionKey" in c and isinstance(c["partitionKey"], dict):
            if "topLevelSite" in c["partitionKey"]:
                c["partitionKey"] = str(c["partitionKey"]["topLevelSite"])
            else:
                del c["partitionKey"]

        if "sameSite" in c:
            val = str(c["sameSite"]).lower()

            if val in ["no_restriction", "none", "unspecified", "null"]:
                c["sameSite"] = "None"
            elif val == "lax":
                c["sameSite"] = "Lax"
            elif val == "strict":
                c["sameSite"] = "Strict"
            else:
                c["sameSite"] = "Lax"

    print("[OK] Cookies loaded", flush=True)
    return cookies


# =========================
# DATA LOADER
# =========================
def load_article_data(file_path: str) -> Dict[str, Any]:
    print(f"[STEP] Reading article content from {file_path}...", flush=True)
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


# =========================
# MAIN
# =========================
def run():
    print("[START] Script started", flush=True)

    # =========================
    # STATUS CHECK
    # =========================
    status_file = Path("status.json")
    if not status_file.exists():
        print("[ERROR] status.json file nahi mila. Exiting...", flush=True)
        sys.exit(0)
        
    try:
        with status_file.open("r", encoding="utf-8") as f:
            status_data = json.load(f)
    except Exception as e:
        print(f"[ERROR] status.json parse nahi ho paya: {e}. Exiting...", flush=True)
        sys.exit(0)

    # Dono true hone par hi aage badhega, nahi toh exit (0) ho jayega
    if status_data.get("generate_content") is not True or status_data.get("generate_image") is not True:
        print("[INFO] Condition match nahi hui (Dono true nahi hain). Exiting safely...", flush=True)
        sys.exit(0)
        
    print("[OK] Status check passed. Proceeding to Medium publishing...", flush=True)

    if not os.path.exists(IMAGE_PATH):
        print(f"[ERROR] Required image file not found at: {IMAGE_PATH}. Exiting process.", flush=True)
        sys.exit(1)

    cookies = load_cookies(Path(MEDIUM_COOKIES_FILE))
    print(f"[OK] Total cookies loaded: {len(cookies)}", flush=True)

    article_data = load_article_data(ARTICLE_FILE)
    
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
        page.goto(
            "https://medium.com/",
            wait_until="load"
        )
        print("[OK] Medium URL opened completely (Logged In)", flush=True)
        custom_random_wait(15, 30)
        page.get_by_test_id('headerWriteButton').click()
        custom_random_wait(15, 30)
        
        # ============================================
        # EDITOR WORKFLOW
        # ============================================
        
        # 1. Title Input
        print("[STEP] Entering Title...", flush=True)
        title_para = page.get_by_test_id('editorTitleParagraph')
        title_para.wait_for(state="visible")
        title_para.click()
        
        for char in article_title:
            page.keyboard.type(char)
            time.sleep(random.uniform(0.05, 0.15))
            
        print("[OK] Title entered successfully", flush=True)
        custom_random_wait(6, 12)

        print("[STEP] Pressing Enter after title to shift to body...", flush=True)
        page.keyboard.press("Enter")
        custom_random_wait(6, 12)

        # 2. Image Upload
        print("[STEP] Clicking Add Button for Image...", flush=True)
        add_btn = page.get_by_test_id('editorAddButton')
        add_btn.wait_for(state="visible")
        add_btn.click()
        print("[OK] Add button clicked", flush=True)
        custom_random_wait(6, 12)

        print("[STEP] Uploading Image...", flush=True)
        image_btn = page.get_by_role('button', name='Add an image', exact=True)
        image_btn.wait_for(state="visible")

        with page.expect_file_chooser() as fc_info:
            image_btn.click()
        
        file_chooser = fc_info.value
        file_chooser.set_files(IMAGE_PATH)
        print("[OK] Image attached successfully", flush=True)
        custom_random_wait(6, 12)
        
        # 3. Image Caption / Alt Text Input
        print("[STEP] Entering Image Caption...", flush=True)
        caption_element = page.get_by_text('Type caption for image (')
        caption_element.wait_for(state="visible")
        caption_element.click()
        custom_random_wait(6, 12)
        
        for char in article_title:
            page.keyboard.type(char)
            time.sleep(random.uniform(0.05, 0.15))
            
        print("[OK] Image caption added successfully", flush=True)
        custom_random_wait(6, 12)

        print("[STEP] Pressing Enter to move past image into paragraph blocks...", flush=True)
        page.keyboard.press("Enter")
        custom_random_wait(6, 12)

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
                
                custom_random_wait(2, 4)
                
                target_selection = "Click Here to Download This Ebook"
                
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
                
                custom_random_wait(2, 4)
                
                print(f"[STEP] Clicking hyperlink action button...", flush=True)
                link_btn = page.locator('button[data-action="link"]')
                link_btn.wait_for(state="visible")
                link_btn.click()
                custom_random_wait(3, 5)
                
                print(f"[STEP] Filling URL into link input textbox...", flush=True)
                link_input = page.get_by_role('textbox', name='Paste or type a link…')
                link_input.wait_for(state="visible")
                link_input.fill(target_url)
                custom_random_wait(2, 4)
                
                print(f"[STEP] Pressing 1st Enter to embed/save the link...", flush=True)
                link_input.press("Enter")  # 🟢 Isse link save hokar cursor auto next line par aa jata hai.
                custom_random_wait(2, 4)
                
                page.keyboard.press("ArrowRight")
                time.sleep(0.5)

                # 🟢 FIX: Extra page.keyboard.press("Enter") ko hata diya gaya hai taaki extra empty line break na bane.
                custom_random_wait(6, 12)
                
                print(f"[OK] Paragraph ({key}) finished typing (hyperlink handled)", flush=True)
                continue

            elif key == "conclusion":
                subheading_text = "Conclusion"
                print(f"[STEP] Typing heading text: '{subheading_text}'...", flush=True)
                for char in subheading_text:
                    page.keyboard.type(char)
                    time.sleep(random.uniform(0.04, 0.12))
                custom_random_wait(2, 4)

                print(f"[STEP] Selecting heading text...", flush=True)
                page.keyboard.down("Shift")
                for _ in range(len(subheading_text)):
                    page.keyboard.press("ArrowLeft")
                    time.sleep(0.03)
                page.keyboard.up("Shift")
                custom_random_wait(2, 4)

                print("[STEP] Pressing Control+Alt+2 shortcut to increase font...", flush=True)
                page.keyboard.press("Control+Alt+2")
                custom_random_wait(2, 4)

                print("[STEP] Deselecting header text to prevent block deletion...", flush=True)
                page.keyboard.press("ArrowRight")
                time.sleep(0.5)
                
                print("[STEP] Pressing Enter to break line...", flush=True)
                page.keyboard.press("Enter")
                custom_random_wait(4, 8)

                print("[STEP] Injecting main conclusion body paragraphs...", flush=True)
                for char in para_text:
                    page.keyboard.type(char)
                    time.sleep(random.uniform(0.03, 0.10))
                
                print("[OK] Conclusion block handled successfully", flush=True)
                custom_random_wait(6, 12)
                
                print(f"[STEP] Pressing Enter to create next section break...", flush=True)
                page.keyboard.press("Enter")
                custom_random_wait(6, 12)
                continue
                
            else:
                for char in para_text:
                    page.keyboard.type(char)
                    time.sleep(random.uniform(0.03, 0.12)) 
                    
            print(f"[OK] Paragraph ({key}) finished typing", flush=True)
            custom_random_wait(6, 12)
            
            print(f"[STEP] Pressing Enter to create next section break...", flush=True)
            page.keyboard.press("Enter")
            custom_random_wait(6, 12)

        print("[SUCCESS] All dynamic contents appended safely.", flush=True)

        # ============================================
        # PUBLISHING WORKFLOW
        # ============================================
        print("[STEP] Post-writing cool down phase...", flush=True)
        long_publish_wait()

        # 1. Click First Publish Button
        print("[STEP] Clicking primary 'Publish' drop-down button...", flush=True)
        publish_trigger = page.get_by_role('button', name='Publish', exact=True)
        publish_trigger.wait_for(state="visible")
        publish_trigger.click()
        print("[OK] Publish panel opened", flush=True)
        
        long_publish_wait()

        # 2. Add Topics / Keywords
        if chosen_keywords:
            print("[STEP] Locating 'Add a topic...' combobox input...", flush=True)
            topic_input = page.get_by_role('combobox', name='Add a topic...')
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
        final_publish_btn = page.get_by_role('button', name='Publish', exact=True)
        final_publish_btn.wait_for(state="visible")
        final_publish_btn.click()
        print("[SUCCESS] Article successfully published!", flush=True)

        # =========================
        # RESET STATUS TO FALSE
        # =========================
        print("[STEP] Resetting status.json to false...", flush=True)
        status_data["generate_content"] = False
        status_data["generate_image"] = False
        with status_file.open("w", encoding="utf-8") as f:
            json.dump(status_data, f, indent=4, ensure_ascii=False)
        print("[OK] status.json successfully reset (content=False, image=False)", flush=True)

        long_publish_wait()

    except SystemExit:
        raise
    except Exception as e:
        print("[ERROR] Automation cycle broke or publish failed due to runtime trace:", e, flush=True)
        if page is not None:
            try:
                screenshot_path = "error_screenshot.png"
                page.screenshot(path=screenshot_path, full_page=True)
                print(f"[OK] Error screenshot captured: {screenshot_path}", flush=True)
                
                imgbb_key = os.getenv("IMGBBB_API_KEY")
                if imgbb_key:
                    print("[OK] Uploading screenshot to ImgBB...", flush=True)
                    url = f"https://api.imgbb.com/1/upload?expiration=86400&key={imgbb_key}"
                    
                    with open(screenshot_path, "rb") as file:
                        response = requests.post(url, files={"image": file})
                    
                    if response.status_code == 200:
                        res_data = response.json()
                        direct_url = res_data["data"]["display_url"]
                        print("\n" + "="*50, flush=True)
                        print(f"👉 DIRECT SCREENSHOT LINK: {direct_url}", flush=True)
                        print("="*50 + "\n", flush=True)
                    else:
                        print(f"[WARNING] ImgBB Upload Failed Status: {response.status_code}", flush=True)
                else:
                    print("[WARNING] IMGBBB_API_KEY environment variable not found.", flush=True)
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
    load_dotenv()
    DECRYPT_KEY = os.getenv("DECRYPT_KEY")
    if not DECRYPT_KEY:
        raise RuntimeError("DECRYPT_KEY missing")
    run()