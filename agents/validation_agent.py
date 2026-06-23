"""
agents/validation_agent.py — Validates and annotates extracted study centre records.

Primary:  Rule-based validation (no API cost).
Fallback: GPT-OSS 20B (openai/gpt-oss-20b:free) for ambiguous cases.

Checks:
  - Required fields present: ai_code, name, district, state
  - address not empty (warns but keeps record)
  - ai_code matches expected NIOS format (digits, often 5 chars)
  - Deduplication marker (tracked by ai_code)
"""

from __future__ import annotations

import re
import json
from typing import List, Dict, Any, Set, Tuple

from config import MODELS, OPENROUTER_API_KEY, OPENROUTER_BASE_URL
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


class ValidationAgent:
    """
    Validates a batch of extracted study centre records.
    Annotates each with is_valid and missing_fields.
    Deduplicates by ai_code within the current batch.
    """

    # NIOS AI codes are typically 5-digit numbers (e.g., "12345")
    # but can also be alphanumeric (e.g., "AP001")
    AI_CODE_PATTERN = re.compile(r'^[A-Z0-9\-/]{2,20}$', re.IGNORECASE)

    REQUIRED_FIELDS = ["ai_code", "name", "district", "state"]
    RECOMMENDED_FIELDS = ["address"]

    def __init__(self):
        self._seen_ai_codes: Set[str] = set()  # tracks duplicates within a run

    def reset_dedup(self) -> None:
        """Call this at the start of each new scrape run."""
        self._seen_ai_codes.clear()

    def validate_batch(
        self,
        centres: List[Dict[str, Any]],
        use_ai_fallback: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Validate a list of centre records.
        Returns: annotated list with is_valid and missing_fields added.
        Duplicates (same ai_code) are removed with a warning.
        """
        validated = []
        duplicates = 0

        for centre in centres:
            # ── Deduplication ──
            ai_code = str(centre.get("ai_code", "")).strip().upper()
            if ai_code in self._seen_ai_codes:
                duplicates += 1
                log.debug(f"    Duplicate ai_code skipped: {ai_code}")
                continue
            if ai_code:
                self._seen_ai_codes.add(ai_code)

            # ── Rule-based validation ──
            is_valid, missing, warnings = self._validate_rules(centre)

            # ── AI fallback for ambiguous records ──
            if not is_valid and use_ai_fallback and OPENROUTER_API_KEY:
                ai_verdict = self._ai_validate(centre, missing)
                if ai_verdict is not None:
                    is_valid = ai_verdict

            # ── Annotate record ──
            centre["is_valid"]       = is_valid
            centre["missing_fields"] = missing
            centre["ai_code"]        = ai_code  # normalised to uppercase

            if warnings:
                for w in warnings:
                    log.debug(f"    Validation warning [{ai_code}]: {w}")

            validated.append(centre)

        if duplicates:
            log.info(f"    Removed {duplicates} duplicate(s) from batch.")

        valid_count   = sum(1 for c in validated if c["is_valid"])
        invalid_count = len(validated) - valid_count
        if invalid_count:
            log.warning(f"    {invalid_count} record(s) marked invalid in batch.")

        return validated

    # ── Rule-Based Validation ──────────────────────────────────

    def _validate_rules(
        self,
        centre: Dict[str, Any],
    ) -> Tuple[bool, List[str], List[str]]:
        """
        Returns: (is_valid, missing_required_fields, warnings)
        A record is invalid only if REQUIRED fields are missing.
        Empty address is a warning, not an error.
        """
        missing = []
        warnings = []

        # Check required fields
        for field in self.REQUIRED_FIELDS:
            val = str(centre.get(field, "")).strip()
            if not val:
                missing.append(field)

        # Check AI code format (sanity check)
        ai_code = str(centre.get("ai_code", "")).strip()
        if ai_code and not self.AI_CODE_PATTERN.match(ai_code):
            warnings.append(f"Unusual ai_code format: {ai_code!r}")

        # Check recommended fields
        for field in self.RECOMMENDED_FIELDS:
            val = str(centre.get(field, "")).strip()
            if not val:
                warnings.append(f"Missing recommended field: {field}")

        # Check name is not just whitespace or a number
        name = str(centre.get("name", "")).strip()
        if name and name.isdigit():
            warnings.append(f"Name appears to be numeric: {name!r}")

        is_valid = len(missing) == 0
        return is_valid, missing, warnings

    # ── AI Fallback Validation ─────────────────────────────────

    def _ai_validate(
        self,
        centre: Dict[str, Any],
        missing_fields: List[str],
    ) -> Optional[bool]:
        """
        Ask GPT-OSS 20B Free to determine if a record with missing fields
        is still salvageable (e.g., ai_code can be inferred from name).
        Returns True/False/None (None = keep rule-based decision).
        """
        try:
            client = _get_ai_client()
            prompt = f"""A NIOS study centre record has these missing fields: {missing_fields}

Record data: {json.dumps(centre, ensure_ascii=False)}

Is this record still valid/useful even with the missing fields?
Answer with ONLY "yes" or "no"."""

            response = client.chat.completions.create(
                model=MODELS["validation"],
                messages=[
                    {"role": "system", "content": "You are a data quality validator. Answer only yes or no."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=10,
                temperature=0.0,
            )
            answer = response.choices[0].message.content.strip().lower()
            return "yes" in answer
        except Exception as e:
            log.debug(f"AI validation fallback failed: {e}")
            return None


# ── Type hint fix ──────────────────────────────────────────────
from typing import Optional
