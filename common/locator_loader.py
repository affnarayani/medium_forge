import os
import json
import re
from pathlib import Path

from dotenv import load_dotenv

from common.config_loader import get

load_dotenv()

GEMINI_MODEL = get("gemini_model", "gemini-3.5-flash-lite")

LOCATORS_DIR = Path(__file__).resolve().parent.parent / "locators"
CHANGED_LOCATORS_FILE = LOCATORS_DIR / "changed_locators.json"


def _locators_file(platform: str) -> Path:
    return LOCATORS_DIR / f"{platform}_locators.txt"


def load_locators(platform: str) -> dict:
    """Load locators from locators/{platform}_locators.txt.

    Returns dict: locator_name -> [expr1, expr2, ...]
    First expression is primary; subsequent same-named entries are fallbacks.
    Lines starting with # are comments.
    """
    locators = {}
    path = _locators_file(platform)
    if not path.exists():
        print(f"[WARNING] Locators file not found: {path}", flush=True)
        return locators

    with path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            name, expr = line.split("=", 1)
            name = name.strip()
            expr = expr.strip()
            if not name or not expr:
                continue
            locators.setdefault(name, []).append(expr)
    return locators


def _eval_expr(page, expr_str: str):
    """Evaluate a Playwright locator expression safely with page in scope."""
    try:
        return eval(expr_str, {"page": page, "re": re, "__builtins__": {}}, {})
    except Exception as e:
        print(f"[WARNING] Failed to evaluate locator expression: {expr_str!r} -> {e}", flush=True)
        return None


def _has_match(locator) -> bool:
    if locator is None:
        return False
    try:
        return locator.count() > 0
    except Exception:
        return False


def _normalize_locator(raw: str):
    """Normalize a Gemini-suggested locator into a full page.xxx(...) expression."""
    text = raw.strip().strip("`").strip()
    if text.startswith("python"):
        text = text[len("python"):].strip()
    if text.startswith("page."):
        return text
    # Wrap raw selector / method-call expressions
    if text.startswith("get_by_") or text.startswith("locator("):
        return "page." + text
    return f"page.locator('{text}')"


def _is_fragile_id_selector(expr: str) -> bool:
    """Return True if the expression is a page.locator('#...') generated-ID selector."""
    return expr.startswith("page.locator('#") or expr.startswith('page.locator("#')


def record_broken_locator(platform: str, locator_name: str, broke_expr: str, suggested: str):
    """Record a broken locator + its suggested fix into changed_locators.json."""
    if _is_fragile_id_selector(suggested):
        print(f"[SKIP] Not recording fragile ID-based locator for {platform}/{locator_name}", flush=True)
        return

    entries = []
    if CHANGED_LOCATORS_FILE.exists():
        try:
            with CHANGED_LOCATORS_FILE.open("r", encoding="utf-8") as f:
                entries = json.load(f)
        except Exception:
            entries = []

    # Deduplicate by (platform, locator_name)
    found = False
    for e in entries:
        if e.get("platform") == platform and e.get("locator_name") == locator_name:
            e["broke_locator"] = broke_expr
            e["suggested_locator"] = suggested
            found = True
            break

    if not found:
        entries.append({
            "platform": platform,
            "locator_name": locator_name,
            "broke_locator": broke_expr,
            "suggested_locator": suggested,
        })

    CHANGED_LOCATORS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CHANGED_LOCATORS_FILE.open("w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)


def resolve_locator(page, platform: str, locator_name: str, purpose: str):
    """Resolve a locator by trying primary + fallbacks; first match wins.

    If all fail, invoke Gemini Vision fallback, record in changed_locators.json,
    and return the vision-suggested locator so the current run can proceed.
    Returns None if nothing works.
    """
    entries = load_locators(platform).get(locator_name, [])
    if not entries:
        print(f"[WARNING] No locator entries found for '{locator_name}' in {platform}_locators.txt", flush=True)
        return None

    # Check each expression immediately; first match wins (no timeout wait)
    for expr_str in entries:
        loc = _eval_expr(page, expr_str)
        if loc is not None and _has_match(loc):
            return loc

    # All locators failed -> Gemini Vision fallback
    print(f"[WARNING] All {len(entries)} locator(s) failed for '{locator_name}'. Invoking Gemini Vision fallback...", flush=True)
    primary_expr = entries[0]

    suggested = gemini_vision_fallback(page, locator_name, purpose, primary_expr)
    if not suggested:
        print("[WARNING] Gemini Vision returned no suggestion.", flush=True)
        return None

    normalized = _normalize_locator(suggested)

    # Record for next-run auto-correct (skip fragile ID selectors)
    record_broken_locator(platform, locator_name, primary_expr, normalized)

    # Use the vision-suggested locator in the current run
    try:
        loc = _eval_expr(page, normalized)
        if loc is not None and _has_match(loc):
            print(f"[OK] Gemini Vision locator working for '{locator_name}'.", flush=True)
            return loc
    except Exception:
        pass

    print(f"[WARNING] Gemini-suggested locator also failed for '{locator_name}'.", flush=True)
    try:
        return _eval_expr(page, normalized)
    except Exception:
        return None


def _append_locator_line(platform: str, locator_name: str, suggested: str):
    path = _locators_file(platform)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\n{locator_name} = {suggested}")


def _suggested_in_txt(platform: str, locator_name: str, suggested: str) -> bool:
    locators = load_locators(platform)
    return suggested in locators.get(locator_name, [])


def apply_auto_correct():
    """Process changed_locators.json at the start of each run.

    If auto_correct_locator is ON:
      - Append each suggested locator to the corresponding locator txt file (as fallback).
      - Remove the entry from changed_locators.json.
    If OFF:
      - If suggested locator is already in the txt file, remove the entry.
      - Otherwise keep the entry for manual handling.
    """
    auto_correct = get("auto_correct_locator", True)

    if not CHANGED_LOCATORS_FILE.exists():
        return

    try:
        with CHANGED_LOCATORS_FILE.open("r", encoding="utf-8") as f:
            entries = json.load(f)
    except Exception:
        return

    if not entries:
        return

    remaining = []

    for entry in entries:
        platform = entry.get("platform")
        locator_name = entry.get("locator_name")
        suggested = entry.get("suggested_locator")

        if not platform or not locator_name or not suggested:
            remaining.append(entry)
            continue

        if auto_correct:
            if not _suggested_in_txt(platform, locator_name, suggested):
                _append_locator_line(platform, locator_name, suggested)
                print(f"[AUTO-CORRECT] Appended suggested locator for {platform}/{locator_name}", flush=True)
            # Always remove entry once processed (added or already present)
        else:
            if _suggested_in_txt(platform, locator_name, suggested):
                print(f"[AUTO-CORRECT] Suggested locator already present for {platform}/{locator_name}, removing entry", flush=True)
            else:
                remaining.append(entry)
                print(f"[AUTO-CORRECT] auto_correct off and suggested not in txt, keeping entry for {platform}/{locator_name}", flush=True)

    CHANGED_LOCATORS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CHANGED_LOCATORS_FILE.open("w", encoding="utf-8") as f:
        json.dump(remaining, f, indent=2, ensure_ascii=False)


def gemini_vision_fallback(page, locator_name: str, purpose: str, failed_expression: str):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[WARNING] GEMINI_API_KEY not set. Skipping Gemini Vision fallback.", flush=True)
        return None

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("[WARNING] google-genai not installed. Skipping Gemini Vision fallback.", flush=True)
        return None

    try:
        client = genai.Client(api_key=api_key)
        screenshot_bytes = page.screenshot(full_page=True)
        image_part = types.Part.from_bytes(data=screenshot_bytes, mime_type="image/png")

        prompt = (
            f"I am automating a webpage with Playwright (Python). I need to locate the element: '{purpose}' "
            f"(locator name: '{locator_name}'). The locator expression {failed_expression!r} failed to find the element. "
            f"Based on this screenshot, suggest a corrected Playwright Python locator expression using 'page.' "
            f"(for example: page.get_by_role('button', name='Submit') or page.locator('#id')). "
            f"Return ONLY the locator expression string, no markdown, no explanation, no code block."
        )

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[prompt, image_part],
        )

        text = (response.text or "").strip()
        text = text.strip("`").strip()
        if text.startswith("python"):
            text = text[len("python"):].strip()
        return text if text else None

    except Exception as e:
        print(f"[WARNING] Gemini Vision fallback error: {e}", flush=True)
        return None