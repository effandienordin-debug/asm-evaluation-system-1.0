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
if "selected_proposal" not in st.session_state:
    st.session_state["selected_proposal"] = None

# --- 3. ACCESS CONTROL SCREEN ---
if not st.session_state["user_email"]:
    st.title("🛡️ ASM Evaluator Access")
    st.markdown("### Identify yourself to access the evaluation portal.")
    
    input_email = st.text_input("Enter Registered Email", placeholder="name@organization.com").lower().strip()
    
    if st.button("Access System", type="primary", use_container_width=True):
        if input_email:
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

# --- 4. MAIN NAVIGATION / SELECTION ---
evaluator_name = st.session_state["current_user"]

# If no proposal is selected, show the list
if not st.session_state["selected_proposal"]:
    st.title(f"Welcome, {evaluator_name}")
    st.subheader("Select a Proposal to Evaluate")
    
    proposals = conn.query("SELECT title FROM proposals ORDER BY title ASC;", ttl=0)
    existing_scores = conn.query(
        "SELECT proposal_title FROM scores WHERE evaluator = :name", 
        params={"name": evaluator_name}, ttl=0
    )
    done_proposals = existing_scores['proposal_title'].tolist() if not existing_scores.empty else []

    for _, row in proposals.iterrows():
        title = row['title']
        col1, col2 = st.columns([0.8, 0.2])
        col1.write(f"📄 {title}")
        if title in done_proposals:
            if col2.button("Edit", key=f"edit_{title}"):
                st.session_state["selected_proposal"] = title
                st.rerun()
        else:
            if col2.button("Evaluate", key=f"eval_{title}", type="primary"):
                st.session_state["selected_proposal"] = title
                st.rerun()
    
    if st.button("Logout"):
        st.session_state.clear()
        st.rerun()
    st.stop()

# --- 5. EVALUATION FORM ---
proposal_title = st.session_state["selected_proposal"]
st.title(f"Evaluating: {proposal_title}")

# Load existing data if editing
existing_data = conn.query(
    "SELECT * FROM scores WHERE evaluator = :e AND proposal_title = :p",
    params={"e": evaluator_name, "p": proposal_title}, ttl=0
)

with st.form("evaluation_form"):
    scores = {}
    for label, weight in CRITERIA:
        default_val = float(existing_data.iloc[0][label.lower().replace(' ', '_')]) if not existing_data.empty else 3.0
        scores[label] = st.slider(f"{label} (Weight: {int(weight*100)}%)", 1.0, 5.0, default_val, 0.5)
    
    rec_default = existing_data.iloc[0]['recommendation'] if not existing_data.empty else "Highly Recommended"
    comm_default = existing_data.iloc[0]['comments'] if not existing_data.empty else ""
    
    recommendation = st.selectbox("Overall Recommendation", ["Highly Recommended", "Recommended", "Recommended with Revisions", "Not Recommended"], index=["Highly Recommended", "Recommended", "Recommended with Revisions", "Not Recommended"].index(rec_default))
    comments = st.text_area("Justification/Comments", value=comm_default, placeholder="Provide your reasoning here...", height=150)
    
    col_save, col_cancel = st.columns([0.2, 0.8])
    submit = col_save.form_submit_button("Save Evaluation", type="primary")
    cancel = col_cancel.form_submit_button("Cancel")

# Handle Cancel
if cancel:
    st.session_state["selected_proposal"] = None
    st.rerun()

# Handle Save
if submit:
    total_score = sum(scores[label] * weight for label, weight in CRITERIA)
    
    with conn.session as s:
        # Delete existing to handle update/insert cleanly
        s.execute(text("DELETE FROM scores WHERE evaluator = :e AND proposal_title = :p"), {"e": evaluator_name, "p": proposal_title})
        
        # Insert new scores
        s.execute(text("""
            INSERT INTO scores (
                evaluator, proposal_title, strategic_alignment, potential_impact, 
                feasibility, budget_justification, timeline_readiness, execution_strategy, 
                total, recommendation, comments
            ) VALUES (
                :eval, :prop, :s1, :s2, :s3, :s4, :s5, :s6, :tot, :rec, :comm
            )
        """), {
            "eval": evaluator_name, "prop": proposal_title,
            "s1": scores['Strategic Alignment'], "s2": scores['Potential Impact'],
            "s3": scores['Feasibility'], "s4": scores['Budget Justification'],
            "s5": scores['Timeline Readiness'], "s6": scores['Execution Strategy'],
            "tot": total_score, "rec": recommendation, "comm": comments
        })
        s.commit()
    
    st.success("✅ Evaluation Saved Successfully!")
    time.sleep(1)
    
    # Return to main page by clearing selected proposal
    st.session_state["selected_proposal"] = None
    st.rerun()
