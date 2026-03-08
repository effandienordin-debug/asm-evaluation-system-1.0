import streamlit as st

import pandas as pd

import time

import re

from datetime import datetime

from sqlalchemy import text

from streamlit_autorefresh import st_autorefresh



# --- 1. CONFIGURATION ---

SUPABASE_URL = st.secrets["supabase_url"]

BUCKET_NAME = "evaluator-photos"



CRITERIA = [

('Strategic Alignment', 0.25), ('Potential Impact', 0.20),

('Feasibility', 0.15), ('Budget Justification', 0.15),

('Timeline Readiness', 0.10), ('Execution Strategy', 0.15)

]



st.set_page_config(page_title="ASM Evaluator Entry", layout="wide")

conn = st.connection("postgresql", type="sql")



# --- 2. SESSION STATE ---

if "current_user" not in st.session_state:

st.session_state["current_user"] = None

if "user_email" not in st.session_state:

st.session_state["user_email"] = None



# --- 3. ACCESS CONTROL SCREEN (Dual Column Lookup) ---

if not st.session_state["user_email"]:

st.title("🛡️ ASM Evaluator Access")

st.markdown("### Identify yourself to access the evaluation portal.")


input_email = st.text_input("Enter Registered Email", placeholder="name@organization.com").lower().strip()


if st.button("Access System", type="primary", use_container_width=True):

if input_email:

# Query DB to check if email exists in EITHER sso_email OR email columns

user_check = conn.query(

"""

SELECT name FROM evaluators

WHERE LOWER(sso_email) = :e

OR LOWER(email) = :e

LIMIT 1

""",

params={"e": input_email}, ttl=0

)


if not user_check.empty:

# Success: Capture the display name and the email used

st.session_state["user_email"] = input_email

st.session_state["current_user"] = user_check.iloc[0]['name']

st.success(f"Verified! Welcome, {st.session_state['current_user']}.")

time.sleep(1)

st.rerun()

else:

st.error("❌ Access Denied: This email is not found in our records.")

else:

st.warning("⚠️ Please enter an email address.")


st.divider()

st.caption("Authorized Use Only. System access is monitored.")

st.stop()

Use Control + Shift + m to toggle the tab key moving focus. Alternatively, use esc then tab to move to the next interactive element on the page.
