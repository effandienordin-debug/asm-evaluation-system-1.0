import streamlit as st
import pandas as pd
import time
from datetime import datetime
from sqlalchemy import text

# --- 1. CONFIG ---
CRITERIA = [
    ('Strategic Alignment', 0.25), ('Potential Impact', 0.20), 
    ('Feasibility', 0.15), ('Budget Justification', 0.15), 
    ('Timeline Readiness', 0.10), ('Execution Strategy', 0.15)
]
st.set_page_config(page_title="ASM Evaluator Entry", layout="wide")
conn = st.connection("postgresql", type="sql")

# Session State
if "current_user" not in st.session_state: st.session_state["current_user"] = None
if "user_email" not in st.session_state: st.session_state["user_email"] = None
if "selected_proposal" not in st.session_state: st.session_state["selected_proposal"] = None

# --- 2. LOGIN ---
if not st.session_state["user_email"]:
    st.title("🛡️ Evaluator Access")
    email = st.text_input("Registered Email").lower().strip()
    if st.button("Access"):
        user = conn.query("SELECT name FROM evaluators WHERE LOWER(email) = :e OR LOWER(sso_email) = :e", params={"e": email}, ttl=0)
        if not user.empty:
            st.session_state["user_email"], st.session_state["current_user"] = email, user.iloc[0]['name']
            st.rerun()
    st.stop()

evaluator_name = st.session_state["current_user"]

# --- 3. FILTERED PROPOSAL LIST ---
if not st.session_state["selected_proposal"]:
    st.title(f"👋 Welcome, {evaluator_name}")
    st.subheader("Your Assigned Applicants")

    # Only load proposals assigned to THIS specific evaluator
    assigned_proposals = conn.query("""
        SELECT p.title 
        FROM proposals p
        JOIN applicant_assignments a ON p.title = a.applicant_name
        WHERE a.evaluator_name = :name
        ORDER BY p.title ASC
    """, params={"name": evaluator_name}, ttl=0)

    done_proposals = conn.query("SELECT proposal_title FROM scores WHERE evaluator = :n", params={"n": evaluator_name}, ttl=0)['proposal_title'].tolist() if not assigned_proposals.empty else []

    if assigned_proposals.empty:
        st.warning("No applicants have been assigned to you yet.")
    else:
        for _, row in assigned_proposals.iterrows():
            title = row['title']
            c1, c2, c3 = st.columns([0.6, 0.2, 0.2])
            c1.write(f"**📄 {title}**")
            status = ":green[✅ Done]" if title in done_proposals else ":blue[📝 Pending]"
            c2.markdown(status)
            label = "Edit Review" if title in done_proposals else "Evaluate"
            if c3.button(label, key=f"btn_{title}"):
                st.session_state["selected_proposal"] = title
                st.rerun()
    
    if st.button("Logout"): st.session_state.clear(); st.rerun()
    st.stop()

# --- 4. FORM (Remains same as your original provided code) ---
# ... [Evaluation Form Logic] ...
