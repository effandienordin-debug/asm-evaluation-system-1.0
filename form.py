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

# --- 4. NAVIGATION CALLBACKS ---
def nav_to_summary():
    st.session_state.proposal_selector = "-- Select --"
    st.session_state.is_editing = False

def nav_to_proposal(title):
    st.session_state.proposal_selector = title
    st.session_state.is_editing = False

def enable_editing():
    st.session_state.is_editing = True

# --- 5. DATA FETCHING HELPERS ---
def get_cloud_list(table, column):
    try:
        df = conn.query(f"SELECT {column} FROM {table} ORDER BY {column} ASC;", ttl=0)
        return df[column].tolist() if not df.empty else []
    except:
        return []

st_autorefresh(interval=30000, key="evaluator_heartbeat")
EVALUATORS = get_cloud_list("evaluators", "name")
PROPOSALS = get_cloud_list("proposals", "title")

# --- 6. USER IDENTIFICATION ---
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

# --- 7. SUBMISSION LOCK CHECK ---
try:
    status_df = conn.query("SELECT has_submitted FROM evaluators WHERE name = :name LIMIT 1;", params={"name": current_user}, ttl=0)
    if not status_df.empty and status_df.iloc[0]['has_submitted']:
        st.warning(f"Hello {current_user}, your session is completed and locked.")
        st.info("Please contact the Administrator if you need to revise your entries.")
        st.stop()
except:
    pass

# --- 8. INITIALIZE STATE & PENDING REDIRECTS ---
if "proposal_selector" not in st.session_state:
    st.session_state.proposal_selector = "-- Select --"

if st.session_state.get("pending_nav"):
    st.session_state.proposal_selector = "-- Select --"
    st.session_state.is_editing = False
    del st.session_state["pending_nav"]
    st.rerun()

# --- 9. HEADER ---
cache_buster = int(datetime.now().timestamp())
col_img, col_txt = st.columns([1, 4])
with col_img:
    clean_name = current_user.replace(' ', '_')
    img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{clean_name}.png?t={cache_buster}"
    st.markdown(f'<div style="text-align: center;"><img src="{img_url}" style="width:100px; height:100px; border-radius:50%; object-fit:cover; border: 3px solid #1E3A8A;" onerror="this.src=\'https://ui-avatars.com/api/?name={current_user}\'"></div>', unsafe_allow_html=True)
with col_txt:
    st.title(f"Welcome, {current_user}")
    st.write("Official ASM Evaluation Portal")

# --- 10. PROGRESS DATA FETCH ---
try:
    scored_df = conn.query("SELECT proposal_title, total, recommendation, comments FROM scores WHERE evaluator = :ev", params={"ev": current_user}, ttl=0)
    completed_proposals = scored_df['proposal_title'].tolist() if not scored_df.empty else []
except:
    scored_df = pd.DataFrame()
    completed_proposals = []

total_count = len(PROPOSALS)
done_count = len(completed_proposals)
st.write(f"**Overall Progress: {done_count} / {total_count} Proposals Evaluated**")
st.progress(done_count / total_count if total_count > 0 else 0)
st.divider()

# --- 11. CLICKABLE TABLE LOGIC ---
if "summary_table" in st.session_state:
    selection = st.session_state.summary_table.get("selection", {}).get("rows", [])
    if selection:
        selected_row_index = selection[0]
        clicked_prop = scored_df.iloc[selected_row_index]["proposal_title"]
        st.session_state.proposal_selector = clicked_prop
        st.session_state.is_editing = True 
        st.session_state.summary_table["selection"]["rows"] = []
        st.rerun()

# --- 12. EVALUATION FORM & NAVIGATION ---
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
            st.button("✏️ Edit Scores", use_container_width=True, on_click=enable_editing)
        with col_back:
            st.button("⬅️ Back to Summary", use_container_width=True, on_click=nav_to_summary)
    else:
        with st.form("evaluation_form"):
            st.subheader(f"Evaluation: {selected_proposal}")
            
            inputs = {}
            criteria_met = 0
            for name, weight in CRITERIA:
                col_db = name.lower().replace(" ", "_")
                default_val = float(existing_data[col_db]) if existing_data is not None else 0.0
                saved_val = st.session_state.get(f"{draft_key}_{col_db}", default_val)
                inputs[name] = st.number_input(f"{name} ({int(weight*100)}%)", 0.0, 5.0, saved_val, 0.1)
                if inputs[name] > 0: criteria_met += 1
            
            form_progress = criteria_met / len(CRITERIA)
            st.write(f"Criteria Completed: {criteria_met}/{len(CRITERIA)}")
            st.progress(form_progress)

            default_comm = str(existing_data['comments']) if existing_data is not None else ""
            saved_comm = st.session_state.get(f"{draft_key}_comm", default_comm)
            user_comments = st.text_area("Comments / Remarks", value=saved_comm)
            
            if st.session_state.get(f"{draft_key}_dirty", False):
                st.caption("🟢 Changes detected in draft")
            
            default_recom = str(existing_data['recommendation']) if existing_data is not None else "Pending"
            recom = st.radio("Recommendation", ["Pending", "Approve", "Revise", "Reject"], 
                             index=["Pending", "Approve", "Revise", "Reject"].index(default_recom), horizontal=True)
            
            col_sub, col_can = st.columns(2)
            with col_sub:
                submit = st.form_submit_button("📤 Submit Evaluation", use_container_width=True, type="primary")
            with col_can:
                cancel = st.form_submit_button("❌ Cancel", use_container_width=True)

            if submit:
                w_sum = sum(inputs[name] * weight for name, weight in CRITERIA if inputs[name] > 0)
                w_used = sum(weight for name, weight in CRITERIA if inputs[name] > 0)
                final_total = round(w_sum / w_used, 2) if w_used > 0 else 0.0

                with conn.session as s:
                    s.execute(text("""INSERT INTO scores (evaluator, proposal_title, strategic_alignment, potential_impact, feasibility, budget_justification, timeline_readiness, execution_strategy, total, recommendation, comments, last_updated)
                                      VALUES (:ev, :prop, :s1, :s2, :s3, :s4, :s5, :s6, :tot, :rec, :comm, :ts)
                                      ON CONFLICT (evaluator, proposal_title) DO UPDATE SET 
                                      strategic_alignment=EXCLUDED.strategic_alignment, potential_impact=EXCLUDED.potential_impact,
                                      feasibility=EXCLUDED.feasibility, budget_justification=EXCLUDED.budget_justification,
                                      timeline_readiness=EXCLUDED.timeline_readiness, execution_strategy=EXCLUDED.execution_strategy,
                                      total=EXCLUDED.total, recommendation=EXCLUDED.recommendation, comments=EXCLUDED.comments, last_updated=EXCLUDED.last_updated"""),
                              {"ev": current_user, "prop": selected_proposal, "s1": inputs['Strategic Alignment'], "s2": inputs['Potential Impact'], 
                               "s3": inputs['Feasibility'], "s4": inputs['Budget Justification'], "s5": inputs['Timeline Readiness'], 
                               "s6": inputs['Execution Strategy'], "tot": final_total, "rec": recom, "comm": user_comments, "ts": datetime.now()})
                    s.commit()
                
                st.session_state.pending_nav = True
                st.success("Evaluation Saved!")
                time.sleep(1)
                st.rerun()
            
            if cancel:
                st.session_state.pending_nav = True
                st.rerun()

        for name, _ in CRITERIA:
            key = f"{draft_key}_{name.lower().replace(' ', '_')}"
            if st.session_state.get(key) != inputs[name]:
                st.session_state[key] = inputs[name]
                st.session_state[f"{draft_key}_dirty"] = True
        
        if st.session_state.get(f"{draft_key}_comm") != user_comments:
            st.session_state[f"{draft_key}_comm"] = user_comments
            st.session_state[f"{draft_key}_dirty"] = True

else:
    # --- 13. SUMMARY DASHBOARD ---
    st.subheader("📊 Your Evaluation Summary")
    st.info("💡 Click a row in the table below to edit that proposal.")
    
    if not scored_df.empty:
        # Prepare the dataframe for display
        summary_display = scored_df.copy()
        summary_display = summary_display.rename(columns={
            "proposal_title": "Proposal Name", 
            "total": "Score", 
            "recommendation": "Recommendation",
            "comments": "Remarks"
        })

        # Display using native Streamlit ProgressColumn for colors
        st.dataframe(
            summary_display, 
            use_container_width=True, 
            hide_index=True, 
            on_select="rerun", 
            selection_mode="single-row", 
            key="summary_table",
            column_config={
                "Score": st.column_config.ProgressColumn(
                    "Score",
                    help="Score out of 5.0",
                    format="%.1f",
                    min_value=0,
                    max_value=5,
                ),
                "Remarks": st.column_config.TextColumn(
                    width="large", 
                    wrap_text=True
                ),
                "Proposal Name": st.column_config.TextColumn(width="medium"),
                "Recommendation": st.column_config.TextColumn(width="small"),
            }
        )
    else:
        st.info("No proposals evaluated yet.")

    remaining = [p for p in PROPOSALS if p not in completed_proposals]
    if remaining:
        with st.expander("⏳ View Remaining Proposals"):
            for p in remaining:
                st.button(f"📝 Start: {p}", key=f"btn_{p}", use_container_width=True, on_click=nav_to_proposal, args=(p,))

    # --- 14. CONDITIONAL FINALIZE ---
    all_done = (len(remaining) == 0 and total_count > 0)
    if all_done:
        st.divider()
        st.subheader("🏁 Finish Evaluation")
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
