import streamlit as st
import pandas as pd
import time
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

# --- 3. LOGIN LOGIC ---
def check_password():
    def password_entered():
        try:
            pass_df = conn.query("SELECT value FROM settings WHERE key = 'evaluator_password' LIMIT 1", ttl=0)
            db_password = pass_df.iloc[0]['value'] if not pass_df.empty else None
        except:
            db_password = None
        
        if st.session_state["password"] == db_password:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.title("🔐 ASM Evaluator Login")
        st.text_input("Enter Access Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.title("🔐 ASM Secure Access")
        st.text_input("Please enter the access password", type="password", on_change=password_entered, key="password")
        st.error("😕 Password incorrect")
        return False
    return True

if not check_password():
    st.stop()

# --- 4. DATA FETCHING HELPERS ---
def get_cloud_list(table, column):
    try:
        df = conn.query(f"SELECT {column} FROM {table} ORDER BY {column} ASC;", ttl=0)
        return df[column].tolist() if not df.empty else []
    except:
        return []

st_autorefresh(interval=30000, key="evaluator_heartbeat")
EVALUATORS = get_cloud_list("evaluators", "name")
PROPOSALS = get_cloud_list("proposals", "title")

# --- 5. USER IDENTIFICATION ---
user_param = st.query_params.get("user")
if user_param is None or not EVALUATORS:
    st.warning("⚠️ Access Denied. Please use your personalized link.")
    st.stop()

current_user = None
if user_param.isdigit():
    idx = int(user_param)
    if idx < len(EVALUATORS): current_user = EVALUATORS[idx]
else:
    if user_param in EVALUATORS: current_user = user_param

if not current_user:
    st.error("Invalid User Identification.")
    st.stop()

# --- 6. SUBMISSION LOCK CHECK ---
try:
    status_df = conn.query("SELECT has_submitted FROM evaluators WHERE name = :name LIMIT 1;", params={"name": current_user}, ttl=0)
    if not status_df.empty and status_df.iloc[0]['has_submitted']:
        st.warning(f"Hello {current_user}, your session is completed and locked.")
        st.info("Please contact the Administrator if you need to revise your entries.")
        st.stop()
except:
    pass

# --- 7. HEADER ---
cache_buster = int(datetime.now().timestamp())
col_img, col_txt = st.columns([1, 4])
with col_img:
    clean_name = current_user.replace(' ', '_')
    img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{clean_name}.png?t={cache_buster}"
    st.markdown(f'<div style="text-align: center;"><img src="{img_url}" style="width:100px; height:100px; border-radius:50%; object-fit:cover; border: 3px solid #1E3A8A;" onerror="this.src=\'https://ui-avatars.com/api/?name={current_user}\'"></div>', unsafe_allow_html=True)
with col_txt:
    st.title(f"Welcome, {current_user}")
    st.write("Official ASM Evaluation Portal")

# --- 8. PROGRESS DATA FETCH ---
try:
    scored_df = conn.query("SELECT proposal_title, total, comments FROM scores WHERE evaluator = :ev", params={"ev": current_user}, ttl=0)
    completed_proposals = scored_df['proposal_title'].tolist() if not scored_df.empty else []
except:
    scored_df = pd.DataFrame()
    completed_proposals = []

total_count = len(PROPOSALS)
done_count = len(completed_proposals)
st.write(f"**Overall Progress: {done_count} / {total_count} Proposals Evaluated**")
st.progress(done_count / total_count if total_count > 0 else 0)
st.divider()

# --- 9. EVALUATION FORM & AUTO-SAVE LOGIC ---

# 1. Initialize a key for the selectbox in session state if it doesn't exist
if "proposal_selector" not in st.session_state:
    st.session_state.proposal_selector = "-- Select --"

# 2. Use the session state variable to control the selectbox
selected_proposal = st.selectbox(
    "Select Proposal Title", 
    ["-- Select --"] + PROPOSALS,
    key="proposal_selector"
)

if selected_proposal != "-- Select --":
    draft_key = f"draft_{current_user}_{selected_proposal}"
    
    query = "SELECT * FROM scores WHERE evaluator = :ev AND proposal_title = :prop LIMIT 1;"
    df_match = conn.query(query, params={"ev": current_user, "prop": selected_proposal}, ttl=0)
    existing_data = df_match.iloc[0] if not df_match.empty else None

    if "is_editing" not in st.session_state:
        st.session_state.is_editing = False

    if existing_data is not None and not st.session_state.is_editing:
        st.success(f"✅ Record found for: {selected_proposal}")
        st.metric("Your Total Score", f"{existing_data['total']} / 5.0")
        
        col_edit, col_back = st.columns(2)
        with col_edit:
            if st.button("✏️ Edit Scores", use_container_width=True):
                st.session_state.is_editing = True
                st.rerun()
        with col_back:
            # THIS IS THE FIX: Manually reset the selectbox key to return to summary
            if st.button("⬅️ Back to Summary", use_container_width=True):
                st.session_state.proposal_selector = "-- Select --"
                st.rerun()
    else:
        # ... (Rest of your form code remains the same)
        with st.form("evaluation_form"):
            # (Inputs here...)
            # ...
            col_sub, col_can = st.columns(2)
            with col_sub:
                submit = st.form_submit_button("📤 Submit Evaluation", use_container_width=True, type="primary")
            with col_can:
                # FIX: Also reset the selector on Cancel
                cancel = st.form_submit_button("❌ Cancel", use_container_width=True)

            if submit:
                # ... (Your save logic here) ...
                # After saving, reset selector to show the updated summary table
                st.session_state.proposal_selector = "-- Select --"
                st.session_state.is_editing = False
                st.success("Evaluation Saved!")
                time.sleep(1)
                st.rerun()
            
            if cancel:
                st.session_state.proposal_selector = "-- Select --"
                st.session_state.is_editing = False
                st.rerun()

        # Update draft state silently outside the form
        for name, _ in CRITERIA:
            col_db = name.lower().replace(" ", "_")
            st.session_state[f"{draft_key}_{col_db}"] = inputs[name]
        st.session_state[f"{draft_key}_comm"] = user_comments

else:
    # --- 10. PROGRESS DASHBOARD ---
    st.subheader("📊 Your Evaluation Summary")
    
    if not scored_df.empty:
        summary_display = scored_df.rename(columns={
            "proposal_title": "Proposal Name",
            "total": "Score",
            "comments": "Remarks"
        })
        st.dataframe(summary_display, use_container_width=True, hide_index=True)
    else:
        st.info("No proposals evaluated yet.")

    remaining = [p for p in PROPOSALS if p not in completed_proposals]
    if remaining:
        with st.expander("⏳ View Remaining Proposals"):
            for p in remaining: st.write(f"▫️ {p}")

    # --- 11. CONDITIONAL FINALIZE ---
    all_done = (len(remaining) == 0 and total_count > 0)
    if all_done:
        st.divider()
        st.subheader("🏁 Finish Evaluation")
        st.success("All proposals complete. Finalize to lock your session.")
        if st.button("Finalize and Close Session", type="primary", use_container_width=True):
            with conn.session as s:
                s.execute(text("UPDATE evaluators SET has_submitted = TRUE WHERE name = :name"), {"name": current_user})
                s.commit()
            st.success("Session Locked!")
            time.sleep(2)
            st.rerun()
    else:
        st.divider()
        st.info(f"💡 Complete the **{len(remaining)}** remaining proposal(s) to finalize.")

