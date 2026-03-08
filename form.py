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

# --- 4. AUTHORIZED APP CONTENT ---
current_user = st.session_state["current_user"]
user_email = st.session_state["user_email"]

st_autorefresh(interval=30000, key="evaluator_heartbeat")

# Sidebar
with st.sidebar:
    st.write(f"**Current Evaluator:**")
    st.subheader(current_user)
    st.caption(user_email)
    st.divider()
    if st.button("🚪 Logout / Switch User", use_container_width=True):
        st.session_state.clear()
        st.rerun()

# --- 5. LOGIC HELPERS ---
def nav_to_summary():
    st.session_state.proposal_selector = "-- Select --"
    st.session_state.is_editing = False

def nav_to_proposal(title):
    st.session_state.proposal_selector = title
    st.session_state.is_editing = False

def get_cloud_list(table, column):
    try:
        df = conn.query(f"SELECT {column} FROM {table} ORDER BY {column} ASC;", ttl=0)
        return df[column].tolist() if not df.empty else []
    except: return []

PROPOSALS = get_cloud_list("proposals", "title")

# --- 6. USER INTERFACE ---
col_img, col_txt = st.columns([1, 4])
with col_img:
    # Avatar detection
    img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{current_user.replace(' ', '_')}.png"
    st.markdown(f'''
        <div style="text-align: center;">
            <img src="{img_url}" style="width:100px; height:100px; border-radius:50%; object-fit:cover; border: 3px solid #1E3A8A;" 
            onerror="this.src='https://ui-avatars.com/api/?name={current_user}&background=random'">
        </div>
    ''', unsafe_allow_html=True)

with col_txt:
    st.title(f"Evaluator Portal")

# Progress Data
try:
    scored_df = conn.query("SELECT proposal_title, total, recommendation, comments FROM scores WHERE evaluator = :ev", params={"ev": current_user}, ttl=0)
    completed_proposals = scored_df['proposal_title'].tolist() if not scored_df.empty else []
except:
    scored_df = pd.DataFrame()
    completed_proposals = []

st.write(f"**Your Progress: {len(completed_proposals)} / {len(PROPOSALS)} Proposals**")
st.progress(len(completed_proposals) / len(PROPOSALS) if PROPOSALS else 0)
st.divider()

# Selection Logic
if "proposal_selector" not in st.session_state:
    st.session_state.proposal_selector = "-- Select --"

selected_proposal = st.selectbox("Choose Proposal", ["-- Select --"] + PROPOSALS, key="proposal_selector")

if selected_proposal != "-- Select --":
    query = "SELECT * FROM scores WHERE evaluator = :ev AND proposal_title = :prop LIMIT 1;"
    df_match = conn.query(query, params={"ev": current_user, "prop": selected_proposal}, ttl=0)
    existing_data = df_match.iloc[0] if not df_match.empty else None

    if "is_editing" not in st.session_state:
        st.session_state.is_editing = False

    if existing_data is not None and not st.session_state.is_editing:
        st.success(f"✅ Submission Received")
        st.metric("Your Total Score", f"{existing_data['total']} / 5.0")
        c1, c2 = st.columns(2)
        if c1.button("✏️ Edit Record", use_container_width=True):
            st.session_state.is_editing = True
            st.rerun()
        c2.button("⬅️ Summary View", use_container_width=True, on_click=nav_to_summary)
    else:
        with st.form("eval_form"):
            st.subheader(f"Evaluation: {selected_proposal}")
            inputs = {}
            for name, weight in CRITERIA:
                col_db = name.lower().replace(" ", "_")
                val = float(existing_data[col_db]) if existing_data is not None else 0.0
                inputs[name] = st.number_input(f"{name} ({int(weight*100)}%)", 0.0, 5.0, val, 0.1)
            
            clean_comm = re.sub(r"\[MERGE WITH:.*?\] ", "", str(existing_data['comments']) if existing_data is not None else "")
            user_comments = st.text_area("Justification", value=clean_comm)
            recom_options = ["Pending", "Approve", "Revise", "Reject", "Combine/Merge"]
            cur_rec = str(existing_data['recommendation']) if existing_data is not None else "Pending"
            recom = st.radio("Recommendation", recom_options, index=recom_options.index(cur_rec) if cur_rec in recom_options else 0, horizontal=True)

            merge_target = None
            if recom == "Combine/Merge":
                other_proposals = [p for p in PROPOSALS if p != selected_proposal]
                merge_target = st.selectbox("Merge with:", other_proposals)

            if st.form_submit_button("📤 Save Evaluation", type="primary"):
                w_sum = sum(inputs[name] * weight for name, weight in CRITERIA)
                final_total = round(w_sum, 2)
                final_comm = f"[MERGE WITH: {merge_target}] {user_comments}" if recom == "Combine/Merge" else user_comments
                with conn.session as s:
                    s.execute(text("""INSERT INTO scores (evaluator, proposal_title, strategic_alignment, potential_impact, feasibility, budget_justification, timeline_readiness, execution_strategy, total, recommendation, comments, last_updated)
                        VALUES (:ev, :prop, :s1, :s2, :s3, :s4, :s5, :s6, :tot, :rec, :comm, :ts)
                        ON CONFLICT (evaluator, proposal_title) DO UPDATE SET 
                        strategic_alignment=EXCLUDED.strategic_alignment, potential_impact=EXCLUDED.potential_impact,
                        feasibility=EXCLUDED.feasibility, budget_justification=EXCLUDED.budget_justification,
                        timeline_readiness=EXCLUDED.timeline_readiness, execution_strategy=EXCLUDED.execution_strategy,
                        total=EXCLUDED.total, recommendation=EXCLUDED.recommendation, comments=EXCLUDED.comments, last_updated=EXCLUDED.last_updated"""),
                        {"ev": current_user, "prop": selected_proposal, "s1": inputs['Strategic Alignment'], "s2": inputs['Potential Impact'], "s3": inputs['Feasibility'], "s4": inputs['Budget Justification'], "s5": inputs['Timeline Readiness'], "s6": inputs['Execution Strategy'], "tot": final_total, "rec": recom, "comm": final_comm, "ts": datetime.now()})
                    s.commit()
                st.success("Evaluation Saved!"); time.sleep(1); st.rerun()
else:
    st.subheader("📊 Submitted Scores")
    if not scored_df.empty:
        st.dataframe(scored_df[["proposal_title", "total", "recommendation"]], use_container_width=True, hide_index=True)
    
    rem = [p for p in PROPOSALS if p not in completed_proposals]
    if rem:
        with st.expander(f"⏳ Pending Evaluations ({len(rem)})"):
            for p in rem:
                st.button(f"📝 Start Scoring: {p}", key=f"btn_{p}", use_container_width=True, on_click=nav_to_proposal, args=(p,))
