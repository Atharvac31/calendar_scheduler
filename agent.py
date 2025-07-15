import os
import re
import datetime
from typing import List, Dict, Any, Optional, Tuple, TypedDict

 # --------- Third‑party imports ---------
import dateparser
import pytz
from langgraph.graph import StateGraph

 # --------- Local package imports ---------
from calendar_utils import (
     book_slot,
     get_free_slots,
     cancel_event_by_summary,
     reschedule_event,
     list_upcoming_events,
 )

 # --------- LLM backend selection ---------
if os.getenv("USE_OLLAMA", "false").lower() == "true":
     # Local inference through Ollama → http://localhost:11434
     from llm_ollama import chat as llm_chat  # noqa: F401  (imported for future use)
else:
     # Cloud‑hosted model (e.g. OpenAI / Together / Groq)
     from openai_client import chat as llm_chat  # type: ignore  # noqa: F401

 # ----------------------------------------------------------------------------------
 # 🕒 Timezone setup
 # ----------------------------------------------------------------------------------
INDIA_TZ = pytz.timezone("Asia/Kolkata")

 # ----------------------------------------------------------------------------------
 # 📋 Help message shown when user asks “help”
 # ----------------------------------------------------------------------------------
HELP_RESPONSE = (
    "Here's what I can help with:\n"
    "• Book a meeting:  \"Schedule for tomorrow at 3 PM\"\n"
    "• Check availability:  \"Are you free Friday?\"\n"
    "• Reschedule:  \"Move my 2 PM meeting to 4 PM\"\n"
    "• Cancel:  \"Cancel my 3 PM appointment\"\n"
    "• List events:  \"Show my upcoming meetings\""
)


 # ----------------------------------------------------------------------------------
 # 🛠️ Utility functions
 # ----------------------------------------------------------------------------------

def _ensure_timezone(dt: datetime.datetime) -> datetime.datetime:
     """Attach or convert to IST."""
     if dt.tzinfo is None:
         return INDIA_TZ.localize(dt)
     return dt.astimezone(INDIA_TZ)


def _clean_text_for_parsing(text: str) -> str:
     """Minor clean‑ups so `dateparser` has an easier life."""
     cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", text.lower())
     cleaned = re.sub(r"\b(at|on|from|to)\b", "", cleaned)
     return cleaned.strip(",.!? ")


def _inject_default_hour(text: str) -> str:
     """Convert vague phrases (\"tomorrow evening\") into explicit times (\"tomorrow 6 PM\")."""
     replacements = {
         "morning": "9 AM",
         "afternoon": "2 PM",
         "evening": "6 PM",
         "night": "8 PM",
         "noon": "12 PM",
         "midnight": "12 AM",
     }
     for phrase, default in replacements.items():
         if phrase in text:
             return text.replace(phrase, default)
     return text


def _extract_single_time(text: str) -> Optional[datetime.datetime]:
     """Return a timezone‑aware datetime if present in *text*; else None."""
     text = _inject_default_hour(text)
     cleaned = _clean_text_for_parsing(text)

     dt = dateparser.parse(
         cleaned,
         settings={
             "PREFER_DATES_FROM": "future",
             "RELATIVE_BASE": datetime.datetime.now(INDIA_TZ),
             "RETURN_AS_TIMEZONE_AWARE": True,
         },
     )

     # ➡️ Fallback heuristics for edge cases -------------------------------------------------
     if not dt:
         # e.g. "28 Jun 10 pm"
         m = re.search(
             r"(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?::\d{2})?\s*(am|pm)",
             cleaned,
             re.IGNORECASE,
         )
         if m:
             dt = dateparser.parse(m.group(0))

     if not dt:
         # e.g. "tomorrow 5 pm"
         m = re.search(
             r"(tomorrow|today|next\s+\w+|this\s+\w+)?\s*\d{1,2}(?::\d{2})?\s*(am|pm)",
             cleaned,
             re.IGNORECASE,
         )
         if m:
             dt = dateparser.parse(m.group(0))

     if dt:
         # if only date provided, default to 9 AM
         if dt.hour == 0 and dt.minute == 0:
             dt = dt.replace(hour=9, minute=0)
         return _ensure_timezone(dt)

     return None


def _extract_times_for_reschedule(text: str) -> Tuple[Optional[datetime.datetime], Optional[datetime.datetime]]:
     """Return (old_time, new_time) or (None, None)."""
     # pattern: "from 2 PM to 4 PM tomorrow"
     m = re.search(r"from\s+(.+?)\s+to\s+(.+)", text, re.IGNORECASE)
     if m:
         old_t = _extract_single_time(m.group(1))
         new_t = _extract_single_time(m.group(2))
         return old_t, new_t

     # fallback: find the first two explicit times in text
     matches = re.findall(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", text.lower())
     if len(matches) >= 2:
         old_t = _extract_single_time(matches[0])
         new_t = _extract_single_time(matches[1])
         return old_t, new_t

     return None, None


 # ----------------------------------------------------------------------------------
 # 🔍 Intent detection (regex‑based)
 # ----------------------------------------------------------------------------------
_INTENT_PATTERNS: Dict[str, str] = {
     "reschedule": r"\b(reschedule|move|change|shift|rearrange)\b",
     "cancel": r"\b(cancel|delete|remove|call\s+off)\b",
     "check": r"\b(free|busy|available|check|when\s+are\s+you)\b",
     "list": r"\b(list|show|upcoming|events|meetings|appointments)\b",
     "book": r"\b(book|schedule|set\s+up|create|meet|set\s+a\s+meeting)\b",
 }


def _detect_intent(text: str) -> str:
     text_lc = text.lower().strip(",.!? ")

     if "help" in text_lc:
         return "help"

     for intent, pattern in _INTENT_PATTERNS.items():
         if re.search(pattern, text_lc):
             return intent

     # heuristic: if we can parse a time, assume booking
     if _extract_single_time(text_lc):
         return "book"

     return "unknown"


 # ----------------------------------------------------------------------------------
 # 🤖 Core handler
 # ----------------------------------------------------------------------------------
def handle_user_input(user_input: str) -> str:
     """Parse *user_input* and perform the requested calendar action."""
     try:
         intent = _detect_intent(user_input)

         # ---------- help / list ----------
         if intent == "help":
             return HELP_RESPONSE
         if intent == "list":
             return list_upcoming_events()

         # ---------- reschedule ----------
         if intent == "reschedule":
             old_t, new_t = _extract_times_for_reschedule(user_input)
             if not old_t or not new_t:
                 return (
                     "❌ Please specify both times clearly, e.g. "
                     "'Reschedule from 2 PM to 4 PM tomorrow'"
                 )
             if new_t < datetime.datetime.now(INDIA_TZ):
                 return "❌ The new time must be in the future."
             return reschedule_event("TailorTalk Meeting", old_t, new_t)

         # ---------- book / cancel / check ----------
         parsed_t = _extract_single_time(user_input)
         if not parsed_t:
             return (
                 "❌ I couldn't understand the time. Try formats like "
                 "'28 June 10 PM' or 'tomorrow at 3 PM'."
             )

         if intent == "cancel":
             # e.g. "cancel meeting tomorrow" without explicit time
             if "tomorrow" in user_input.lower() and not re.search(r"\d{1,2}(?::\d{2})?\s*(am|pm)", user_input.lower()):
                 return "❗ Please specify the time, e.g. 'cancel meeting tomorrow at 3 PM'."
             return cancel_event_by_summary("TailorTalk Meeting", parsed_t)

         if intent == "check":
             return get_free_slots(parsed_t)

         if intent == "book":
             return book_slot(parsed_t, summary="TailorTalk Meeting")

         return "🤔 I'm not sure what you're asking. Type 'help' to see what I can do."

     except Exception as exc:
         return f"⚠️ An error occurred: {exc}. Please try again later."


 # ----------------------------------------------------------------------------------
 # 🧩 LangGraph integration
 # ----------------------------------------------------------------------------------
class AgentState(TypedDict):
     messages: List[Dict[str, Any]]


def _run_agent(state: AgentState) -> AgentState:
     """Single LangGraph node: appends assistant reply to state."""
     user_msg = state["messages"][-1]["content"]
     reply = handle_user_input(user_msg)
     state["messages"].append({"role": "assistant", "content": reply})
     return state


 # Build LangGraph workflow (trivial single‑node graph)
_builder = StateGraph(AgentState)
_builder.add_node("agent_step", _run_agent)
_builder.set_entry_point("agent_step")
_builder.set_finish_point("agent_step")
graph = _builder.compile()


 # ----------------------------------------------------------------------------------
 # 🌐 Async entry‑point (used by FastAPI or other servers)
 # ----------------------------------------------------------------------------------
async def process_message(user_message: str) -> str:
     """Public coroutine: given *user_message*, return assistant reply."""
     try:
         state: AgentState = {"messages": [{"role": "user", "content": user_message}]}
         result = graph.invoke(state)
         return result["messages"][-1]["content"]
     except Exception as exc:
         return f"⚠️ System error: {exc}. Please try again later."


 # ----------------------------------------------------------------------------------
 # For quick CLI testing -------------------------------------------------------------
 # ----------------------------------------------------------------------------------
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
