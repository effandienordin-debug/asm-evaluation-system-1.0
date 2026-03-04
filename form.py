import streamlit as st
import pandas as pd
import os
from datetime import datetime
from sqlalchemy import text

# --- Configuration & Credentials ---
# Replace with your actual Supabase Project URL
SUPABASE_URL = "https://your-project-id.supabase.co"
BUCKET_NAME = "evaluator-photos"

CRITERIA = [
    ('Strategic Alignment', 0.25), ('Potential Impact', 0.20), 
    ('Feasibility', 0.15), ('Budget Justification', 0.15), 
    ('Timeline Readiness', 0.10), ('Execution Strategy', 0.15)
]

st.set_page_config(page_title="ASM Evaluator Entry", layout="centered")

# --- Database Connection ---
conn = st.connection("postgresql", type="sql")

# --- Helper Functions (Cloud Based) ---
def get_cloud_list(table, column):
    df = conn.query(f"SELECT {column} FROM {table} ORDER BY {column} ASC;", ttl=0)
    return df[column].tolist() if not df.empty else []

EVALUATORS = get_cloud_list("evaluators", "name")
PROPOSALS = get_cloud_list("proposals", "title")

# --- User Identification ---
user_id = st.query_params.get("user")
if user_id is None or not EVALUATORS:
    st.warning("⚠️ Access Denied. Please use your personalized link.")
    st.stop()

try:
    current_user = EVALUATORS[int(user_id)]
except:
    st.error("Invalid User ID.")
    st.stop()

# --- Header with Supabase Photo ---
col_img, col_txt = st.columns([1, 4])
with col_img:
    # Construct the Public URL for the photo
    img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{current_user.replace(' ', '_')}.png"
    # Display image; fall back to professional initials if image fails to load
    st.markdown(f"""
        <img src="{img_url}" style="width:100px; height:100px; border-radius:50%; object-fit:cover;" 
        onerror="this.src='https://ui-avatars.com/api/?name={current_user}&background=random&size=128'">
    """, unsafe_allow_html=True)

with col_txt:
    st.title(f"Welcome, {current_user}")
    st.write("ASM Official Evaluation Portal")

selected_proposal = st.selectbox("Select Proposal Title", ["-- Select --"] + PROPOSALS)

if selected_proposal != "-- Select --":
    # --- LOAD EXISTING DATA FROM CLOUD ---
    query = text("SELECT * FROM scores WHERE evaluator = :ev AND proposal_title = :prop LIMIT 1;")
    df_match = conn.query(query, params={"ev": current_user, "prop": selected_proposal}, ttl="0s")
    existing_data = df_match.iloc[0] if not df_match.empty else None

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
            inputs = {}
            
            for name, weight in CRITERIA:
                # Match database column names (lowercase, underscores)
                col_name = name.lower().replace(" ", "_")
                d_val = float(existing_data[col_name]) if (existing_data is not None) else 0.0
                inputs[name] = st.number_input(f"{name} ({int(weight*100)}%)", 0.0, 5.0, d_val, 0.1)
            
            d_comm = str(existing_data['comments']) if (existing_data is not None) else ""
            user_comments = st.text_area("Comments / Remarks", value=d_comm, placeholder="Enter any notes here...")
            
            # --- Non-mandatory Recommendation Logic ---
            rec_options = ["Pending", "Approve", "Revise", "Reject"]
            existing_rec = existing_data['recommendation'] if (existing_data is not None) else "Pending"
            
            try:
                rec_idx = rec_options.index(existing_rec)
            except ValueError:
                rec_idx = 0
                
            recom = st.radio("Recommendation", rec_options, index=rec_idx, horizontal=True)
            
            if st.form_submit_button("📤 Submit Evaluation", use_container_width=True, type="primary"):
                # --- CALCULATION LOGIC (Proportional Weighting) ---
                weighted_sum = 0
                total_weight_used = 0
                
                for name, weight in CRITERIA:
                    score = inputs[name]
                    if score > 0: 
                        weighted_sum += (score * weight)
                        total_weight_used += weight
                
                # Normalize based on used weights
                final_total = round(weighted_sum / total_weight_used, 2) if total_weight_used > 0 else 0.0

                # --- CLOUD SAVE LOGIC (PostgreSQL) ---
                with conn.session as s:
                    sql = text("""
                        INSERT INTO scores (
                            evaluator, proposal_title, strategic_alignment, potential_impact, 
                            feasibility, budget_justification, timeline_readiness, 
                            execution_strategy, total, recommendation, comments, last_updated
                        )
                        VALUES (:ev, :prop, :s1, :s2, :s3, :s4, :s5, :s6, :tot, :rec, :comm, :ts)
                        ON CONFLICT (evaluator, proposal_title) DO UPDATE SET
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
                    """)
                    
                    s.execute(sql, {
                        "ev": current_user, "prop": selected_proposal,
                        "s1": inputs['Strategic Alignment'], "s2": inputs['Potential Impact'],
                        "s3": inputs['Feasibility'], "s4": inputs['Budget Justification'],
                        "s5": inputs['Timeline Readiness'], "s6": inputs['Execution Strategy'],
                        "tot": final_total, "rec": recom, "comm": user_comments, "ts": datetime.now()
                    })
                    s.commit()
                
                st.session_state.is_editing = False
                st.balloons()
                st.success("🎉 Submission Successful!")
                st.rerun()

else:
    st.info("Please select a proposal title to begin.")
