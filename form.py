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
    input_email = st.text_input("Enter Registered Email", placeholder="name@organization.com").lower().strip()
    
    if st.button("Access System", type="primary", use_container_width=True):
        if input_email:
            user_check = conn.query(
                "SELECT name FROM evaluators WHERE LOWER(sso_email) = :e OR LOWER(email) = :e LIMIT 1", 
                params={"e": input_email}, ttl=0
            )
            if not user_check.empty:
                st.session_state["user_email"] = input_email
                st.session_state["current_user"] = user_check.iloc[0]['name']
                st.rerun()
            else:
                st.error("❌ Access Denied: Email not found.")
    st.stop() 

# --- 4. MAIN NAVIGATION ---
evaluator_name = st.session_state["current_user"]

if not st.session_state["selected_proposal"]:
    st.title(f"👋 Welcome, {evaluator_name}")
    
    with st.container():
        st.markdown(f"""
        ### 📋 About the ASM Evaluation Portal
        This system is designed for evaluators to review and score project proposals systematically. 
        
        **How to use this page:**
        1. **Review Assignments:** See proposals assigned to you below.
        2. **Evaluate:** Click **'Evaluate'** to start or **'Edit Review'** to update.
        3. **Scoring:** Provide scores (**0.0 - 5.0**).
        """)
        
        with st.expander("🔍 View Scoring Criteria Details"):
            cols = st.columns(3)
            for i, (label, weight) in enumerate(CRITERIA):
                with cols[i % 3]:
                    st.write(f"**{label}**")
                    st.caption(f"Weight: {int(weight*100)}%")
    
    st.divider()
    st.subheader("Your Assigned Proposals")
    
    proposals = conn.query("SELECT title FROM proposals ORDER BY title ASC;", ttl=0)
    existing_scores = conn.query(
        "SELECT proposal_title FROM scores WHERE evaluator = :name", 
        params={"name": evaluator_name}, ttl=0
    )
    done_proposals = existing_scores['proposal_title'].tolist() if not existing_scores.empty else []

    for _, row in proposals.iterrows():
        title = row['title']
        col1, col2, col3 = st.columns([0.6, 0.2, 0.2])
        col1.write(f"**📄 {title}**")
        
        if title in done_proposals:
            col2.markdown(":green[✅ Completed]")
            if col3.button("Edit Review", key=f"edit_{title}", use_container_width=True):
                st.session_state["selected_proposal"] = title
                st.rerun()
        else:
            col2.markdown(":blue[📝 Pending]")
            if col3.button("Evaluate", key=f"eval_{title}", type="primary", use_container_width=True):
                st.session_state["selected_proposal"] = title
                st.rerun()
        st.divider()
    
    if st.button("Logout"):
        st.session_state.clear()
        st.rerun()
    st.stop()

# --- 5. EVALUATION FORM ---
proposal_title = st.session_state["selected_proposal"]
st.title("Evaluation Form")
st.info(f"**Project:** {proposal_title}")

existing_data = conn.query(
    "SELECT * FROM scores WHERE evaluator = :e AND proposal_title = :p",
    params={"e": evaluator_name, "p": proposal_title}, ttl=0
)

if st.button("⬅️ Cancel and Return to List"):
    st.session_state["selected_proposal"] = None
    st.rerun()

with st.form("evaluation_form"):
    st.markdown("### Scoring (0.0 - 5.0)")
    scores = {}
    
    grid_cols = st.columns(2)
    for i, (label, weight) in enumerate(CRITERIA):
        db_col = label.lower().replace(' ', '_')
        default_val = 3.0
        if not existing_data.empty and db_col in existing_data.columns:
            default_val = float(existing_data.iloc[0][db_col])
        
        with grid_cols[i % 2]:
            scores[label] = st.number_input(
                f"{label} (Weight: {int(weight*100)}%)", 
                min_value=0.0, max_value=5.0, value=default_val, 
                step=0.1, format="%.1f"
            )
    
    st.divider()
    
    # --- MULTI-SELECT RECOMMENDATION LOGIC ---
    rec_choices = ["Approve", "Revise", "Reject", "Combined/Merge"]
    default_recs = []
    
    if not existing_data.empty:
        raw_rec = existing_data.iloc[0]['recommendation']
        if raw_rec:
            saved_recs = [r.strip() for r in str(raw_rec).split(",")]
            default_recs = [r for r in saved_recs if r in rec_choices]

    recommendation_list = st.multiselect(
        "Overall Recommendation (Select one or more)", 
        rec_choices, 
        default=default_recs
    )
    
    comm_val = existing_data.iloc[0]['comments'] if not existing_data.empty else ""
    comments = st.text_area("Justification/Comments", value=comm_val, height=150)
    
    submit = st.form_submit_button("Save Evaluation", type="primary")

if submit:
    if not comments.strip():
        st.error("⚠️ Please provide justification comments.")
    elif not recommendation_list:
        st.error("⚠️ Please select at least one recommendation.")
    else:
        recommendation_str = ", ".join(recommendation_list)
        total_score = sum(scores[label] * weight for label, weight in CRITERIA)
        
        with conn.session as s:
            s.execute(text("DELETE FROM scores WHERE evaluator = :e AND proposal_title = :p"), 
                      {"e": evaluator_name, "p": proposal_title})
            s.execute(text("""
                INSERT INTO scores (evaluator, proposal_title, strategic_alignment, potential_impact, 
                feasibility, budget_justification, timeline_readiness, execution_strategy, total, recommendation, comments)
                VALUES (:eval, :prop, :s1, :s2, :s3, :s4, :s5, :s6, :tot, :rec, :comm)
            """), {
                "eval": evaluator_name, "prop": proposal_title,
                "s1": scores['Strategic Alignment'], "s2": scores['Potential Impact'],
                "s3": scores['Feasibility'], "s4": scores['Budget Justification'],
                "s5": scores['Timeline Readiness'], "s6": scores['Execution Strategy'],
                "tot": total_score, "rec": recommendation_str, "comm": comments
            })
            s.commit()
        
        st.success("✅ Evaluation Saved Successfully!")
        time.sleep(1)
        st.session_state["selected_proposal"] = None
        st.rerun()
