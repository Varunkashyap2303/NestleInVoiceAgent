"""
Tool definitions and execution layer.
Claude calls these to search for services and send SMS messages.
"""

import os
import json
import logging
from pathlib import Path

import httpx
from twilio.rest import Client as TwilioClient

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Tool schemas (passed to Claude)
# ─────────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "search_local_services",
        "description": (
            "Search the local resource database for services matching the caller's needs. "
            "Returns a list of services with name, address, phone number, and hours. "
            "Always search before telling the caller about specific services."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": [
                        "shelter",
                        "food",
                        "health",
                        "mental_health",
                        "legal",
                        "financial",
                        "domestic_violence",
                        "substance_support",
                        "general",
                    ],
                    "description": "The type of service the caller needs.",
                },
                "suburb": {
                    "type": "string",
                    "description": "Suburb or postcode the caller is in or near. Use this to filter results.",
                },
                "urgency": {
                    "type": "string",
                    "enum": ["tonight", "this_week", "general"],
                    "description": "How urgently the caller needs help.",
                },
            },
            "required": ["category"],
        },
    },
    {
        "name": "send_sms",
        "description": (
            "Send an SMS to the caller with a summary of services found. "
            "Only call this after the caller has confirmed their mobile number. "
            "Keep the message under 300 characters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to_number": {
                    "type": "string",
                    "description": "Caller's mobile number in E.164 format, e.g. +61412345678",
                },
                "message": {
                    "type": "string",
                    "description": "The SMS message content. Include service name, address, and phone.",
                },
            },
            "required": ["to_number", "message"],
        },
    },
    {
        "name": "get_crisis_lines",
        "description": (
            "Returns national and state crisis line numbers for immediate support. "
            "Use when the caller seems in danger, mentions self-harm, or needs urgent mental health support."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "state": {
                    "type": "string",
                    "description": "Australian state abbreviation, e.g. VIC, NSW, QLD. Optional.",
                },
            },
            "required": [],
        },
    },
]


# ─────────────────────────────────────────────────────────────
# Tool execution
# ─────────────────────────────────────────────────────────────

async def execute_tool(name: str, inputs: dict) -> str:
    """Dispatch a tool call and return a string result for Claude."""
    if name == "search_local_services":
        return await search_local_services(**inputs)
    elif name == "send_sms":
        return await send_sms(**inputs)
    elif name == "get_crisis_lines":
        return get_crisis_lines(**inputs)
    else:
        return f"Unknown tool: {name}"


async def search_local_services(
    category: str,
    suburb: str = "",
    urgency: str = "general",
) -> str:
    """
    Search the resource database.
    In production, replace this with a real database query or API call
    (e.g. AskIzzy API, Infoxchange, or your own curated database).
    """
    # Try AskIzzy API first (Australia's largest social services directory)
    try:
        results = await _query_askizzy(category, suburb)
        if results:
            return results
    except Exception as e:
        logger.warning(f"AskIzzy API failed: {e}, falling back to local DB")

    # Fall back to local JSON database
    return _query_local_db(category, suburb, urgency)


async def _query_askizzy(category: str, suburb: str) -> str:
    """
    Query AskIzzy (Infoxchange) API.
    Docs: https://github.com/ask-izzy/ask-izzy
    Set ASKIZZY_API_KEY in your .env to enable this.
    """
    api_key = os.getenv("ASKIZZY_API_KEY")
    if not api_key:
        raise ValueError("No ASKIZZY_API_KEY set")

    category_map = {
        "shelter": "accommodation",
        "food": "food",
        "health": "health",
        "mental_health": "mental-health",
        "legal": "legal",
        "financial": "centrelink-financial-help",
        "domestic_violence": "domestic-family-violence-crisis",
        "substance_support": "drug-support",
        "general": "housing",
    }

    service_type = category_map.get(category, "housing")
    params = {"type": service_type, "location": suburb or "Melbourne VIC"}

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.prod.askizzy.org.au/api/v3/search/",
            params=params,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()

    objects = data.get("objects", [])[:3]
    if not objects:
        return "No services found via AskIzzy for that category and location."

    lines = []
    for s in objects:
        name = s.get("name", "Unknown")
        address = s.get("location", {}).get("full_address", "Address not listed")
        phone = next(
            (c["number"] for c in s.get("phones", []) if c.get("number")), "No phone listed"
        )
        hours = s.get("open", {}).get("humanReadable", "Hours not listed")
        lines.append(f"• {name} | {address} | Ph: {phone} | {hours}")

    return "\n".join(lines)


def _query_local_db(category: str, suburb: str, urgency: str) -> str:
    """
    Query the local JSON resource database.
    Edit resources/services.json to add your own curated services.
    """
    db_path = Path("resources/services.json")
    if not db_path.exists():
        return "Resource database not found. Please add services to resources/services.json."

    with open(db_path) as f:
        db = json.load(f)

    services = db.get("services", [])

    # Filter by category
    matches = [
        s for s in services
        if category.lower() in [c.lower() for c in s.get("categories", [])]
    ]

    # Filter by suburb if provided
    if suburb:
        suburb_lower = suburb.lower()
        suburb_matches = [
            s for s in matches
            if suburb_lower in s.get("suburb", "").lower()
            or suburb_lower in s.get("postcode", "")
        ]
        if suburb_matches:
            matches = suburb_matches

    # Prioritise urgent/overnight options
    if urgency == "tonight":
        urgent = [s for s in matches if s.get("accepts_walkins") or s.get("24_hour")]
        if urgent:
            matches = urgent

    if not matches:
        return f"No {category} services found in the local database{' near ' + suburb if suburb else ''}."

    lines = []
    for s in matches[:3]:
        name = s.get("name", "Unknown")
        address = s.get("address", "Address not listed")
        phone = s.get("phone", "Phone not listed")
        hours = s.get("hours", "Hours not listed")
        notes = s.get("notes", "")
        entry = f"• {name} | {address} | Ph: {phone} | {hours}"
        if notes:
            entry += f" | {notes}"
        lines.append(entry)

    return "\n".join(lines)


async def send_sms(to_number: str, message: str) -> str:
    """Send an SMS via Twilio."""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_PHONE_NUMBER")

    if not all([account_sid, auth_token, from_number]):
        return "SMS not sent — Twilio credentials not configured."

    try:
        client = TwilioClient(account_sid, auth_token)
        msg = client.messages.create(
            body=message[:320],  # SMS length limit
            from_=from_number,
            to=to_number,
        )
        logger.info(f"SMS sent: {msg.sid}")
        return f"SMS sent successfully to {to_number}."
    except Exception as e:
        logger.error(f"SMS failed: {e}")
        return f"Failed to send SMS: {str(e)}"


def get_crisis_lines(state: str = "") -> str:
    """Return crisis line numbers."""
    lines = [
        "• Lifeline: 13 11 14 (24/7)",
        "• Beyond Blue: 1300 22 4636 (24/7)",
        "• 1800RESPECT (DV): 1800 737 732 (24/7)",
        "• Suicide Call Back: 1300 659 467",
        "• Kids Helpline: 1800 55 1800",
    ]

    state_lines = {
        "VIC": ["• Launch Housing Crisis Line: 1800 825 955 (24/7)"],
        "NSW": ["• Link2Home (NSW): 1800 152 152 (24/7)"],
        "QLD": ["• DVConnect: 1800 811 811 (24/7)"],
        "SA": ["• Homeless Connect SA: 1800 003 308"],
        "WA": ["• Entrypoint Perth: (08) 9325 5010"],
    }

    if state.upper() in state_lines:
        lines = state_lines[state.upper()] + lines

    return "\n".join(lines)
