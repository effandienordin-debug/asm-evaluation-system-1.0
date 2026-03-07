import streamlit as st
import pandas as pd
import time
import re
import msal
from datetime import datetime
from sqlalchemy import text
from streamlit_autorefresh import st_autorefresh

# --- 1. CONFIGURATION ---
# Replace with your actual secrets from the Admin Panel
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

# --- 2. MICROSOFT AUTH LOGIC ---
def get_msal_app():
    return msal.ConfidentialClientApplication(
        CLIENT_ID, 
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        client_credential=CLIENT_SECRET
    )

def get_auth_url():
    client = get_msal_app()
    return client.get_authorization_request_url(["User.Read"])

def handle_sso_callback():
    # 1. Look for the 'code' Microsoft sent back in the URL
    if "code" in st.query_params:
        code = st.query_params["code"]
        client = get_msal_app()
        
        # 2. Exchange that code for an actual Identity Token
        token_result = client.acquire_token_by_authorization_code(
            code,
            scopes=["User.Read"],
            redirect_uri=st.secrets.get("redirect_uri") # Must match Azure EXACTLY
        )
        
        if "id_token_claims" in token_result:
            ms_email = token_result["id_token_claims"].get("preferred_username").lower()
            # 3. CRITICAL: Clear the URL so we don't try to reuse the same code
            st.query_params.clear() 
            return ms_email
            
        elif "error" in token_result:
            st.error(f"Auth Error: {token_result.get('error_description')}")
            
    return None

# --- 3. LOGIN & IDENTITY CHECK ---
def check_auth():
    # If already logged in, just let them through
    if st.session_state.get("authenticated"):
        return True

    # 1. Check if we are CURRENTLY returning from Microsoft
    ms_email = handle_sso_callback()
    
    if ms_email:
        # 2. Verify this email exists in our DB
        user_data = conn.query(
            "SELECT name FROM evaluators WHERE LOWER(sso_email) = :email LIMIT 1",
            params={"email": ms_email.strip()}, ttl=0
        )
        
        if not user_data.empty:
            st.session_state["authenticated"] = True
            st.session_state["current_user"] = user_data.iloc[0]['name']
            st.rerun() # Refresh to clear login UI and show the portal
        else:
            st.error(f"❌ Access Denied: {ms_email} is not on the evaluator list.")
            st.link_button("Try Again", get_auth_url())
            st.stop()

    # 3. If not returning from MS and not authenticated, show the login button
    st.title("🛡️ ASM Evaluator Portal")
    st.info("Please sign in with your corporate Microsoft account.")
    st.link_button("🚀 Sign in with Microsoft", get_auth_url(), use_container_width=True)
    st.stop() # This prevents the rest of the script from loading a "blank" portal

current_user = st.session_state["current_user"]

# --- 4. NAVIGATION CALLBACKS ---
def nav_to_summary():
    st.session_state.proposal_selector = "-- Select --"
    st.session_state.is_editing = False

def nav_to_proposal(title):
    st.session_state.proposal_selector = title
    st.session_state.is_editing = False

def enable_editing():
    st.session_state.is_editing = True

# --- 5. DATA FETCHING ---
st_autorefresh(interval=30000, key="evaluator_heartbeat")

def get_cloud_list(table, column):
    try:
        df = conn.query(f"SELECT {column} FROM {table} ORDER BY {column} ASC;", ttl=0)
        return df[column].tolist() if not df.empty else []
    except: return []

PROPOSALS = get_cloud_list("proposals", "title")

# --- 6. HEADER ---
cache_buster = datetime.now().strftime("%Y%m%d%H%M%S")
col_img, col_txt = st.columns([1, 4])
with col_img:
    img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{current_user.replace(' ', '_')}.png?t={cache_buster}"
    st.markdown(f'<div style="text-align: center;"><img src="{img_url}" style="width:100px; height:100px; border-radius:50%; object-fit:cover; border: 3px solid #1E3A8A;" onerror="this.src=\'https://ui-avatars.com/api/?name={current_user}\'"></div>', unsafe_allow_html=True)
with col_txt:
    st.title(f"Welcome, {current_user}")
    if st.button("🚪 Sign Out"):
        st.session_state.clear()
        st.rerun()

# --- 7. PROGRESS TRACKING ---
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

total_count = len(PROPOSALS)
done_count = len(completed_proposals)
st.write(f"**Evaluation Progress: {done_count} / {total_count}**")
st.progress(done_count / total_count if total_count > 0 else 0)
st.divider()

# --- 8. FORM LOGIC ---
if "proposal_selector" not in st.session_state:
    st.session_state.proposal_selector = "-- Select --"

selected_proposal = st.selectbox("Select Proposal Title", ["-- Select --"] + PROPOSALS, key="proposal_selector")

if selected_proposal != "-- Select --":
    query = "SELECT * FROM scores WHERE evaluator = :ev AND proposal_title = :prop LIMIT 1;"
    df_match = conn.query(query, params={"ev": current_user, "prop": selected_proposal}, ttl=0)
    existing_data = df_match.iloc[0] if not df_match.empty else None

    if "is_editing" not in st.session_state:
        st.session_state.is_editing = False

    if existing_data is not None and not st.session_state.is_editing:
        st.success(f"✅ Completed: {selected_proposal}")
        st.metric("Score", f"{existing_data['total']} / 5.0")
        col_edit, col_back = st.columns(2)
        col_edit.button("✏️ Edit Scores", use_container_width=True, on_click=enable_editing)
        col_back.button("⬅️ Back to Summary", use_container_width=True, on_click=nav_to_summary)
    else:
        with st.form("evaluation_form"):
            st.subheader(f"Evaluating: {selected_proposal}")
            inputs = {}
            for name, weight in CRITERIA:
                col_db = name.lower().replace(" ", "_")
                val = float(existing_data[col_db]) if existing_data is not None else 0.0
                inputs[name] = st.number_input(f"{name} ({int(weight*100)}%)", 0.0, 5.0, val, 0.1)
            
            user_comments = st.text_area("Comments", value=re.sub(r"\[MERGE WITH:.*?\] ", "", str(existing_data['comments']) if existing_data is not None else ""))
            recom_options = ["Pending", "Approve", "Revise", "Reject", "Combine/Merge"]
            cur_rec = str(existing_data['recommendation']) if existing_data is not None else "Pending"
            recom = st.radio("Recommendation", recom_options, index=recom_options.index(cur_rec) if cur_rec in recom_options else 0, horizontal=True)

            merge_target = None
            if recom == "Combine/Merge":
                other_proposals = [p for p in PROPOSALS if p != selected_proposal]
                merge_target = st.selectbox("Combine with:", other_proposals)

            if st.form_submit_button("📤 Submit", type="primary"):
                # Calculation Logic
                w_sum = sum(inputs[name] * weight for name, weight in CRITERIA)
                final_total = round(w_sum, 2)
                final_comm = f"[MERGE WITH: {merge_target}] {user_comments}" if recom == "Combine/Merge" else user_comments

                with conn.session as s:
                    s.execute(text("""INSERT INTO scores (evaluator, proposal_title, strategic_alignment, potential_impact, feasibility, budget_justification, timeline_readiness, execution_strategy, total, recommendation, comments, last_updated)
                        VALUES (:ev, :prop, :s1, :s2, :s3, :s4, :s5, :s6, :tot, :rec, :comm, :ts)
                        ON CONFLICT (evaluator, proposal_title) DO UPDATE SET total=EXCLUDED.total, recommendation=EXCLUDED.recommendation, comments=EXCLUDED.comments, last_updated=EXCLUDED.last_updated"""),
                        {"ev": current_user, "prop": selected_proposal, "s1": inputs['Strategic Alignment'], "s2": inputs['Potential Impact'], "s3": inputs['Feasibility'], "s4": inputs['Budget Justification'], "s5": inputs['Timeline Readiness'], "s6": inputs['Execution Strategy'], "tot": final_total, "rec": recom, "comm": final_comm, "ts": datetime.now()})
                    s.commit()
                st.success("Evaluation Saved!")
                time.sleep(1); st.rerun()
else:
    # --- 9. SUMMARY TABLE ---
    st.subheader("📊 Your Evaluation Summary")
    if not scored_df.empty:
        # Table sorting and display logic same as your previous version...
        st.dataframe(scored_df[["proposal_title", "total", "recommendation"]], use_container_width=True)
    
    # Remaining Proposals
    rem = [p for p in PROPOSALS if p not in completed_proposals]
    if rem:
        with st.expander(f"⏳ Remaining Proposals ({len(rem)})"):
            for p in rem:
                st.button(f"📝 Start: {p}", key=f"btn_{p}", use_container_width=True, on_click=nav_to_proposal, args=(p,))

    if not rem and total_count > 0:
        if st.button("🏁 Finalize and Close Session", type="primary", use_container_width=True):
            with conn.session as s:
                s.execute(text("UPDATE evaluators SET has_submitted = TRUE WHERE name = :name"), {"name": current_user})
                s.commit()
            st.rerun()


