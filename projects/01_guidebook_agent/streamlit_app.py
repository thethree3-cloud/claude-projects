import streamlit as st

from ask import answer_question

st.set_page_config(page_title="HR Handbook Agent", page_icon="📖")
st.title("HR & Policy Guidebook Agent")
st.caption("Ask a question about the Las Vegas employee handbook.")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

question = st.chat_input("Ask about the handbook...")
if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Routing and answering..."):
            reply = answer_question(question)
        st.markdown(reply)
    st.session_state.messages.append({"role": "assistant", "content": reply})
