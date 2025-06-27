import os
import datetime
import pytz
from dotenv import load_dotenv
from dateutil.parser import parse
from typing import Optional, Dict, Any
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# ---------------------- Load Environment ----------------------
# Only for local development
if os.getenv("STREAMLIT_CLOUD") != "true":
    load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/calendar']
INDIA_TZ = pytz.timezone("Asia/Kolkata")

# ---------------------- Google Calendar Auth ----------------------

def get_calendar_service():
    """Load credentials from environment variables and return Google Calendar service."""
    creds_data = {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "refresh_token": os.getenv("GOOGLE_REFRESH_TOKEN"),
        "token_uri": "https://oauth2.googleapis.com/token",
        "type": "authorized_user"
    }
    print(os.getenv("GOOGLE_CLIENT_ID"))
    print(os.getenv("GOOGLE_CLIENT_SECRET"))
    print(os.getenv("GOOGLE_REFRESH_TOKEN"))

    # Check for missing credentials
    missing = [key for key, value in creds_data.items() if not value]
    if missing:
        raise ValueError(f"❌ Missing credentials in environment: {missing}")

    # Build credentials and service
    creds = Credentials.from_authorized_user_info(info=creds_data, scopes=SCOPES)
    service = build('calendar', 'v3', credentials=creds)
    return service


# ---------------------- Helper Functions ----------------------

def ensure_timezone(dt: datetime.datetime) -> datetime.datetime:
    return INDIA_TZ.localize(dt) if dt.tzinfo is None else dt.astimezone(INDIA_TZ)

def format_datetime_range(start: datetime.datetime, hours: float = 1.0) -> Dict[str, str]:
    end = start + datetime.timedelta(hours=hours)
    return {
        "start": ensure_timezone(start).isoformat(),
        "end": ensure_timezone(end).isoformat()
    }

# ---------------------- Event Functions ----------------------

def book_slot(start_time: datetime.datetime, summary: str = "Meeting") -> str:
    try:
        service = get_calendar_service()
        time_range = format_datetime_range(start_time)

        # Conflict check
        events = service.events().list(
            calendarId="primary",
            timeMin=time_range["start"],
            timeMax=time_range["end"],
            singleEvents=True
        ).execute().get("items", [])

        if events:
            return f"❌ Time slot conflict at {ensure_timezone(start_time).strftime('%A %I:%M %p')}."

        event = {
            "summary": summary,
            "start": {"dateTime": time_range["start"], "timeZone": "Asia/Kolkata"},
            "end": {"dateTime": time_range["end"], "timeZone": "Asia/Kolkata"}
        }

        service.events().insert(calendarId="primary", body=event).execute()
        return f"📅 Booked '{summary}' for {ensure_timezone(start_time).strftime('%A %I:%M %p')}!"
    except Exception as e:
        return f"⚠️ Error booking event: {str(e)}"

def get_free_slots(start_time: datetime.datetime) -> str:
    try:
        service = get_calendar_service()
        time_range = format_datetime_range(start_time)

        events = service.events().list(
            calendarId="primary",
            timeMin=time_range["start"],
            timeMax=time_range["end"],
            singleEvents=True
        ).execute().get("items", [])

        formatted = ensure_timezone(start_time).strftime("%A %I:%M %p")
        return f"✅ You are free at {formatted}." if not events else f"❌ You already have an event at {formatted}."
    except Exception as e:
        return f"⚠️ Error checking availability: {str(e)}"

def list_upcoming_events(max_results: int = 5) -> str:
    try:
        service = get_calendar_service()
        now = datetime.datetime.now(INDIA_TZ).isoformat()

        events = service.events().list(
            calendarId="primary",
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime"
        ).execute().get("items", [])

        if not events:
            return "📭 No upcoming events found."

        response = ["📅 Upcoming events:"]
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            dt = parse(start).astimezone(INDIA_TZ)
            response.append(f"• {event.get('summary', 'Untitled')} on {dt.strftime('%A, %d %B %Y at %I:%M %p')}")

        return "\n".join(response)
    except Exception as e:
        return f"⚠️ Error listing events: {str(e)}"

def reschedule_event(summary_text: str, old_time: datetime.datetime, new_time: datetime.datetime) -> str:
    try:
        service = get_calendar_service()
        old_range = format_datetime_range(old_time)

        events = service.events().list(
            calendarId="primary",
            timeMin=old_range["start"],
            timeMax=old_range["end"],
            singleEvents=True
        ).execute().get("items", [])

        for event in events:
            if summary_text.lower() in event.get("summary", "").lower():
                new_range = format_datetime_range(new_time)
                event.update({
                    "start": {"dateTime": new_range["start"], "timeZone": "Asia/Kolkata"},
                    "end": {"dateTime": new_range["end"], "timeZone": "Asia/Kolkata"}
                })

                service.events().update(
                    calendarId="primary",
                    eventId=event["id"],
                    body=event
                ).execute()

                return f"🔁 Rescheduled '{event['summary']}' to {ensure_timezone(new_time).strftime('%A %I:%M %p')}."
        return "⚠️ No matching event found to reschedule."
    except Exception as e:
        return f"⚠️ Error rescheduling event: {str(e)}"

def cancel_event_by_summary(summary_text: str, date_time: datetime.datetime) -> str:
    try:
        service = get_calendar_service()
        time_range = format_datetime_range(date_time)

        events = service.events().list(
            calendarId="primary",
            timeMin=time_range["start"],
            timeMax=time_range["end"],
            singleEvents=True
        ).execute().get("items", [])

        for event in events:
            if summary_text.lower() in event.get("summary", "").lower():
                service.events().delete(
                    calendarId="primary",
                    eventId=event["id"]
                ).execute()
                formatted = ensure_timezone(date_time).strftime('%A %I:%M %p')
                return f"🗑️ Cancelled '{event['summary']}' on {formatted}."

        return "⚠️ No matching event found to cancel."
    except Exception as e:
        return f"⚠️ Error cancelling event: {str(e)}"
