"""
agents/extraction_agent.py — Extracts structured study centre data from raw HTML.

Primary:  BeautifulSoup deterministic CSS selectors (fast, no API cost).
Fallback: Qwen3 Coder 480B via OpenRouter for malformed/non-standard HTML.

NIOS results use a card-based layout, NOT tables:
  <div class="studycenter__main-content--tile">
    <div class="ai-data">
      1. Centre Name  <span class="ai-code">CODE <span>(Status)</span></span>
    </div>
    <div class="ai-address">
      <p>Street address</p>
      <p>DISTRICT, State</p>
      <p>Regional Centre : CODE - NAME</p>
      <p>Phone/Email</p>
      <p>Accreditation/Renewal dates</p>
    </div>
    <div class="ai-otherinfo">
      <span class="ai-pincode">...</span>
      <span class="ai-total-seats">...</span>
      ...
    </div>
  </div>

Extracted fields per centre:
  - ai_code     : NIOS AI Code (unique centre ID)
  - name        : Study Centre Name
  - address     : Full address string
  - district    : District name
  - state       : State name
  - category    : Always "Academic" for this agent
"""

from __future__ import annotations

import re
import json
from typing import List, Dict, Optional, Any

from bs4 import BeautifulSoup, Tag

from config import MODELS, OPENROUTER_API_KEY, OPENROUTER_BASE_URL, CATEGORY_NAME
from utils.logger import log


# ─── OpenRouter client ──────────────────────────────────────────

def _get_ai_client():
    from openai import OpenAI
    return OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        default_headers={
            "HTTP-Referer": "https://github.com/nios-agent",
            "X-Title": "NIOS Study Centre Agent",
        },
    )


class ExtractionAgent:
    """
    Parses raw HTML from the NIOS locator results page into
    a list of structured study centre dictionaries.

    The NIOS portal renders results as card tiles
    (.studycenter__main-content--tile), not as HTML tables.
    """

    def extract(
        self,
        html: str,
        state_name: str,
        district_name: str,
    ) -> List[Dict[str, Any]]:
        """
        Main entry point. Tries deterministic extraction first,
        falls back to AI if that yields nothing and AI key is set.

        Returns: list of centre dicts, possibly empty.
        """
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")

        # Check for "no results" page
        if self._is_no_results(soup):
            log.debug(f"  No results for {district_name}, {state_name}")
            return []

        # Try card-based extraction (primary — matches NIOS layout)
        centres = self._extract_from_cards(soup, state_name, district_name)

        # Try table-based extraction as secondary fallback
        if not centres:
            centres = self._extract_from_table(soup, state_name, district_name)

        # AI fallback as last resort
        if not centres and OPENROUTER_API_KEY:
            log.debug(
                f"  Deterministic extraction empty for {district_name}, "
                f"{state_name}. Trying AI fallback..."
            )
            centres = self._ai_extract(html, state_name, district_name)

        return centres

    # ── Card-based Extraction (NIOS primary layout) ────────────

    def _extract_from_cards(
        self,
        soup: BeautifulSoup,
        state_name: str,
        district_name: str,
    ) -> List[Dict[str, Any]]:
        """
        Parse study centre cards from NIOS results page.
        Each card is a .studycenter__main-content--tile div.
        """
        tiles = soup.select(".studycenter__main-content--tile")
        if not tiles:
            return []

        log.debug(f"  Found {len(tiles)} study centre card(s)")
        centres = []

        for tile in tiles:
            centre = self._parse_card(tile, state_name, district_name)
            if centre:
                centres.append(centre)

        return centres

    def _parse_card(
        self,
        tile: Tag,
        state_name: str,
        district_name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Parse a single .studycenter__main-content--tile card into a centre dict.

        HTML structure:
          <div class="ai-data">
            1. Centre Name  <span class="ai-code">CODE <span>(Status)</span></span>
          </div>
          <div class="ai-address">
            <p>Street address</p>
            <p>DISTRICT, State</p>
            ...
          </div>
          <div class="ai-otherinfo">
            <span class="ai-pincode"><strong>Pincode</strong> 110002</span>
            ...
          </div>
        """
        centre: Dict[str, Any] = {
            "state": state_name,
            "district": district_name,
            "category": CATEGORY_NAME,
        }

        # ── Extract AI Code ──
        ai_code_span = tile.select_one(".ai-code")
        if ai_code_span:
            # ai-code span contains: "270154  <span>(Active)</span>"
            # Get just the code text, excluding child spans
            code_text = ai_code_span.find(string=True, recursive=False)
            if code_text:
                centre["ai_code"] = code_text.strip()
            else:
                # Fallback: get all text and remove status
                full_text = ai_code_span.get_text(strip=True)
                # Remove (Active), (Inactive), (Disaccredited) etc.
                code_only = re.sub(r'\(.*?\)', '', full_text).strip()
                centre["ai_code"] = code_only

        # ── Extract Name ──
        ai_data_div = tile.select_one(".ai-data")
        if ai_data_div:
            # Name is the text content before the ai-code span
            # e.g., "1. Govt. Sarvodaya Bal Vidyalaya"
            name_text = ai_data_div.find(string=True, recursive=False)
            if name_text:
                name = name_text.strip()
                # Remove leading "1. ", "2. ", etc.
                name = re.sub(r'^\d+\.\s*', '', name).strip()
                centre["name"] = name

        # ── Extract Address ──
        ai_address_div = tile.select_one(".ai-address")
        if ai_address_div:
            paragraphs = ai_address_div.find_all("p")
            address_parts = []
            for p in paragraphs:
                text = p.get_text(strip=True)
                if not text:
                    continue
                # Skip metadata lines
                if text.startswith("Regional Centre"):
                    continue
                if text.startswith("Accreditation Date"):
                    continue
                if text.startswith("Renewal Date"):
                    continue
                if "Phone No:" in text or "Email:" in text or "Mobile No:" in text:
                    continue
                address_parts.append(text)

            if address_parts:
                centre["address"] = ", ".join(address_parts)

        # ── Extract extra info (pincode, seats, etc.) ──
        ai_otherinfo = tile.select_one(".ai-otherinfo")
        if ai_otherinfo:
            pincode_span = ai_otherinfo.select_one(".ai-pincode")
            if pincode_span:
                pincode_text = pincode_span.get_text(strip=True)
                pincode = re.sub(r'^Pincode\s*', '', pincode_text).strip()
                if pincode:
                    # Append pincode to address
                    addr = centre.get("address", "")
                    if addr and pincode not in addr:
                        centre["address"] = f"{addr} - {pincode}"

        # ── Validate ──
        ai_code = centre.get("ai_code", "").strip()
        if not ai_code:
            return None

        centre["ai_code"] = ai_code
        centre["name"] = centre.get("name", "").strip() or "Unknown"
        centre["address"] = centre.get("address", "").strip()

        return centre

    # ── Table-based Extraction (legacy fallback) ────────────────

    # CSS selectors tried in order
    TABLE_SELECTORS = [
        "table.table",
        "table.dataTable",
        "#result-table",
        ".is__table table",
    ]

    def _extract_from_table(
        self,
        soup: BeautifulSoup,
        state_name: str,
        district_name: str,
    ) -> List[Dict[str, Any]]:
        """
        Find the results table and parse each row into a centre dict.
        Handles multiple known column layouts.
        """
        table = None
        for selector in self.TABLE_SELECTORS:
            table = soup.select_one(selector)
            if table:
                break

        if not table:
            return []

        # Get headers to understand column order
        headers = [
            th.get_text(strip=True).lower()
            for th in table.select("thead th, thead td")
        ]
        log.debug(f"  Table headers: {headers}")

        rows = table.select("tbody tr")
        if not rows:
            # Some pages have no thead; try all tr > td rows
            rows = [r for r in table.select("tr") if r.select("td")]

        centres = []
        for row in rows:
            cells = [td.get_text(separator=" ", strip=True) for td in row.select("td")]
            if not cells:
                continue

            centre = self._parse_row(cells, headers, state_name, district_name)
            if centre:
                centres.append(centre)

        return centres

    def _parse_row(
        self,
        cells: List[str],
        headers: List[str],
        state_name: str,
        district_name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Map table cells to centre fields using header names or positional heuristics.
        NIOS table typically has columns:
          S.No | AI Code | Study Centre Name | Address | District | State
        """
        if not cells or len(cells) < 2:
            return None

        centre: Dict[str, Any] = {
            "state":    state_name,
            "district": district_name,
            "category": CATEGORY_NAME,
        }

        # ── Header-based mapping ──
        if headers:
            col_map = {}
            for i, h in enumerate(headers):
                if i >= len(cells):
                    break
                if any(k in h for k in ["ai code", "ai_code", "code", "centre code"]):
                    col_map["ai_code"] = cells[i]
                elif any(k in h for k in ["centre name", "study centre", "name", "institution"]):
                    col_map["name"] = cells[i]
                elif any(k in h for k in ["address", "location"]):
                    col_map["address"] = cells[i]
                elif "district" in h:
                    col_map["district"] = cells[i] or district_name
                elif "state" in h:
                    col_map["state"] = cells[i] or state_name

            centre.update(col_map)

        # ── Positional fallback (0=SNO, 1=AI_CODE, 2=NAME, 3=ADDRESS...) ──
        else:
            if len(cells) >= 5:
                centre["ai_code"] = cells[1].strip()
                centre["name"]    = cells[2].strip()
                centre["address"] = cells[3].strip()
                if len(cells) >= 6:
                    centre["district"] = cells[4].strip() or district_name
                if len(cells) >= 7:
                    centre["state"] = cells[5].strip() or state_name
            elif len(cells) >= 3:
                centre["ai_code"] = cells[0].strip()
                centre["name"]    = cells[1].strip()
                centre["address"] = cells[2].strip()
            else:
                # Can't parse this row
                return None

        # ── Validate ai_code looks like a real NIOS code ──
        ai_code = centre.get("ai_code", "").strip()
        if not ai_code or not re.search(r'\d', ai_code):
            return None  # Skip rows with no numeric AI code (e.g. header rows)

        # ── Clean up ──
        centre["ai_code"] = ai_code
        centre["name"]    = centre.get("name", "").strip() or "Unknown"
        centre["address"] = centre.get("address", "").strip()

        return centre

    # ── AI Fallback Extraction ─────────────────────────────────

    def _ai_extract(
        self,
        html: str,
        state_name: str,
        district_name: str,
    ) -> List[Dict[str, Any]]:
        """
        Use Qwen3 Coder (free) to extract study centres from HTML
        when deterministic parsing fails.
        Returns parsed JSON list or [].
        """
        # Trim HTML to relevant section to stay within token limits
        soup = BeautifulSoup(html, "lxml")
        # Try to get just the results/content area
        content = soup.find("div", class_=re.compile("card-body|content|result|main|studycenter"))
        trimmed_html = str(content)[:6000] if content else html[:6000]

        prompt = f"""You are a data extraction assistant. Extract ALL NIOS Academic study centre records from this HTML.

State: {state_name}
District: {district_name}

HTML:
{trimmed_html}

Return ONLY a JSON array with objects like:
[
  {{
    "ai_code": "string (NIOS AI Code, required)",
    "name": "string (Study Centre Name, required)",
    "address": "string (Full address)",
    "district": "{district_name}",
    "state": "{state_name}",
    "category": "Academic"
  }}
]

If no study centres are found, return: []
Return ONLY the JSON array, no other text."""

        try:
            client = _get_ai_client()
            response = client.chat.completions.create(
                model=MODELS["extraction"],
                messages=[
                    {"role": "system", "content": "You extract structured data from HTML. Always return valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2000,
                temperature=0.0,
            )
            raw = response.choices[0].message.content.strip()

            # Extract JSON from response (handle markdown code blocks)
            json_match = re.search(r'\[.*\]', raw, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                if isinstance(data, list):
                    log.debug(f"  AI extraction found {len(data)} centres.")
                    return [
                        {**c, "category": CATEGORY_NAME}
                        for c in data
                        if isinstance(c, dict) and c.get("ai_code")
                    ]
        except Exception as e:
            log.debug(f"  AI extraction fallback failed: {e}")

        return []

    # ── Helpers ───────────────────────────────────────────────

    def _is_no_results(self, soup: BeautifulSoup) -> bool:
        """Check if the page indicates no study centres were found."""
        text = soup.get_text().lower()
        no_result_phrases = [
            "no study centre",
            "no record",
            "no result",
            "not found",
            "0 study centre",
            "no data",
        ]
        return any(phrase in text for phrase in no_result_phrases)
