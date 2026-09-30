"""Streamlit hello page for the scaffold."""

import streamlit as st

from ui import strings

st.set_page_config(page_title=strings.PAGE_TITLE)
st.title(strings.PAGE_TITLE)
st.write(strings.PAGE_HEADING)
