import streamlit as st
import pandas as pd
import time
import re
import msal
from datetime import datetime
from sqlalchemy import text
from streamlit_autorefresh import st_autorefresh

# --- 0. INITIALIZE SESSION STATE ---
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "current_user" not in st.session_state:
    st.session_state["current_user"] = None

# --- 1. CONFIGURATION ---
CLIENT_ID = st.secrets["azure_client_id"]
CLIENT_SECRET = st.secrets["azure_client_secret"]
TENANT_ID = st.secrets["azure_tenant_id"]
SUPABASE_URL = st.secrets["supabase_url"]
BUCKET_NAME = "evaluator-photos"

CRITERIA = [
    ('Strategic Alignment', 0.25), ('Potential Impact', 0.20), 
    ('Feasibility', 0.15), ('Budget Justification', 0.15), 
    ('Timeline Readiness', 0.10), ('Execution Strategy', 0.15)
]

st.set_page_config(page_title="ASM Evaluator Entry", layout="wide")
conn = st.connection("postgresql", type="sql")

# --- 2. AUTHENTICATION UTILITIES ---
def get_msal_app():
    return msal.ConfidentialClientApplication(
        CLIENT_ID, 
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        client_credential=CLIENT_SECRET
    )

def get_auth_url():
    return get_msal_app().get_authorization_request_url(["User.Read"])

# --- 2. UPDATED CALLBACK HANDLER ---
def handle_sso_callback():
    params = st.query_params
    if "code" in params:
        code = params["code"]
        try:
            token_result = get_msal_app().acquire_token_by_authorization_code(
                code,
                scopes=["User.Read"],
                redirect_uri=st.secrets.get("redirect_uri")
            )
            if "id_token_claims" in token_result:
                ms_email = token_result["id_token_claims"].get("preferred_username").lower()
                st.query_params.clear() 
                return ms_email
        except Exception as e:
            st.session_state["login_error"] = f"Authentication Error: {str(e)}"
            st.query_params.clear()
            st.rerun()
    return None

# --- 3. THE LOGIN GATEKEEPER ---
def check_auth():
    if st.session_state["authenticated"]:
        return True

    if "login_error" in st.session_state:
        st.error(st.session_state["login_error"])
        if st.button("🔄 Try Again"):
            del st.session_state["login_error"]
            st.rerun()
        st.stop()

    ms_email = handle_sso_callback()
    if ms_email:
        user_data = conn.query(
            "SELECT name FROM evaluators WHERE LOWER(TRIM(sso_email)) = LOWER(:e) LIMIT 1", 
            params={"e": ms_email.strip()}, 
            ttl=0
        )
        
        if not user_data.empty:
            st.session_state["authenticated"] = True
            st.session_state["current_user"] = user_data.iloc[0]['name']
            st.rerun()
        else:
            st.session_state["login_error"] = f"❌ Access Denied: {ms_email} is not registered in the ASM database."
            st.rerun()

    st.title("🛡️ ASM Evaluator Portal")
    st.warning("🔒 This system is restricted to authorized ASM Evaluators only.")
    
    tab1, tab2 = st.tabs(["Microsoft SSO", "Local Login"])
    
    with tab1:
        st.info("Log in with your @akademisains.gov.my or registered corporate email.")
        auth_url = get_auth_url()
        
        # JAVASCRIPT REDIRECT WITH LOADING SPINNER
        login_html = f"""
            <div id="login-container" style="display: flex; justify-content: center; flex-direction: column; align-items: center;">
                <button id="sso-button" onclick="startLogin()" style="
                    width: 100%; background-color: #1E3A8A; color: white; padding: 14px;
                    border: none; border-radius: 8px; cursor: pointer; font-weight: bold;
                    font-size: 16px; display: flex; align-items: center; justify-content: center;
                ">
                    <span id="btn-text">🚀 Sign in with Microsoft</span>
                </button>
                <div id="loader" style="display: none; margin-top: 10px; border: 4px solid #f3f3f3; border-top: 4px solid #1E3A8A; border-radius: 50%; width: 30px; height: 30px; animation: spin 2s linear infinite;"></div>
            </div>

            <style>
                @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
            </style>

            <script>
                function startLogin() {{
                    const btn = document.getElementById('sso-button');
                    const loader = document.getElementById('loader');
                    const btnText = document.getElementById('btn-text');
                    
                    btn.style.backgroundColor = '#cccccc';
                    btn.disabled = true;
                    btnText.innerHTML = 'Redirecting to Microsoft...';
                    loader.style.display = 'block';
                    
                    setTimeout(() => {{
                        window.parent.location.href = "{auth_url}";
                    }}, 500);
                }}
            </script>
        """
        st.components.v1.html(login_html, height=120)

    with tab2:
        with st.form("local_login"):
            u_name = st.text_input("Evaluator Name")
            u_pass = st.text_input("Password", type="password")
            if st.form_submit_button("Login", use_container_width=True):
                res = conn.query("SELECT value FROM settings WHERE key = 'evaluator_password' LIMIT 1", ttl=0)
                db_pass = res.iloc[0]['value'] if not res.empty else None
                eval_check = conn.query("SELECT name FROM evaluators WHERE name = :n LIMIT 1", params={"n": u_name}, ttl=0)
                
                if not eval_check.empty and u_pass == db_pass:
                    st.session_state["authenticated"] = True
                    st.session_state["current_user"] = u_name
                    st.rerun()
                else:
                    st.error("Invalid name or password. Please try again.")
    
    st.stop()

# --- 4. APP LOGIC ---
check_auth()
current_user = st.session_state["current_user"]
st_autorefresh(interval=30000, key="evaluator_heartbeat")

# Navigation Callbacks
def nav_to_summary():
    st.session_state.proposal_selector = "-- Select --"
    st.session_state.is_editing = False

def nav_to_proposal(title):
    st.session_state.proposal_selector = title
    st.session_state.is_editing = False

def enable_editing():
    st.session_state.is_editing = True

def get_cloud_list(table, column):
    try:
        df = conn.query(f"SELECT {column} FROM {table} ORDER BY {column} ASC;", ttl=0)
        return df[column].tolist() if not df.empty else []
    except: return []

PROPOSALS = get_cloud_list("proposals", "title")

# --- 5. HEADER & SIGN OUT ---
cache_buster = datetime.now().strftime("%Y%m%d%H%M%S")
col_img, col_txt = st.columns([1, 4])

with col_img:
    img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{current_user.replace(' ', '_')}.png?t={cache_buster}"
    st.markdown(f'<div style="text-align: center;"><img src="{img_url}" style="width:100px; height:100px; border-radius:50%; object-fit:cover; border: 3px solid #1E3A8A;" onerror="this.src=\'https://ui-avatars.com/api/?name={current_user}\'"></div>', unsafe_allow_html=True)

with col_txt:
    st.title(f"Welcome, {current_user}")
    
    logout_url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/logout?post_logout_redirect_uri={st.secrets.get('redirect_uri')}"
    
    if st.button("🚪 Sign Out"):
        st.session_state.clear()
        st.components.v1.html(f"""
            <script>window.parent.location.href = "{logout_url}";</script>
        """, height=0)
        st.stop()

# --- 6. PROGRESS TRACKING ---
try:
    scored_df = conn.query("SELECT proposal_title, total, recommendation, comments FROM scores WHERE evaluator = :ev", params={"ev": current_user}, ttl=0)
    completed_proposals = scored_df['proposal_title'].tolist() if not scored_df.empty else []
    
    def extract_merge_target(comment):
        if pd.isna(comment): return ""
        match = re.search(r"\[MERGE WITH: (.*?)\]", str(comment))
        return match.group(1) if match else ""

    if not scored_df.empty:
        scored_df['merge_target'] = scored_df['comments'].apply(extract_merge_target)
        scored_df['display_comments'] = scored_df['comments'].str.replace(r"\[MERGE WITH:.*?\] ", "", regex=True)
except:
    scored_df = pd.DataFrame()
    completed_proposals = []

st.write(f"**Progress: {len(completed_proposals)} / {len(PROPOSALS)} Proposals**")
st.progress(len(completed_proposals) / len(PROPOSALS) if PROPOSALS else 0)
st.divider()

# --- 7. EVALUATION FORM ---
if "proposal_selector" not in st.session_state:
    st.session_state.proposal_selector = "-- Select --"

selected_proposal = st.selectbox("Select Proposal", ["-- Select --"] + PROPOSALS, key="proposal_selector")

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
        c1.button("✏️ Edit", use_container_width=True, on_click=enable_editing)
        c2.button("⬅️ Summary", use_container_width=True, on_click=nav_to_summary)
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
                st.success("Saved!"); time.sleep(1); st.rerun()
else:
    st.subheader("📊 Your Summary")
    if not scored_df.empty:
        st.dataframe(scored_df[["proposal_title", "total", "recommendation"]], use_container_width=True, hide_index=True)
    
    rem = [p for p in PROPOSALS if p not in completed_proposals]
    if rem:
        with st.expander(f"⏳ Remaining ({len(rem)})"):
            for p in rem:
                st.button(f"📝 Start: {p}", key=f"btn_{p}", use_container_width=True, on_click=nav_to_proposal, args=(p,))

    if not rem and len(PROPOSALS) > 0:
        if st.button("🏁 Finalize & Close Session", type="primary", use_container_width=True):
            with conn.session as s:
                s.execute(text("UPDATE evaluators SET has_submitted = TRUE WHERE name = :name"), {"name": current_user})
                s.commit()
            st.rerun()
