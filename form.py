import streamlit as st
import pandas as pd
import os
from datetime import datetime
from sqlalchemy import text

# --- Config ---
CRITERIA = [
    ('Strategic Alignment', 0.25), ('Potential Impact', 0.20), 
    ('Feasibility', 0.15), ('Budget Justification', 0.15), 
    ('Timeline Readiness', 0.10), ('Execution Strategy', 0.15)
]
UPLOAD_DIR = "evaluator_photos"

st.set_page_config(page_title="ASM Evaluation Form", layout="centered")
conn = st.connection("postgresql", type="sql")

# --- Helper ---
def get_cloud_list(table, column):
    df = conn.query(f"SELECT {column} FROM {table} ORDER BY {column} ASC;", ttl=0)
    return df[column].tolist() if not df.empty else []

EVALUATORS = get_cloud_list("evaluators", "name")
PROPOSALS = get_cloud_list("proposals", "title")

# --- Auth ---
user_id = st.query_params.get("user")
if user_id is None or not EVALUATORS:
    st.warning("⚠️ Please use your official link.")
    st.stop()

try:
    current_user = EVALUATORS[int(user_id)]
except:
    st.error("Invalid link.")
    st.stop()

# --- Header with Photo ---
col1, col2 = st.columns([1, 4])
with col1:
    photo_path = os.path.join(UPLOAD_DIR, f"{current_user.replace(' ', '_')}.png")
    if os.path.exists(photo_path):
        st.image(photo_path, width=100)
    else:
        st.image(f"https://ui-avatars.com/api/?name={current_user}&background=random&size=128", width=100)

with col2:
    st.title(f"Welcome, {current_user}")
    st.write("ASM Official Evaluation Portal")

selected_prop = st.selectbox("Select Proposal to Evaluate", ["-- Select --"] + PROPOSALS)

if selected_prop != "-- Select --":
    query = text("SELECT * FROM scores WHERE evaluator = :ev AND proposal_title = :prop LIMIT 1;")
    df_match = conn.query(query, params={"ev": current_user, "prop": selected_prop}, ttl="0s")
    existing_data = df_match.iloc[0] if not df_match.empty else None

    with st.form("eval_form"):
        st.subheader(f"Reviewing: {selected_prop}")
        inputs = {}
        for name, weight in CRITERIA:
            col = name.lower().replace(" ", "_")
            val = float(existing_data[col]) if existing_data is not None else 0.0
            inputs[name] = st.number_input(f"{name} ({int(weight*100)}%)", 0.0, 5.0, val, 0.1)

        comments = st.text_area("Comments", value=str(existing_data['comments']) if existing_data is not None else "")
        
        rec_options = ["Pending", "Approve", "Revise", "Reject"]
        existing_rec = existing_data['recommendation'] if existing_data is not None else "Pending"
        rec_idx = rec_options.index(existing_rec) if existing_rec in rec_options else 0
        
        recom = st.radio("Recommendation", rec_options, index=rec_idx, horizontal=True)

        if st.form_submit_button("Submit Evaluation", type="primary", use_container_width=True):
            total = sum([inputs[n] * w for n, w in CRITERIA])
            with conn.session as s:
                sql = text("""
                    INSERT INTO scores (evaluator, proposal_title, strategic_alignment, potential_impact, 
                                        feasibility, budget_justification, timeline_readiness, 
                                        execution_strategy, total, recommendation, comments, last_updated)
                    VALUES (:ev, :prop, :s1, :s2, :s3, :s4, :s5, :s6, :tot, :rec, :comm, :ts)
                    ON CONFLICT (evaluator, proposal_title) DO UPDATE SET
                        strategic_alignment=EXCLUDED.strategic_alignment, potential_impact=EXCLUDED.potential_impact,
                        feasibility=EXCLUDED.feasibility, budget_justification=EXCLUDED.budget_justification,
                        timeline_readiness=EXCLUDED.timeline_readiness, execution_strategy=EXCLUDED.execution_strategy,
                        total=EXCLUDED.total, recommendation=EXCLUDED.recommendation, comments=EXCLUDED.comments,
                        last_updated=EXCLUDED.last_updated;
                """)
                s.execute(sql, {
                    "ev": current_user, "prop": selected_prop,
                    "s1": inputs['Strategic Alignment'], "s2": inputs['Potential Impact'],
                    "s3": inputs['Feasibility'], "s4": inputs['Budget Justification'],
                    "s5": inputs['Timeline Readiness'], "s6": inputs['Execution Strategy'],
                    "tot": round(total, 2), "rec": recom, "comm": comments, "ts": datetime.now()
                })
                s.commit()
            st.balloons()
            st.success("✅ Submission Successful!")
