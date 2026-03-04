import streamlit as st
import pandas as pd
from datetime import datetime
from sqlalchemy import text
from streamlit_autorefresh import st_autorefresh

# --- 1. CONFIGURATION ---
SUPABASE_URL = "https://qizxricvzsnsfjibfmxw.supabase.co"
BUCKET_NAME = "evaluator-photos"

CRITERIA = [
    ('Strategic Alignment', 0.25), ('Potential Impact', 0.20), 
    ('Feasibility', 0.15), ('Budget Justification', 0.15), 
    ('Timeline Readiness', 0.10), ('Execution Strategy', 0.15)
]

st.set_page_config(page_title="ASM Evaluator Entry", layout="centered")

# --- 2. DATABASE CONNECTION ---
conn = st.connection("postgresql", type="sql")

# --- 3. HELPER FUNCTIONS ---
def get_cloud_list(table, column):
    try:
        df = conn.query(f"SELECT {column} FROM {table} ORDER BY {column} ASC;", ttl=0)
        return df[column].tolist() if not df.empty else []
    except:
        return []

EVALUATORS = get_cloud_list("evaluators", "name")
PROPOSALS = get_cloud_list("proposals", "title")

# --- 4. USER IDENTIFICATION ---
user_id = st.query_params.get("user")
if user_id is None or not EVALUATORS:
    st.warning("⚠️ Access Denied. Please use your personalized link.")
    st.stop()

try:
    current_user = EVALUATORS[int(user_id)]
except:
    st.error("Invalid User ID.")
    st.stop()

# --- 5. AUTO-REFRESH (Optional/Safe) ---
# We use a key to ensure this refresh doesn't break the form state
st_autorefresh(interval=60000, key="form_stay_alive") 

# --- 6. HEADER WITH PHOTO ---
# 1. Create a unique timestamp to force the browser to refresh the image
cache_buster = int(datetime.now().timestamp())

col_img, col_txt = st.columns([1, 4])
with col_img:
    # 2. Add ?t={cache_buster} to the end of the URL
    clean_name = current_user.replace(' ', '_')
    img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{clean_name}.png?t={cache_buster}"
    
    st.markdown(f"""
        <img src="{img_url}" style="width:100px; height:100px; border-radius:50%; object-fit:cover; border: 2px solid #E2E8F0;" 
        onerror="this.src='https://ui-avatars.com/api/?name={current_user}&background=random&size=128'">
    """, unsafe_allow_html=True)

with col_txt:
    st.title(f"Welcome, {current_user}")
    st.write("Official ASM Evaluation Portal")

selected_proposal = st.selectbox("Select Proposal Title", ["-- Select --"] + PROPOSALS)

if selected_proposal != "-- Select --":
    # LOAD DATA
    query = text("SELECT * FROM scores WHERE evaluator = :ev AND proposal_title = :prop LIMIT 1;")
    df_match = conn.query(query, params={"ev": current_user, "prop": selected_proposal}, ttl="0s")
    existing_data = df_match.iloc[0] if not df_match.empty else None

    if "is_editing" not in st.session_state:
        st.session_state.is_editing = False

    # VIEW MODE
    if existing_data is not None and not st.session_state.is_editing:
        st.success(f"✅ Record found for: {selected_proposal}")
        st.metric("Your Total Score", f"{existing_data['total']} / 5.0")
        if st.button("✏️ Edit Scores", use_container_width=True):
            st.session_state.is_editing = True
            st.rerun()
            
    # FORM MODE
    else:
        # Putting everything in a FORM prevents Auto-Refresh from clearing your typing
        with st.form("evaluation_form", clear_on_submit=False):
            st.info("ℹ️ **Flexible Scoring**: Leave at 0.0 if a criterion is not applicable.")
            inputs = {}
            
            for name, weight in CRITERIA:
                col_db = name.lower().replace(" ", "_")
                d_val = float(existing_data[col_db]) if (existing_data is not None) else 0.0
                inputs[name] = st.number_input(f"{name} ({int(weight*100)}%)", 0.0, 5.0, d_val, 0.1)
            
            d_comm = str(existing_data['comments']) if (existing_data is not None) else ""
            user_comments = st.text_area("Comments / Remarks", value=d_comm)
            
            rec_options = ["Pending", "Approve", "Revise", "Reject"]
            existing_rec = existing_data['recommendation'] if (existing_data is not None) else "Pending"
            rec_idx = rec_options.index(existing_rec) if existing_rec in rec_options else 0
            recom = st.radio("Recommendation", rec_options, index=rec_idx, horizontal=True)
            
            submit = st.form_submit_button("📤 Submit Evaluation", use_container_width=True, type="primary")

            if submit:
                # Proportional Weighting Calculation
                w_sum = 0
                w_used = 0
                for name, weight in CRITERIA:
                    if inputs[name] > 0:
                        w_sum += (inputs[name] * weight)
                        w_used += weight
                
                final_total = round(w_sum / w_used, 2) if w_used > 0 else 0.0

                with conn.session as s:
                    save_query = text("""
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
                    s.execute(save_query, {
                        "ev": current_user, "prop": selected_proposal,
                        "s1": inputs['Strategic Alignment'], "s2": inputs['Potential Impact'],
                        "s3": inputs['Feasibility'], "s4": inputs['Budget Justification'],
                        "s5": inputs['Timeline Readiness'], "s6": inputs['Execution Strategy'],
                        "tot": final_total, "rec": recom, "comm": user_comments, "ts": datetime.now()
                    })
                    s.commit()
                
                st.session_state.is_editing = False
                st.balloons()
                st.rerun()
else:
    st.info("Please select a proposal title to begin.")


