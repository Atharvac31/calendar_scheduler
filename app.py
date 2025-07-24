import streamlit as st
import asyncio
from agent import process_message

st.set_page_config(page_title="📅 Calendar Scheduler", layout="centered")
st.title("📆 Calendar Scheduler")
st.caption("Powered by Google Calendar API ")

# 🗂️ Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# 💬 Display chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 🧾 User input
user_input = st.chat_input("Try: 'Book a meeting tomorrow at 3 PM'")

if user_input:
    # Show user message
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Process via LangGraph agent
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                assistant_reply = asyncio.run(process_message(user_input))
            except Exception as e:
                assistant_reply = f"❌ Error: {str(e)}"

        # 🎯 Smart formatting for event listings
        if assistant_reply.startswith("📅 Upcoming events:"):
            lines = assistant_reply.split("\n")
            with st.expander(lines[0]):
                for line in lines[1:]:
                    st.markdown(f"• {line}")
        else:
            st.markdown(assistant_reply)

        # Store assistant response
        st.session_state.messages.append({"role": "assistant", "content": assistant_reply})