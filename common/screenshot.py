import os
import requests
from pathlib import Path

from dotenv import load_dotenv

from common.config_loader import get

load_dotenv()


def capture_error_screenshot(page) -> str:
    """Capture a full-page error screenshot to /error/error_screenshot.png.

    If the file already exists it is replaced. Returns the saved path.
    """
    error_folder = get("error_folder", "error")
    error_dir = Path(__file__).resolve().parent.parent / error_folder
    error_dir.mkdir(parents=True, exist_ok=True)

    filename = get("error_screenshot_filename", "error_screenshot.png")
    screenshot_path = error_dir / filename

    page.screenshot(path=str(screenshot_path), full_page=True)
    print(f"[OK] Error screenshot captured: {screenshot_path}", flush=True)
    return str(screenshot_path)


def upload_to_onlyfiles(screenshot_path: str) -> str:
    """Upload an error screenshot to OnlyFiles and return the direct URL."""
    url = get("onlyfiles_upload_url", "https://api.onlyfiles.com/v1/upload")
    expire_seconds = get("onlyfiles_expire_seconds", "172800")

    with open(screenshot_path, "rb") as f:
        response = requests.post(url, files={"file": f}, data={"expire": expire_seconds})

    if response.status_code == 200:
        res_data = response.json()
        if res_data.get("status"):
            direct_url = res_data["data"]["file"]["url"]["full"]
            print(f"👉 DIRECT LINK (Expires in 48 Hours): {direct_url}", flush=True)
            return direct_url
        else:
            error_info = res_data.get("error", {})
            print(f"[WARNING] OnlyFiles upload failed: {error_info.get('message', 'Unknown error')}", flush=True)
    else:
        print(f"[WARNING] OnlyFiles upload failed: {response.status_code}", flush=True)

    return None