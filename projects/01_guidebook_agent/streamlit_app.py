import streamlit as st

from ask import answer_question_full, render_page_png

MAX_PAGES_SHOWN = 3  # per source

st.set_page_config(page_title="HR Handbook Agent", page_icon="📖", layout="wide")
st.title("HR & Policy Guidebook Agent")
st.caption(
    "Ask a question about the Las Vegas employee handbook. Answers come only from "
    "the handbook. Open a source to see the actual page."
)

EXAMPLES = [
    "What is the policy on smoking?",
    "Who is eligible for family and medical leave?",
    "What should I do if I'm hurt on the job?",
    "Can I have a second job?",
]


@st.cache_data(show_spinner=False)
def page_image(page_number):
    return render_page_png(page_number)


def show_sources(sources, searched_as, question):
    if searched_as and searched_as != question:
        st.caption(f"Searched as: *{searched_as}*")
    if not sources:
        return
    st.markdown("**Sources**")
    for source in sources:
        with st.expander(f"{source['subject']} (pages {source['start']}-{source['end']})"):
            last = min(source["end"], source["start"] + MAX_PAGES_SHOWN - 1)
            for page in range(source["start"], last + 1):
                st.image(page_image(page), caption=f"Page {page}", use_container_width=True)


if "messages" not in st.session_state:
    st.session_state.messages = []

with st.sidebar:
    st.subheader("Try asking")
    for example in EXAMPLES:
        if st.button(example, use_container_width=True):
            st.session_state.pending = example
    if st.session_state.messages and st.button("New conversation", type="secondary"):
        st.session_state.messages = []
        st.rerun()

for i, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant":
            show_sources(message["sources"], message["searched_as"],
                         st.session_state.messages[i - 1]["content"])

question = st.chat_input("Ask about the handbook...") or st.session_state.pop("pending", None)
if question:
    history = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Routing and answering..."):
            result = answer_question_full(question, history)
        st.markdown(result["answer"])
        show_sources(result["sources"], result["searched_as"], question)
    st.session_state.messages.append({
        "role": "assistant",
        "content": result["answer"],
        "sources": result["sources"],
        "searched_as": result["searched_as"],
    })
