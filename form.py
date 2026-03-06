import streamlit as st
import pandas as pd
import time
import re
import msal
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

st.set_page_config(page_title="ASM Evaluator Entry", layout="wide")

# --- 2. DATABASE & SSO CONFIG ---
conn = st.connection("postgresql", type="sql")

def load_secret(key):
    if key in st.secrets: return st.secrets[key]
    st.error(f"❌ Missing Secret: {key}"); st.stop()

CLIENT_ID = load_secret("azure_client_id")
CLIENT_SECRET = load_secret("azure_client_secret")
TENANT_ID = load_secret("azure_tenant_id")
REDIRECT_URI = load_secret("azure_redirect_uri")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = ["User.Read"]

# --- 3. DUAL LOGIN LOGIC ---
def get_msal_app():
    return msal.ConfidentialClientApplication(CLIENT_ID, authority=AUTHORITY, client_credential=CLIENT_SECRET)

def check_password():
    if st.session_state.get("authenticated"):
        return True

    # --- HANDLE SSO CALLBACK ---
    query_params = st.query_params
    if "code" in query_params:
        app = get_msal_app()
        result = app.acquire_token_by_authorization_code(query_params["code"], scopes=SCOPE, redirect_uri=REDIRECT_URI)
        if "error" not in result:
            sso_email = result.get("id_token_claims").get("preferred_username")
            sso_name = result.get("id_token_claims").get("name")
            
            st.session_state["authenticated"] = True
            st.session_state["sso_info"] = {"email": sso_email, "name": sso_name}
            
            # IDENTITY MAPPING: Update evaluator record with their SSO email
            user_id = query_params.get("user")
            if user_id:
                with conn.session as s:
                    s.execute(text("UPDATE evaluators SET sso_email = :sso WHERE nickname = :nick OR name = :nick"), 
                             {"sso": sso_email, "nick": user_id})
                    s.commit()
            
            st.query_params.clear()
            if user_id: st.query_params["user"] = user_id
            st.rerun()

    # Login UI
   st.markdown("<h1 style='text-align: center;'>🛡️ ASM Evaluator Access</h1>", unsafe_allow_html=True)
    _, center, _ = st.columns([1, 1.5, 1])
    with center:
        msal_app = get_msal_app()
        auth_url = msal_app.get_authorization_request_url(SCOPE, redirect_uri=REDIRECT_URI)
        st.link_button("󰊯 Sign in with Microsoft 365", auth_url, type="primary", use_container_width=True)

        st.markdown("<p style='text-align: center; color: gray; margin: 10px 0;'>- OR -</p>", unsafe_allow_html=True)

        with st.form("local_login"):
            p_input = st.text_input("Access Password", type="password")
            if st.form_submit_button("Enter with Password", use_container_width=True):
                pass_df = conn.query("SELECT value FROM settings WHERE key = 'evaluator_password' LIMIT 1", ttl=0)
                if not pass_df.empty and p_input == pass_df.iloc[0]['value']:
                    st.session_state["authenticated"] = True
                    st.session_state["sso_info"] = None
                    st.rerun()
                else:
                    st.error("❌ Incorrect Password")
    return False

if not check_password(): st.stop()

# --- 9. HEADER (Modified to show SSO) ---
# ... (Keep existing user identification logic) ...
col_img, col_txt, col_auth = st.columns([1, 2.5, 1.5])
# ... (Profile image/title logic) ...
with col_auth:
    sso = st.session_state.get("sso_user")
    if sso:
        st.info(f"Verified: {sso['name']}\n{sso['email']}")
    else:
        st.warning("Logged in via Password")
    if st.button("Logout"):
        st.session_state["authenticated"] = False
        st.rerun()

st.divider()

# --- 9. HEADER ---
cache_buster = int(datetime.now().timestamp())
col_img, col_txt, col_auth = st.columns([1, 2.5, 1.5])

with col_img:
    # ... existing image logic ...

with col_txt:
    st.title(f"Welcome, {current_user}")
    st.write("Official ASM Evaluation Portal")

with col_auth:
    sso = st.session_state.get("sso_info")
    if sso:
        st.success(f"Verified: {sso['name']}")
        st.caption(f"MS: {sso['email']}")
    else:
        st.warning("Logged in via Password")
    
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()

# --- 10. PROGRESS DATA FETCH ---
try:
    scored_df = conn.query("SELECT proposal_title, total, recommendation, comments FROM scores WHERE evaluator = :ev", params={"ev": current_user}, ttl=0)
    completed_proposals = scored_df['proposal_title'].tolist() if not scored_df.empty else []
    
    # Extract Merge Target from comments
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
                inputs[name] = st.number_input(f"{name} ({int(weight*100)}%)", 0.0, 5.0, default_val, 0.1)
                if inputs[name] > 0: criteria_met += 1
            
            st.write(f"Criteria Completed: {criteria_met}/{len(CRITERIA)}")
            st.progress(criteria_met / len(CRITERIA))

            # Raw comment handling
            raw_comm = str(existing_data['comments']) if existing_data is not None else ""
            clean_comm = re.sub(r"\[MERGE WITH:.*?\] ", "", raw_comm)
            user_comments = st.text_area("Comments / Remarks", value=clean_comm)
            
            recom_options = ["Pending", "Approve", "Revise", "Reject", "Combine/Merge"]
            current_rec = str(existing_data['recommendation']) if existing_data is not None else "Pending"
            recom = st.radio("Recommendation", recom_options, 
                             index=recom_options.index(current_rec) if current_rec in recom_options else 0, 
                             horizontal=True)
            
            merge_target = None
            if recom == "Combine/Merge":
                existing_target = extract_merge_target(raw_comm)
                other_proposals = [p for p in PROPOSALS if p != selected_proposal]
                try:
                    target_idx = other_proposals.index(existing_target)
                except:
                    target_idx = 0
                merge_target = st.selectbox("Combine with which proposal?", other_proposals, index=target_idx)

            col_sub, col_can = st.columns(2)
            with col_sub:
                submit = st.form_submit_button("📤 Submit Evaluation", use_container_width=True, type="primary")
            with col_can:
                cancel = st.form_submit_button("❌ Cancel", use_container_width=True)

            if submit:
                w_sum = sum(inputs[name] * weight for name, weight in CRITERIA if inputs[name] > 0)
                w_used = sum(weight for name, weight in CRITERIA if inputs[name] > 0)
                final_total = round(w_sum / w_used, 2) if w_used > 0 else 0.0

                final_comments = user_comments
                if recom == "Combine/Merge" and merge_target:
                    final_comments = f"[MERGE WITH: {merge_target}] {user_comments}"

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
                               "s6": inputs['Execution Strategy'], "tot": final_total, "rec": recom, "comm": final_comments, "ts": datetime.now()})
                    s.commit()
                
                st.session_state.pending_nav = True
                st.success("Evaluation Saved!")
                time.sleep(1)
                st.rerun()

else:
    # --- 13. SUMMARY DASHBOARD ---
    st.subheader("📊 Your Evaluation Summary")
    
    if not scored_df.empty:
        summary_display = scored_df.copy()

        # Sort Logic: MERGE (1) -> Others
        def get_status_info(rec):
            if rec == "Combine/Merge": return "🔵 MERGE", 1
            if rec == "Approve": return "🟢 Approve", 2
            if rec == "Revise": return "🟡 Revise", 3
            if rec == "Reject": return "🔴 Reject", 4
            return "⚪ Pending", 5

        status_data = summary_display["recommendation"].apply(get_status_info)
        summary_display["Status"] = [x[0] for x in status_data]
        summary_display["sort_priority"] = [x[1] for x in status_data]
        
        summary_display = summary_display.rename(columns={
            "proposal_title": "Proposal Name", 
            "total": "Score", 
            "merge_target": "Combined With",
            "display_comments": "Remarks"
        })

        # Sort and Drop helper
        summary_display = summary_display.sort_values("sort_priority").drop(columns=["sort_priority"])

        display_cols = ["Status", "Proposal Name", "Combined With", "Score", "Remarks"]
        summary_display = summary_display[display_cols]

        st.dataframe(
            summary_display, 
            use_container_width=True, 
            hide_index=True, 
            on_select="rerun", 
            selection_mode="single-row", 
            key="summary_table",
            column_config={
                "Status": st.column_config.TextColumn(width="small"),
                "Combined With": st.column_config.TextColumn(width="medium"),
                "Score": st.column_config.ProgressColumn(
                    "Score",
                    format="%.1f",
                    min_value=0,
                    max_value=5,
                ),
                "Remarks": st.column_config.TextColumn(width="large"),
                "Proposal Name": st.column_config.TextColumn(width="medium"),
            }
        )
    else:
        st.info("No proposals evaluated yet.")

    remaining = [p for p in PROPOSALS if p not in completed_proposals]
    if remaining:
        with st.expander(f"⏳ View Remaining Proposals ({len(remaining)})"):
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





