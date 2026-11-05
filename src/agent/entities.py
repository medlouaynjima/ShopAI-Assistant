"""Shared extraction and normalization for customer-facing identifiers."""
import re


# Existing seeded IDs have four digits; new checkout IDs have ten hex characters.
# Requiring a four-character suffix also prevents the word "order" matching "ORD".
ORDER_ID_PATTERN = re.compile(r"\bORD[-\s]?([A-Z0-9]{4,})\b", re.IGNORECASE)


def extract_order_id(value: object) -> str:
    match = ORDER_ID_PATTERN.search(str(value or ""))
    return f"ORD-{match.group(1).upper()}" if match else ""
