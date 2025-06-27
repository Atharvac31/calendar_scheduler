import streamlit as st
import asyncio
from agent import process_message  # Import your agent directly

st.set_page_config(page_title="Calendar Scheduler", layout="centered")
st.title("📅 Calendar Scheduler - Your Calendar Assistant")

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display past chat messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Chat input
user_input = st.chat_input("Say something like 'Book a meeting tomorrow at 3 PM'...")

# Handle new user input
if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                assistant_reply = asyncio.run(process_message(user_input))
            except Exception as e:
                assistant_reply = f"❌ Error: {str(e)}"

        # Enhanced response rendering
        if assistant_reply.startswith("📅 Upcoming events:") or assistant_reply.startswith("📅 Events on"):
            events = assistant_reply.split("\n")
            with st.expander(events[0]):
                for line in events[1:]:
                    st.markdown(f"• {line}")
        else:
            st.markdown(assistant_reply)

        st.session_state.messages.append({"role": "assistant", "content": assistant_reply})
