import streamlit as st
import pandas as pd
import time
import re
import msal
import warnings
from datetime import datetime
from sqlalchemy import text
from streamlit_autorefresh import st_autorefresh

# 1. SILENCE MSAL SECURITY WARNINGS
warnings.filterwarnings("ignore", category=UserWarning, module="msal")

# --- 2. CONFIGURATION ---
CLIENT_ID = st.secrets["azure_client_id"]
CLIENT_SECRET = st.secrets["azure_client_secret"]
TENANT_ID = st.secrets["azure_tenant_id"]
REDIRECT_URI = st.secrets["azure_redirect_uri"] 
SUPABASE_URL = st.secrets["supabase_url"]
BUCKET_NAME = "evaluator-photos"

CRITERIA = [
    ('Strategic Alignment', 0.25), ('Potential Impact', 0.20), 
    ('Feasibility', 0.15), ('Budget Justification', 0.15), 
    ('Timeline Readiness', 0.10), ('Execution Strategy', 0.15)
]

st.set_page_config(page_title="ASM Evaluator Entry", layout="wide")
conn = st.connection("postgresql", type="sql")

# --- 3. SESSION STATE ---
if "current_user" not in st.session_state:
    st.session_state["current_user"] = None
if "user_email" not in st.session_state:
    st.session_state["user_email"] = None
if "auth_flow" not in st.session_state:
    st.session_state["auth_flow"] = None

# --- 4. AUTHENTICATION HELPERS ---
def get_msal_app():
    return msal.ConfidentialClientApplication(
        CLIENT_ID, 
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        client_credential=CLIENT_SECRET
    )

def verify_and_login(email):
    """Verifies email against database and starts session."""
    if not email:
        return False
    email_clean = email.lower().strip()
    user_check = conn.query(
        "SELECT name FROM evaluators WHERE LOWER(sso_email) = :e LIMIT 1", 
        params={"e": email_clean}, ttl=0
    )
    if not user_check.empty:
        st.session_state["user_email"] = email_clean
        st.session_state["current_user"] = user_check.iloc[0]['name']
        return True
    return False

# --- 5. ACCESS CONTROL SCREEN ---
if not st.session_state["user_email"]:
    params = st.query_params.to_dict()

    # A. Check for SSO Callback
    if "code" in params:
        flow = st.session_state.get("auth_flow")
        if flow:
            try:
                app = get_msal_app()
                result = app.acquire_token_by_auth_code_flow(flow, params)
                if "id_token_claims" in result:
                    sso_email = result["id_token_claims"].get("preferred_username")
                    if verify_and_login(sso_email):
                        st.query_params.clear()
                        st.rerun()
                    else:
                        st.error(f"❌ Access Denied: {sso_email} is not authorized.")
            except Exception as e:
                st.error(f"SSO Error: {e}")
        else:
            st.error("Session expired. Please try again.")

    # B. Login UI
    st.title("🛡️ ASM Evaluator Access")
    
    input_email = st.text_input("Enter Registered Email", placeholder="name@organization.com").lower().strip()
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("Access System", type="primary", use_container_width=True):
            if verify_and_login(input_email):
                st.success(f"Welcome back!")
                time.sleep(1)
                st.rerun()
            else:
                st.error("❌ Email not found in the authorized database.")

    with col2:
        # Generate SSO flow for the button
        if st.session_state["auth_flow"] is None:
            try:
                app = get_msal_app()
                st.session_state["auth_flow"] = app.initiate_auth_code_flow(["User.Read"], redirect_uri=REDIRECT_URI)
            except: pass
        
        if st.session_state["auth_flow"]:
            auth_url = st.session_state["auth_flow"].get("auth_uri")
            if input_email: auth_url += f"&login_hint={input_email}"
            
            st.markdown(f'''
                <a href="{auth_url}" target="_top" style="text-decoration:none;">
                    <div style="background-color:#1E3A8A; color:white; text-align:center; 
                    padding:10px; border-radius:5px; font-weight:bold; height:42px; border:1px solid #1E3A8A;">
                        Sign in with Microsoft
                    </div>
                </a>
            ''', unsafe_allow_html=True)

    st.stop() 

# --- 6. AUTHORIZED APP CONTENT ---
current_user = st.session_state["current_user"]
user_email = st.session_state["user_email"]

st_autorefresh(interval=30000, key="evaluator_heartbeat")

# Sidebar
with st.sidebar:
    st.write(f"Logged in as:")
    st.subheader(current_user)
    st.caption(user_email)
    if st.button("Logout / Change Email"):
        st.session_state.clear()
        st.rerun()

# Functions
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

# Profile Header
col_img, col_txt = st.columns([1, 4])
with col_img:
    img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{current_user.replace(' ', '_')}.png"
    st.markdown(f'<div style="text-align: center;"><img src="{img_url}" style="width:100px; height:100px; border-radius:50%; object-fit:cover; border: 3px solid #1E3A8A;" onerror="this.src=\'https://ui-avatars.com/api/?name={current_user}\'"></div>', unsafe_allow_html=True)

with col_txt:
    st.title(f"Evaluation Dashboard")

# Progress
try:
    scored_df = conn.query("SELECT proposal_title, total, recommendation, comments FROM scores WHERE evaluator = :ev", params={"ev": current_user}, ttl=0)
    completed_proposals = scored_df['proposal_title'].tolist() if not scored_df.empty else []
except:
    scored_df = pd.DataFrame()
    completed_proposals = []

st.write(f"**Overall Progress: {len(completed_proposals)} / {len(PROPOSALS)} Proposals**")
st.progress(len(completed_proposals) / len(PROPOSALS) if PROPOSALS else 0)
st.divider()

if "proposal_selector" not in st.session_state:
    st.session_state.proposal_selector = "-- Select --"

selected_proposal = st.selectbox("Select Proposal to Evaluate", ["-- Select --"] + PROPOSALS, key="proposal_selector")

if selected_proposal != "-- Select --":
    query = "SELECT * FROM scores WHERE evaluator = :ev AND proposal_title = :prop LIMIT 1;"
    df_match = conn.query(query, params={"ev": current_user, "prop": selected_proposal}, ttl=0)
    existing_data = df_match.iloc[0] if not df_match.empty else None

    if "is_editing" not in st.session_state:
        st.session_state.is_editing = False

    if existing_data is not None and not st.session_state.is_editing:
        st.success(f"✅ Record found for: {selected_proposal}")
        st.metric("Total Score", f"{existing_data['total']} / 5.0")
        c1, c2 = st.columns(2)
        if c1.button("✏️ Edit Record", use_container_width=True):
            st.session_state.is_editing = True
            st.rerun()
        c2.button("⬅️ Back to Summary", use_container_width=True, on_click=nav_to_summary)
    else:
        with st.form("eval_form"):
            st.subheader(f"Evaluating: {selected_proposal}")
            inputs = {}
            for name, weight in CRITERIA:
                col_db = name.lower().replace(" ", "_")
                val = float(existing_data[col_db]) if existing_data is not None else 0.0
                inputs[name] = st.number_input(f"{name} ({int(weight*100)}%)", 0.0, 5.0, val, 0.1)
            
            clean_comm = re.sub(r"\[MERGE WITH:.*?\] ", "", str(existing_data['comments']) if existing_data is not None else "")
            user_comments = st.text_area("Comments", value=clean_comm)
            recom_options = ["Pending", "Approve", "Revise", "Reject", "Combine/Merge"]
            cur_rec = str(existing_data['recommendation']) if existing_data is not None else "Pending"
            recom = st.radio("Recommendation", recom_options, index=recom_options.index(cur_rec) if cur_rec in recom_options else 0, horizontal=True)

            merge_target = None
            if recom == "Combine/Merge":
                other_proposals = [p for p in PROPOSALS if p != selected_proposal]
                merge_target = st.selectbox("Merge with:", other_proposals)

            if st.form_submit_button("📤 Submit Evaluation", type="primary"):
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
    st.subheader("📊 Your Evaluation Summary")
    if not scored_df.empty:
        st.dataframe(scored_df[["proposal_title", "total", "recommendation"]], use_container_width=True, hide_index=True)
    
    rem = [p for p in PROPOSALS if p not in completed_proposals]
    if rem:
        with st.expander(f"⏳ Pending Evaluations ({len(rem)})"):
            for p in rem:
                st.button(f"📝 Start Scoring: {p}", key=f"btn_{p}", use_container_width=True, on_click=nav_to_proposal, args=(p,))
