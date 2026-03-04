import streamlit as st
import pandas as pd
from datetime import datetime

# --- Configuration ---
CRITERIA = [
    ('Strategic Alignment', 0.25), ('Potential Impact', 0.20), 
    ('Feasibility', 0.15), ('Budget Justification', 0.15), 
    ('Timeline Readiness', 0.10), ('Execution Strategy', 0.15)
]

st.set_page_config(page_title="ASM Evaluator Entry", layout="centered")

# --- Database Connection ---
# This looks for [connections.postgresql] in your Streamlit Secrets (TOML)
conn = st.connection("postgresql", type="sql")

# --- Fetch Lists from SQL ---
def get_cloud_list(table, column):
    try:
        df = conn.query(f"SELECT {column} FROM {table} ORDER BY {column} ASC;", ttl="2s")
        return df[column].tolist()
    except:
        return []

EVALUATORS = get_cloud_list("evaluators", "name")
PROPOSALS = get_cloud_list("proposals", "title")

# --- User Identification via URL ---
user_id = st.query_params.get("user")
if user_id is None or not EVALUATORS:
    st.warning("⚠️ Access Denied. Please use your personalized link.")
    st.stop()

try:
    current_user = EVALUATORS[int(user_id)]
except:
    st.error("Invalid User ID.")
    st.stop()

st.title(f"👤 {current_user}")

selected_proposal = st.selectbox("Select Proposal Title", ["-- Select --"] + PROPOSALS)

if selected_proposal != "-- Select --":
    # --- LOAD EXISTING DATA FROM SQL ---
    existing_data = None
    query = "SELECT * FROM scores WHERE evaluator = :ev AND proposal_title = :prop LIMIT 1;"
    df_match = conn.query(query, params={"ev": current_user, "prop": selected_proposal}, ttl="0s")
    
    if not df_match.empty:
        existing_data = df_match.iloc[0]

    if "is_editing" not in st.session_state:
        st.session_state.is_editing = False

    # --- VIEW MODE ---
    if existing_data is not None and not st.session_state.is_editing:
        st.success(f"✅ Record found for: {selected_proposal}")
        st.metric("Your Total Score", f"{existing_data['total']} / 5.0")
        if st.button("✏️ Edit Scores", use_container_width=True):
            st.session_state.is_editing = True
            st.rerun()
            
    # --- FORM / EDIT MODE ---
    else:
        with st.form("evaluation_form", clear_on_submit=True):
            st.info("ℹ️ **Flexible Scoring**: If a criterion is not applicable, you may leave it at 0.0.")
            new_scores = {}
            for name, weight in CRITERIA:
                # SQL column names are usually lowercase. Adjust if your DB uses caps.
                col_name = name.lower().replace(" ", "_")
                d_val = float(existing_data[name]) if (existing_data is not None) else 0.0
                val = st.number_input(f"{name} ({int(weight*100)}%)", 0.0, 5.0, d_val, 0.1)
                new_scores[name] = val
            
            d_comm = str(existing_data['comments']) if (existing_data is not None) else ""
            user_comments = st.text_area("Comments / Remarks", value=d_comm)
            
            d_recom = existing_data['recommendation'] if (existing_data is not None) else "Approve"
            recom = st.radio("Recommendation", ["Approve", "Revise", "Reject"], 
                             index=["Approve", "Revise", "Reject"].index(d_recom), horizontal=True)
            
            if st.form_submit_button("📤 Submit Evaluation", use_container_width=True):
                # --- CALCULATION LOGIC ---
                weighted_sum = 0
                total_weight_used = 0
                for name, weight in CRITERIA:
                    score = new_scores[name]
                    if score > 0: 
                        weighted_sum += (score * weight)
                        total_weight_used += weight
                
                final_total = round(weighted_sum / total_weight_used, 2) if total_weight_used > 0 else 0.0
                ts = datetime.now()

                # --- SQL SAVE (UPSERT) ---
                # This uses "ON CONFLICT" to update the score if it already exists
                with conn.session as s:
                    sql = """
                        INSERT INTO scores (
                            evaluator, proposal_title, 
                            strategic_alignment, potential_impact, feasibility, 
                            budget_justification, timeline_readiness, execution_strategy,
                            total, recommendation, comments, last_updated
                        ) VALUES (
                            :ev, :prop, :s1, :s2, :s3, :s4, :s5, :s6, :tot, :rec, :comm, :ts
                        )
                        ON CONFLICT (evaluator, proposal_title) 
                        DO UPDATE SET 
                            strategic_alignment = EXCLUDED.strategic_alignment,
                            potential_impact = EXCLUDED.potential_impact,
                            feasibility = EXCLUDED.feasibility,
                            budget_justification = EXCLUDED.budget_justification,
                            timeline_readiness = EXCLUDED.timeline_readiness,
                            execution_strategy = EXCLUDED.execution_strategy,
                            total = EXCLUDED.total,
                            recommendation = EXCLUDED.recommendation,
                            comments = EXCLUDED.comments,
                            last_updated = EXCLUDED.last_updated;
                    """
                    params = {
                        "ev": current_user, "prop": selected_proposal,
                        "s1": new_scores['Strategic Alignment'], "s2": new_scores['Potential Impact'],
                        "s3": new_scores['Feasibility'], "s4": new_scores['Budget Justification'],
                        "s5": new_scores['Timeline Readiness'], "s6": new_scores['Execution Strategy'],
                        "tot": final_total, "rec": recom, "comm": user_comments, "ts": ts
                    }
                    s.execute(sql, params)
                    s.commit()

                st.session_state.is_editing = False
                st.success("🎉 Submission Saved to Database!")
                st.rerun()
else:
    st.info("Please select a proposal title to begin.")
