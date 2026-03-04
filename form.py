import streamlit as st
import pandas as pd
from datetime import datetime
from sqlalchemy import text

# --- Config ---
CRITERIA = [
    ('Strategic Alignment', 0.25), ('Potential Impact', 0.20), 
    ('Feasibility', 0.15), ('Budget Justification', 0.15), 
    ('Timeline Readiness', 0.10), ('Execution Strategy', 0.15)
]

st.set_page_config(page_title="ASM Evaluation Form", layout="centered")
conn = st.connection("postgresql", type="sql")

# --- Get Lists ---
def get_cloud_list(table, column):
    df = conn.query(f"SELECT {column} FROM {table} ORDER BY {column} ASC;", ttl="5s")
    return df[column].tolist() if not df.empty else []

EVALUATORS = get_cloud_list("evaluators", "name")
PROPOSALS = get_cloud_list("proposals", "title")

# --- Auth ---
user_id = st.query_params.get("user")
if user_id is None or not EVALUATORS:
    st.warning("⚠️ Please use your official link.")
    st.stop()

current_user = EVALUATORS[int(user_id)]
st.title(f"👤 {current_user}")

selected_prop = st.selectbox("Select Proposal", ["-- Select --"] + PROPOSALS)

if selected_prop != "-- Select --":
    # Check for existing score
    query = text("SELECT * FROM scores WHERE evaluator = :ev AND proposal_title = :prop LIMIT 1;")
    df_match = conn.query(query, params={"ev": current_user, "prop": selected_prop}, ttl="0s")
    existing_data = df_match.iloc[0] if not df_match.empty else None

    with st.form("eval_form"):
        st.info("Score from 0.0 to 5.0")
        inputs = {}
        for name, weight in CRITERIA:
            # Match database column names (lowercase, underscores)
            col = name.lower().replace(" ", "_")
            val = float(existing_data[col]) if existing_data is not None else 0.0
            inputs[name] = st.number_input(f"{name} ({int(weight*100)}%)", 0.0, 5.0, val, 0.1)

        comments = st.text_area("Comments", value=str(existing_data['comments']) if existing_data is not None else "")
        recom = st.radio("Result", ["Approve", "Revise", "Reject"], horizontal=True)

        if st.form_submit_button("Submit Evaluation"):
            total = sum([inputs[n] * w for n, w in CRITERIA])
            
            with conn.session as s:
                sql = text("""
                    INSERT INTO scores (evaluator, proposal_title, strategic_alignment, potential_impact, 
                                        feasibility, budget_justification, timeline_readiness, 
                                        execution_strategy, total, recommendation, comments, last_updated)
                    VALUES (:ev, :prop, :s1, :s2, :s3, :s4, :s5, :s6, :tot, :rec, :comm, :ts)
                    ON CONFLICT (evaluator, proposal_title) DO UPDATE SET
                    total = EXCLUDED.total, last_updated = EXCLUDED.last_updated, comments = EXCLUDED.comments;
                """)
                s.execute(sql, {
                    "ev": current_user, "prop": selected_prop,
                    "s1": inputs['Strategic Alignment'], "s2": inputs['Potential Impact'],
                    "s3": inputs['Feasibility'], "s4": inputs['Budget Justification'],
                    "s5": inputs['Timeline Readiness'], "s6": inputs['Execution Strategy'],
                    "tot": round(total, 2), "rec": recom, "comm": comments, "ts": datetime.now()
                })
                s.commit()
            st.success("✅ Evaluation Saved!")
