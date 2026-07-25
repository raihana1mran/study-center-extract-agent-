"""
agents/browser_agent.py — Playwright headless browser agent.

Responsibilities:
  1. Navigate to the NIOS Study Centre Locator.
  2. Select Category = Academic, Country = India, State, District.
  3. Submit the form and return the raw results HTML.
  4. Enumerate districts for a given state via AJAX interception.

The NIOS portal uses Chosen.js to replace native <select> elements with
custom styled dropdowns. We interact via JavaScript to set values on
the hidden <select> and trigger jQuery change events so Chosen.js,
dependent-dropdown AJAX, and Yii2 form logic all fire correctly.

Uses: Gemma 4 26B (google/gemma-4-26b-a4b-it:free) as AI fallback for
      complex navigation decisions. Primary logic is deterministic Playwright.
"""

from __future__ import annotations

import time
import json
import re
from pathlib import Path
from typing import List, Dict, Optional

from playwright.sync_api import (
    sync_playwright, Page, Browser, BrowserContext,
    TimeoutError as PlaywrightTimeout
)

from config import (
    NIOS_LOCATOR_URL, HEADLESS, BROWSER_TIMEOUT_MS, FORM_TIMEOUT_MS,
    CATEGORY_ACADEMIC, COUNTRY_CODE_INDIA, REQUEST_DELAY_SECONDS,
    SCREENSHOTS_DIR, MODELS, OPENROUTER_API_KEY, OPENROUTER_BASE_URL,
)
from utils.logger import log


# ─── OpenRouter client (AI fallback) ────────────────────────────

def _get_ai_client():
    """Return an OpenAI-compatible client pointed at OpenRouter."""
    from openai import OpenAI
    return OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        default_headers={
            "HTTP-Referer": "https://github.com/nios-agent",
            "X-Title": "NIOS Study Centre Agent",
        },
    )


# ─── Chosen.js Helper ──────────────────────────────────────────

def _js_set_chosen_value(select_id: str, value: str) -> str:
    """Build JS snippet to set value on a Chosen.js-wrapped <select>."""
    return f"""
    (() => {{
        const sel = document.getElementById('{select_id}');
        if (!sel) throw new Error('Select #{select_id} not found');
        sel.value = '{value}';
        if (typeof jQuery !== 'undefined') {{
            jQuery('#{select_id}').val('{value}').trigger('change').trigger('chosen:updated');
        }} else {{
            sel.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }}
        return true;
    }})()
    """


def _js_read_options(select_id: str) -> str:
    """Build JS snippet to read all <option> values from a <select>."""
    return f"""
    (() => {{
        const sel = document.getElementById('{select_id}');
        if (!sel) return [];
        return Array.from(sel.options)
            .filter(o => o.value !== '')
            .map(o => ({{ name: o.text.trim(), code: o.value }}));
    }})()
    """


class BrowserAgent:
    """
    Manages a single Playwright browser session for scraping NIOS.
    Call open() before use, close() when done.
    """

    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    # ── Lifecycle ──────────────────────────────────────────────

    def open(self) -> None:
        """Launch headless Chromium browser."""
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        self._context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        self._page = self._context.new_page()
        self._page.set_default_timeout(BROWSER_TIMEOUT_MS)
        log.debug("Browser launched (headless={})".format(HEADLESS))

    def close(self) -> None:
        """Clean up browser resources."""
        try:
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception as e:
            log.debug(f"Browser close warning: {e}")

    # ── Chosen.js interaction helpers ─────────────────────────

    def _chosen_select(self, select_id: str, value: str) -> None:
        """
        Set value on a Chosen.js-wrapped <select> element via JavaScript.
        This sets the native select value and triggers jQuery change events
        so both Chosen UI and AJAX dependent-dropdown logic update properly.
        """
        page = self._page
        try:
            page.evaluate(_js_set_chosen_value(select_id, value))
            log.debug(f"  Chosen select #{select_id} = {value}")
        except Exception as e:
            log.error(f"  Chosen select #{select_id} failed: {e}")
            self._screenshot(f"chosen_fail_{select_id}")
            raise

    def _read_select_options(self, select_id: str) -> List[Dict[str, str]]:
        """Read all options from a <select> element (works even if Chosen-wrapped)."""
        return self._page.evaluate(_js_read_options(select_id)) or []

    def _wait_for_select_populated(
        self, select_id: str, state_code: str, timeout_ms: int = None
    ) -> bool:
        """Wait until a <select> is populated with options for the given state code."""
        timeout = timeout_ms or FORM_TIMEOUT_MS
        try:
            self._page.wait_for_function(
                f"""() => {{
                    const sel = document.getElementById('{select_id}');
                    if (!sel) return false;
                    const options = Array.from(sel.options).filter(o => o.value !== '');
                    if (options.length === 0) return false;
                    
                    // Wait for jQuery AJAX requests to complete
                    if (typeof jQuery !== 'undefined' && jQuery.active > 0) {{
                        return false;
                    }}
                    
                    return options.every(o => o.value.startsWith('{state_code}'));
                }}""",
                timeout=timeout,
            )
            return True
        except PlaywrightTimeout:
            return False

    # ── Navigate & prepare form ───────────────────────────────

    def _navigate_and_set_base_fields(self) -> None:
        """Navigate to form and select Category=Academic, Country=India."""
        page = self._page

        page.goto(NIOS_LOCATOR_URL, wait_until="networkidle")
        time.sleep(1.5)

        # Wait for jQuery/Chosen to be ready
        try:
            page.wait_for_function(
                "() => typeof jQuery !== 'undefined' && jQuery('.chzn-search').length > 0",
                timeout=10_000,
            )
        except PlaywrightTimeout:
            log.warning("jQuery/Chosen not detected; proceeding anyway.")

        # Category = Academic
        self._chosen_select("locatestudycenter-category", CATEGORY_ACADEMIC)
        time.sleep(0.8)

        # Country = India
        self._chosen_select("locatestudycenter-country_code", COUNTRY_CODE_INDIA)
        time.sleep(0.8)

    # ── District Enumeration ───────────────────────────────────

    def get_districts(self, state_code: str) -> List[Dict[str, str]]:
        """
        Navigate to locator page, select state, capture the AJAX-loaded
        district dropdown, and return list of {name, code} dicts.
        """
        districts = []

        try:
            self._navigate_and_set_base_fields()

            # Select State — triggers AJAX district load
            self._chosen_select("locatestudycenter-state_code", state_code)

            # Wait for district dropdown to be populated by AJAX
            # The district select may be: locatestudycenter-district_code or district_code
            district_select_id = self._find_district_select_id()

            if district_select_id:
                populated = self._wait_for_select_populated(
                    district_select_id, state_code, timeout_ms=FORM_TIMEOUT_MS
                )
                if populated:
                    districts = self._read_select_options(district_select_id)
                else:
                    log.warning(
                        f"District dropdown #{district_select_id} didn't populate "
                        f"for state {state_code}."
                    )
                    self._screenshot(f"no_districts_{state_code}")
            else:
                log.warning(f"Could not find district <select> for state {state_code}.")
                self._screenshot(f"no_district_select_{state_code}")

        except PlaywrightTimeout as e:
            log.error(f"Timeout getting districts for state {state_code}: {e}")
            self._screenshot(f"timeout_districts_{state_code}")
            raise

        except Exception as e:
            log.error(f"Error getting districts for state {state_code}: {e}")
            self._screenshot(f"error_districts_{state_code}")
            raise

        return districts

    def _find_district_select_id(self) -> Optional[str]:
        """
        Find the district dropdown's ID. NIOS may use different IDs;
        search for common patterns.
        """
        candidates = [
            "locatestudycenter-district_code",
            "locatestudycenter-districtcode",
            "district_code",
        ]
        for cid in candidates:
            exists = self._page.evaluate(
                f"() => !!document.getElementById('{cid}')"
            )
            if exists:
                return cid

        # Fallback: find any select whose id/name contains 'district'
        found_id = self._page.evaluate("""
            () => {
                const selects = document.querySelectorAll('select');
                for (const sel of selects) {
                    if ((sel.id && sel.id.toLowerCase().includes('district')) ||
                        (sel.name && sel.name.toLowerCase().includes('district'))) {
                        return sel.id || null;
                    }
                }
                return null;
            }
        """)
        return found_id

    # ── Study Centre Search ────────────────────────────────────

    def search_study_centres(
        self,
        state_code: str,
        state_name: str,
        district_code: str,
        district_name: str,
    ) -> str:
        """
        Fill the locator form for state+district+Academic and return
        the raw HTML of the results section.

        Returns: HTML string of results table, or "" on failure.
        """
        page = self._page

        try:
            self._navigate_and_set_base_fields()

            # ── Select State ──
            self._chosen_select("locatestudycenter-state_code", state_code)

            # Wait for district dropdown to populate
            district_select_id = self._find_district_select_id()
            if district_select_id:
                self._wait_for_select_populated(district_select_id, state_code, timeout_ms=FORM_TIMEOUT_MS)
                time.sleep(0.5)

                # ── Select District ──
                self._chosen_select(district_select_id, district_code)
                time.sleep(0.5)
            else:
                log.warning(f"No district select found; submitting without district.")

            # ── Click Submit button with navigation wait ──
            # The form does a full POST navigation, not AJAX
            try:
                with page.expect_navigation(
                    timeout=FORM_TIMEOUT_MS, wait_until="networkidle"
                ):
                    page.click(
                        "button:has-text('Submit'), input[type='submit']"
                    )
                log.debug(f"  Page navigated after submit for {district_name}")
            except PlaywrightTimeout:
                log.debug(
                    f"  Navigation timeout for {district_name}; "
                    f"reading page anyway."
                )

            time.sleep(1.5)

            # Wait for results container (card-based layout)
            try:
                page.wait_for_selector(
                    ".studycenter__main, .studycenter__main-content, "
                    ".studycenter__main-content--tile, .ai-data",
                    timeout=5000,
                )
            except PlaywrightTimeout:
                log.debug(
                    f"  No results container found for {district_name}; "
                    f"reading full page."
                )

            # Return the full page HTML for the extraction agent
            html = page.content()
            return html

        except PlaywrightTimeout as e:
            log.error(
                f"Timeout during search: State={state_name}, "
                f"District={district_name}: {e}"
            )
            self._screenshot(f"timeout_{state_code}_{district_code}")
            raise

        except Exception as e:
            log.error(
                f"Error searching: State={state_name}, "
                f"District={district_name}: {e}"
            )
            self._screenshot(f"error_{state_code}_{district_code}")
            raise

    # ── AI Fallback: Describe page for navigation help ─────────

    def ai_describe_page(self, context_hint: str = "") -> str:
        """
        Use Gemma Free via OpenRouter to describe current page content
        and suggest next navigation step. Used as an AI fallback.
        """
        if not OPENROUTER_API_KEY:
            return ""
        try:
            client = _get_ai_client()
            page_text = self._page.inner_text("body")[:3000]
            response = client.chat.completions.create(
                model=MODELS["browser"],
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a web navigation assistant. Analyze the page content "
                            "and help identify form elements, results tables, and next steps "
                            "for NIOS study centre extraction."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Context: {context_hint}\n\nPage content:\n{page_text}\n\n"
                            "What do you see? Are there study centre results? "
                            "Any errors or unexpected states?"
                        ),
                    },
                ],
                max_tokens=500,
                temperature=0.1,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            log.debug(f"AI browser fallback failed: {e}")
            return ""

    # ── Helpers ───────────────────────────────────────────────

    def _screenshot(self, name: str) -> None:
        """Take a debug screenshot saved to logs/screenshots/."""
        try:
            path = SCREENSHOTS_DIR / f"{name}.png"
            self._page.screenshot(path=str(path))
            log.debug(f"Screenshot saved: {path}")
        except Exception:
            pass

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *_):
        self.close()
