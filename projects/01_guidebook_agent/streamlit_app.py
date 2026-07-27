import fitz
import streamlit as st

from ask import PDF_PATH, answer, extract_pages, load_sections, route

st.set_page_config(page_title="HR Handbook Agent", page_icon="📖")
st.title("HR & Policy Guidebook Agent")
st.caption("Ask a question about the Las Vegas employee handbook.")


@st.cache_resource
def get_sections():
    doc = fitz.open(PDF_PATH)
    page_count = doc.page_count
    doc.close()
    return load_sections(page_count)


sections = get_sections()

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
            subjects, unmatched = route(question, sections)

            if not subjects:
                reply = "No matching section found in the table of contents."
            else:
                by_subject = {s["subject"]: s for s in sections}
                matched = [by_subject[subj] for subj in subjects]
                routed_line = "**Routed to:** " + ", ".join(
                    f"{s['subject']} (pages {s['start']}-{s['end']})" for s in matched
                )
                sections_with_text = [
                    {**s, "text": extract_pages(s["start"], s["end"])} for s in matched
                ]
                reply = f"{routed_line}\n\n{answer(question, sections_with_text)}"

            if unmatched:
                reply += f"\n\n*(ignored unmatched router output: {unmatched!r})*"

        st.markdown(reply)
    st.session_state.messages.append({"role": "assistant", "content": reply})
