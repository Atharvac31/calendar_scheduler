import re
import datetime
import dateparser
import pytz
from typing import TypedDict, List, Dict, Any, Optional, Tuple
from langgraph.graph import StateGraph
from langchain_community.chat_models import ChatOllama

from calendar_utils import (
    book_slot,
    get_free_slots,
    cancel_event_by_summary,
    reschedule_event,
    list_upcoming_events
)


# Timezone setup
INDIA_TZ = pytz.timezone('Asia/Kolkata')

# ----------------- 📆 Utility Functions ------------------

HELP_RESPONSE = """
Here's what I can help with:
• Book a meeting: "Schedule for tomorrow at 3 PM"
• Check availability: "Are you free Friday?"
• Reschedule: "Move my 2 PM meeting to 4 PM"
• Cancel: "Cancel my 3 PM appointment"
• List events: "Show my upcoming meetings"
"""

def clean_text_for_parsing(text: str) -> str:
    """Clean text for better date parsing."""
    text = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', text.lower())
    text = re.sub(r'\b(at|on|from|to)\b', '', text)
    return text.strip(",.!? ")

def inject_default_hour_from_phrase(text: str) -> str:
    """Replace time-related phrases with specific times."""
    text = text.lower()
    replacements = {
        "morning": "9 AM",
        "afternoon": "2 PM",
        "evening": "6 PM",
        "night": "8 PM",
        "noon": "12 PM",
        "midnight": "12 AM"
    }
    for phrase, time in replacements.items():
        if phrase in text:
            return text.replace(phrase, time)
    return text

def ensure_timezone(dt: datetime.datetime) -> datetime.datetime:
    """Ensure datetime is in India timezone."""
    if dt.tzinfo is None:
        return INDIA_TZ.localize(dt)
    return dt.astimezone(INDIA_TZ)

def extract_single_time(text: str) -> Optional[datetime.datetime]:
    text = inject_default_hour_from_phrase(text)
    cleaned = clean_text_for_parsing(text)

    # First, try parsing the full text
    dt = dateparser.parse(
        cleaned,
        settings={
            'PREFER_DATES_FROM': 'future',
            'RELATIVE_BASE': datetime.datetime.now(INDIA_TZ),
            'RETURN_AS_TIMEZONE_AWARE': True
        }
    )

    # Fallback for relative date without time (e.g., 'this Sunday')
    if not dt:
        fallback_match = re.search(r'\b(?:this|next)?\s*(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', cleaned)
        if fallback_match:
            fallback_text = fallback_match.group(0) + " 9 AM"
            dt = dateparser.parse(
                fallback_text,
                settings={
                    'PREFER_DATES_FROM': 'future',
                    'RELATIVE_BASE': datetime.datetime.now(INDIA_TZ),
                    'RETURN_AS_TIMEZONE_AWARE': True
                }
            )

    if dt:
        return ensure_timezone(dt)
    return None


def extract_times_for_reschedule(text: str) -> Tuple[Optional[datetime.datetime], Optional[datetime.datetime]]:
    """Extract both old and new times with timezone handling."""
    from_to_match = re.search(r'from\s+(.+?)\s+to\s+(.+)', text, re.IGNORECASE)
    if from_to_match:
        old_time = extract_single_time(from_to_match.group(1))
        new_time = extract_single_time(from_to_match.group(2))
        if old_time and new_time:
            return old_time, new_time
    
    time_ranges = re.findall(r'\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b', text.lower())
    if len(time_ranges) >= 2:
            old_phrase = re.search(r'(tomorrow|today|next\s+\w+|this\s+\w+)?[^0-9]*' + re.escape(time_ranges[0]), text, re.IGNORECASE)
            new_phrase = re.search(re.escape(time_ranges[1]) + r'[^0-9]*', text, re.IGNORECASE)
            old_time = extract_single_time(old_phrase.group(0)) if old_phrase else None
            new_time = extract_single_time(new_phrase.group(0)) if new_phrase else None
            return old_time, new_time
    
    return None, None

# ----------------- 💬 Intent Detection ------------------

def detect_intent(text: str) -> str:
    """Detect user intent with improved patterns."""
    text = text.lower().strip(",.!?")
    
    if "help" in text:
        return "help"
        
    intent_patterns = {
        "reschedule": r"\b(reschedule|move|change|shift|rearrange)\b",
        "cancel": r"\b(cancel|delete|remove|call\s+off)\b",
        "check": r"\b(free|busy|available|check|when\s+are\s+you)\b",
        "list": r"\b(list|show|upcoming|events|meetings|appointments)\b",
        "book": r"\b(book|schedule|set\s+up|create|meet|set\s+a\s+meeting)\b"
    }
    
    for intent, pattern in intent_patterns.items():
        if re.search(pattern, text):
            return intent
            
    if extract_single_time(text):
        return "book"
        
    return "unknown"

# ----------------- 🤖 Agent Handler ------------------

def handle_user_input(user_input: str) -> str:
    """Main handler with proper error management."""
    try:
        intent = detect_intent(user_input)

        if intent == "help":
            return HELP_RESPONSE
            
        if intent == "list":
            return list_upcoming_events()

        if intent == "reschedule":
            old_time, new_time = extract_times_for_reschedule(user_input)
            if not old_time or not new_time:
                return "❌ Please specify both times clearly, like 'Reschedule from 2 PM to 4 PM'"
            if new_time < datetime.datetime.now(INDIA_TZ):
                return "❌ The new time must be in the future"
            return reschedule_event("TailorTalk Meeting", old_time, new_time)

        parsed_time = extract_single_time(user_input)
        if not parsed_time:
            return "❌ I couldn't understand the time. Try formats like '28 June 10 PM' or 'tomorrow at 3 PM'."

        if intent == "cancel":
            return cancel_event_by_summary("TailorTalk Meeting", parsed_time)
        elif intent == "check":
            return get_free_slots(parsed_time)
        elif intent == "book":
            return book_slot(parsed_time, summary="TailorTalk Meeting")
        else:
            return "🤔 I'm not sure what you're asking. Type 'help' to see what I can do."

    except Exception as e:
        return f"⚠️ An error occurred: {str(e)}. Please try again or contact support."

# ----------------- 🧠 LangGraph Setup ------------------

class AgentState(TypedDict):
    messages: List[Dict[str, Any]]

def run_agent(state: AgentState) -> AgentState:
    """Process user message through the agent workflow."""
    user_msg = state["messages"][-1]["content"]
    result = handle_user_input(user_msg)
    state["messages"].append({"role": "assistant", "content": result})
    return state

# Build the workflow graph
builder = StateGraph(AgentState)
builder.add_node("agent_step", run_agent)
builder.set_entry_point("agent_step")
builder.set_finish_point("agent_step")
graph = builder.compile()

# ----------------- 🚀 FastAPI Entry Point ------------------

async def process_message(user_message: str) -> str:
    """Entry point with error handling."""
    try:
        state = {"messages": [{"role": "user", "content": user_message}]}
        result = graph.invoke(state)
        return result["messages"][-1]["content"]
    except Exception as e:
        return f"⚠️ System error: {str(e)}. Please try again later."
    

# print(f"[Intent] {intent}")
# print(f"[Parsed Time] {parsed_time}")
