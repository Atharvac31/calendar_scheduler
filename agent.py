import os
import re
import datetime
from typing import List, Dict, Any, Optional, Tuple, TypedDict

import dateparser
import pytz
from langgraph.graph import StateGraph
from rapidfuzz import fuzz

from calendar_utils import (
    book_slot,
    get_free_slots,
    cancel_event_by_summary,
    reschedule_event,
    list_upcoming_events,
)

INDIA_TZ = pytz.timezone("Asia/Kolkata")

HELP_RESPONSE = (
    "Here's what I can help with:\n"
    "• Book a meeting:  \"Schedule for tomorrow at 3 PM\"\n"
    "• Check availability:  \"Are you free Friday?\"\n"
    "• Reschedule:  \"Move my 2 PM meeting to 4 PM\"\n"
    "• Cancel:  \"Cancel my 3 PM appointment\"\n"
    "• List events:  \"Show my upcoming meetings\""
)

GREETINGS = {"hi", "hello", "hey", "good morning", "good evening", "what's up"}

INTENT_PATTERNS = {
    "reschedule": r"\b(reschedule|move|change|shift|rearrange|postpone|push back)\b",
    "cancel": r"\b(cancel|delete|remove|call off|drop|scrap)\b",
    "check": r"\b(free|busy|available|availability|occupied|check)\b",
    "list": r"\b(list|show|see|what are my|upcoming|schedule|meetings|events|appointments)\b",
    "book": r"\b(book|schedule|set up|create|make|plan|add|meet)\b",
}


# ---------------------- Utilities ----------------------
def ensure_timezone(dt: datetime.datetime) -> datetime.datetime:
    if dt.tzinfo is None:
        return INDIA_TZ.localize(dt)
    return dt.astimezone(INDIA_TZ)

def clean_text(text: str) -> str:
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", text.lower())
    cleaned = re.sub(r"\b(at|on|from|to)\b", "", cleaned)
    return cleaned.strip(",.!? ")

def inject_default_hour(text: str) -> str:
    mapping = {
        "morning": "9 AM",
        "afternoon": "2 PM",
        "evening": "6 PM",
        "night": "8 PM",
        "noon": "12 PM",
        "midnight": "12 AM"
    }
    for word, time in mapping.items():
        if word in text:
            return text.replace(word, time)
    return text

def extract_single_time(text: str) -> Optional[datetime.datetime]:
    # Save original in case fallback needed
    original_text = text

    text = inject_default_hour(text)

    # Remove only soft noise words that interfere (don't remove month/day info)
    for word in ["meeting", "appointment", "call", "event"]:
        text = text.replace(word, "")

    cleaned = clean_text(text)

    # First attempt
    dt = dateparser.parse(
        cleaned,
        settings={
            'PREFER_DATES_FROM': 'future',
            'RELATIVE_BASE': datetime.datetime.now(INDIA_TZ),
            'RETURN_AS_TIMEZONE_AWARE': True,
            'TIMEZONE': 'Asia/Kolkata',
            'TO_TIMEZONE': 'Asia/Kolkata',
        }
    )

    # Fallback for things like "26th July 2pm"
    if not dt:
        fallback_match = re.search(
            r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?::\d{2})?\s*(am|pm)?",
            original_text,
            re.IGNORECASE,
        )
        if fallback_match:
            dt = dateparser.parse(fallback_match.group(0))

    # Fallback for "tomorrow 3pm"
    if not dt:
        relative_match = re.search(
            r"(tomorrow|today|tonight|next\s+\w+|this\s+\w+)?\s*\d{1,2}(?::\d{2})?\s*(am|pm)",
            original_text,
            re.IGNORECASE,
        )
        if relative_match:
            dt = dateparser.parse(relative_match.group(0))

    if dt:
        if dt.hour == 0 and dt.minute == 0:
            dt = dt.replace(hour=9, minute=0)
        return ensure_timezone(dt)

    return None



def extract_times_for_reschedule(text: str) -> Tuple[Optional[datetime.datetime], Optional[datetime.datetime]]:
    m = re.search(r"from\\s+(.+?)\\s+to\\s+(.+)", text, re.IGNORECASE)
    if m:
        old_time = extract_single_time(m.group(1))
        new_time = extract_single_time(m.group(2))
        return old_time, new_time
    times = re.findall(r"\\b\\d{1,2}(?::\\d{2})?\\s*(?:am|pm)\\b", text.lower())
    if len(times) >= 2:
        old = extract_single_time(times[0])
        new = extract_single_time(times[1])
        return old, new
    return None, None

def is_greeting(text: str) -> bool:
    GREETING_KEYWORDS = ["hi", "hello", "hey", "hii", "heyy", "good morning", "good evening"]
    return any(fuzz.ratio(text.lower(), word) > 85 for word in GREETING_KEYWORDS)


def fuzzy_match(text: str, choices: List[str], threshold: int = 85) -> Optional[str]:
    for choice in choices:
        if fuzz.ratio(text, choice) > threshold:
            return choice
    return None


# ---------------------- Intent Detection ----------------------
def detect_intent(text: str) -> str:
    if is_greeting(text):
        return "greeting"
    for intent, pattern in INTENT_PATTERNS.items():
        if re.search(pattern, text.lower()):
            return intent
    if extract_single_time(text):
        return "book"
    return "unknown"


# ---------------------- Handler ----------------------
def handle_user_input(user_input: str) -> str:
    intent = detect_intent(user_input)

    if intent == "greeting":
        return "👋 Hello! I'm your calendar assistant. Try saying 'Book a meeting tomorrow at 3 PM'."

    if intent == "help":
        return HELP_RESPONSE

    if intent == "list":
        return list_upcoming_events()

    if intent == "reschedule":
        old_time, new_time = extract_times_for_reschedule(user_input)
        if not old_time or not new_time:
            return "❌ Please provide both old and new times, e.g. 'Move meeting from 2 PM to 4 PM tomorrow'."
        if new_time < datetime.datetime.now(INDIA_TZ):
            return "❌ The new time must be in the future."
        return reschedule_event("TailorTalk Meeting", old_time, new_time)

    parsed_time = extract_single_time(user_input)
    if not parsed_time:
        return "❌ I couldn't understand the time. Try '28 June 10 PM' or 'tomorrow at 3 PM'."

    if intent == "cancel":
        return cancel_event_by_summary("TailorTalk Meeting", parsed_time)

    if intent == "check":
        return get_free_slots(parsed_time)

    if intent == "book":
        return book_slot(parsed_time, summary="TailorTalk Meeting")

    return "🤔 I'm not sure what you're asking. Type 'help' to see what I can do."


# ---------------------- LangGraph Setup ----------------------
class AgentState(TypedDict):
    messages: List[Dict[str, Any]]

def _run_agent(state: AgentState) -> AgentState:
    user_msg = state["messages"][-1]["content"]
    reply = handle_user_input(user_msg)
    state["messages"].append({"role": "assistant", "content": reply})
    return state

_builder = StateGraph(AgentState)
_builder.add_node("agent_step", _run_agent)
_builder.set_entry_point("agent_step")
_builder.set_finish_point("agent_step")
graph = _builder.compile()

async def process_message(user_message: str) -> str:
    try:
        state = {"messages": [{"role": "user", "content": user_message}]}
        result = graph.invoke(state)
        return result["messages"][-1]["content"]
    except Exception as e:
        return f"⚠️ System error: {str(e)}. Please try again later."

if __name__ == "__main__":
    print("Calendar Assistant ready!  (type 'quit' to exit)")
    while True:
        try:
            user_input = input("You: ")
        except EOFError:
            break
        if user_input.lower() in {"quit", "exit"}:
            break
        print("Assistant:", handle_user_input(user_input))
