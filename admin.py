import streamlit as st
import pandas as pd
import time
import msal  
from io import BytesIO
from datetime import datetime
from sqlalchemy import text
from supabase import create_client
from streamlit_autorefresh import st_autorefresh

# --- 1. CONFIG & CONNECTIONS ---
st.set_page_config(page_title="ASM Admin Panel", layout="wide")

# Initialize Session States
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "username" not in st.session_state:
    st.session_state["username"] = None
if "user_role" not in st.session_state:
    st.session_state["user_role"] = "Viewer"

def load_secret(key):
    if key in st.secrets:
        return st.secrets[key]
    st.error(f"❌ Missing Secret: **{key}**")
    st.stop()

# Load Secrets
CLIENT_ID = load_secret("azure_client_id")
CLIENT_SECRET = load_secret("azure_client_secret")
TENANT_ID = load_secret("azure_tenant_id")
REDIRECT_URI = load_secret("azure_redirect_uri")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = ["User.Read"]

SUPABASE_URL = load_secret("supabase_url")
SUPABASE_KEY = load_secret("supabase_key")
BUCKET_NAME = "evaluator-photos"

# Establish Connections
conn = st.connection("postgresql", type="sql")
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except:
    st.error("Supabase Connection Error.")

# --- 2. SSO & LOGIN LOGIC ---
def get_msal_app():
    return msal.ConfidentialClientApplication(
        CLIENT_ID, authority=AUTHORITY, client_credential=CLIENT_SECRET
    )

def check_password():
    if st.session_state.get("authenticated"):
        return True

    # Handle SSO Callback Redirect
    query_params = st.query_params
    if "code" in query_params:
        app = get_msal_app()
        result = app.acquire_token_by_authorization_code(
            query_params["code"], 
            scopes=SCOPE, 
            redirect_uri=REDIRECT_URI
        )
        if "error" not in result:
            email = result.get("id_token_claims").get("preferred_username")
            user_check = conn.query("SELECT username, role FROM users WHERE LOWER(username) = LOWER(:u)", params={"u": email}, ttl=0)
            
            if not user_check.empty:
                st.session_state["authenticated"] = True
                st.session_state["username"] = user_check.iloc[0]['username']
                st.session_state["user_role"] = user_check.iloc[0]['role']
                st.query_params.clear()
                st.rerun()
            else:
                st.error(f"🚫 Access Denied: {email} is not authorized.")
        else:
            st.error(f"Authentication Failed: {result.get('error_description')}")

    # --- LOGIN UI ---
    st.markdown("<h1 style='text-align: center;'>🛡️ ASM Admin Access</h1>", unsafe_allow_html=True)
    _, center, _ = st.columns([1, 1.5, 1])
    
    with center:
        msal_app = get_msal_app()
        auth_url = msal_app.get_authorization_request_url(SCOPE, redirect_uri=REDIRECT_URI)
        
        # primary blue button for Microsoft
        st.link_button(
            "󰊯 Sign in with Microsoft 365", 
            auth_url, 
            type="primary", 
            use_container_width=True
        )

        st.markdown("<p style='text-align: center; color: gray; margin: 15px 0;'>- OR -</p>", unsafe_allow_html=True)

        with st.form("login_form"):
            u_input = st.text_input("Local Username").strip()
            p_input = st.text_input("Local Password", type="password").strip()
            if st.form_submit_button("Sign In with Password", use_container_width=True):
                user_data = conn.query("SELECT username, password_hash, role FROM users WHERE LOWER(username) = LOWER(:u)", params={"u": u_input}, ttl=0)
                if not user_data.empty and str(user_data.iloc[0]['password_hash']) == p_input:
                    st.session_state["authenticated"] = True
                    st.session_state["username"] = user_data.iloc[0]['username']
                    st.session_state["user_role"] = user_data.iloc[0]['role']
                    st.rerun()
                else:
                    st.error("❌ Invalid Credentials")
    return False

if not check_password():
    st.stop()

# --- 3. THEME & CSS ---
st.markdown("""
    <style>
    .stApp { background-color: #FFFFFF !important; color: #000000 !important; }
    [data-testid="stMetricValue"] { color: #1E3A8A !important; }
    div[data-testid="stExpander"] { background-color: #F8F9FA !important; border: 1px solid #E5E7EB !important; }
    .eval-card {
        padding:15px; border-radius:10px; border: 1px solid #E2E8F0; 
        text-align:center; margin-bottom:10px; min-height: 140px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 4. DIALOGS (MANAGE LOGIC) ---
@st.dialog("📧 Send Access Link")
def send_email_dialog(name, recipient_email, nickname):
    target_url = "https://asm-evaluation-system-10-evaluation-form.streamlit.app"
    link = f"{target_url}/?user={nickname.replace(' ', '%20')}"
    st.write(f"Sending personalized link to **{name}** at `{recipient_email}`")
    st.info(f"Link: {link}")
    if st.button("Confirm & Send via System", type="primary"):
        st.success(f"✅ Link sent to {recipient_email}")
        time.sleep(1); st.rerun()

@st.dialog("✏️ Edit Evaluator")
def edit_evaluator_dialog(old_name, old_nick):
    new_name = st.text_input("Full Name", value=old_name)
    new_nick = st.text_input("Nickname", value=old_nick)
    new_photo = st.file_uploader("Update Photo (Optional)", type=['png', 'jpg', 'jpeg'])
    if st.button("Save Changes", type="primary"):
        clean_new = new_name.strip()
        with conn.session as s:
            s.execute(text("UPDATE evaluators SET name = :new, nickname = :nick WHERE name = :old"), 
                      {"new": clean_new, "nick": new_nick.strip(), "old": old_name})
            s.execute(text("UPDATE scores SET evaluator = :new WHERE evaluator = :old"), {"new": clean_new, "old": old_name})
            s.commit()
        if new_photo:
            file_path = f"{clean_new.replace(' ', '_')}.png"
            supabase.storage.from_(BUCKET_NAME).upload(path=file_path, file=new_photo.getvalue(), file_options={"content-type": "image/png", "x-upsert": "true"})
        st.rerun()

@st.dialog("✏️ Edit Proposal")
def edit_proposal_dialog(old_val):
    new_val = st.text_input("Edit Proposal Title", value=old_val)
    if st.button("Update Title", type="primary"):
        with conn.session as s:
            s.execute(text("UPDATE proposals SET title = :new WHERE title = :old"), {"new": new_val.strip(), "old": old_val})
            s.execute(text("UPDATE scores SET proposal_title = :new WHERE proposal_title = :old"), {"new": new_val.strip(), "old": old_val})
            s.commit()
        st.rerun()

@st.dialog("🔑 User Credentials")
def reset_password_dialog(username):
    new_pw = st.text_input("New Password", type="password")
    if st.button("Update Password", type="primary"):
        with conn.session as s:
            s.execute(text("UPDATE users SET password_hash = :p WHERE username = :u"), {"p": new_pw.strip(), "u": username}); s.commit()
        st.success("Password updated!"); st.rerun()

@st.dialog("🗑️ Confirm Delete")
def confirm_delete_dialog(table, column, value):
    st.warning(f"Delete '{value}' permanently?")
    if st.button("Yes, Delete", type="primary"):
        if table == "evaluators":
            try:
                file_path = f"{value.strip().replace(' ', '_')}.png"
                supabase.storage.from_(BUCKET_NAME).remove([file_path])
            except: pass
        with conn.session as s:
            s.execute(text(f"DELETE FROM {table} WHERE {column} = :val"), {"val": value}); s.commit()
        st.rerun()

# --- 5. HELPER FUNCTIONS ---
def get_items_sql(table, column):
    try:
        df = conn.query(f"SELECT {column} FROM {table} ORDER BY {column} ASC;", ttl=0)
        return df[column].dropna().tolist() if not df.empty else []
    except: return []

def add_item_sql(table, column, value):
    with conn.session as s:
        s.execute(text(f"INSERT INTO {table} ({column}) VALUES (:val) ON CONFLICT DO NOTHING;"), {"val": value.strip()}); s.commit()

# --- 6. SIDEBAR NAVIGATION ---
cache_buster = int(time.time())
with st.sidebar:
    st.title("🛡️ ASM Admin")
    st.write(f"User: **{st.session_state['username']}**")
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state["authenticated"] = False; st.rerun()
    st.divider()
    menu_options = ["📊 Tracker", "📋 Proposals", "👤 Evaluators & Links", "📜 History"]
    if st.session_state["user_role"] == "SuperAdmin": menu_options.append("🔑 User Management")
    menu_choice = st.radio("Navigate to:", menu_options)
    
    # Session Control (Force Reset)
    if st.session_state["user_role"] in ["SuperAdmin", "Editor"]:
        st.divider()
        st.subheader("🚀 Session Control")
        force_mode = st.toggle("⚠️ Enable Force Archive")
        if st.button("🆕 Archive & Reset", type="primary", use_container_width=True, disabled=not force_mode):
            with conn.session as s:
                s.execute(text("INSERT INTO scores_history SELECT *, NOW() as archive_timestamp FROM scores;"))
                s.execute(text("TRUNCATE TABLE scores RESTART IDENTITY CASCADE;"))
                s.commit()
            st.balloons(); time.sleep(1); st.rerun()

# --- 7. MAIN CONTENT ---

if menu_choice == "📊 Tracker":
    st.header("📊 Live Proposal Progress")
    df_scores = conn.query("SELECT * FROM scores;", ttl=0)
    props_all = get_items_sql("proposals", "title")
    evals_df = conn.query("SELECT name, nickname FROM evaluators ORDER BY name ASC;", ttl=0)
    
    total_props = len(props_all)
    total_evals = len(evals_df)
    total_req = total_props * total_evals
    current_sub = len(df_scores) if not df_scores.empty else 0

    if total_req > 0:
        st.progress(min(current_sub / total_req, 1.0))
        st.write(f"**Total Progress:** {current_sub} / {total_req} Evaluations")

    cols = st.columns(4)
    for i, row in evals_df.iterrows():
        name, nick = row['name'], (row['nickname'] or row['name'])
        done = len(df_scores[df_scores['evaluator'] == name]) if not df_scores.empty else 0
        img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{name.replace(' ', '_')}.png?t={cache_buster}"
        with cols[i % 4]:
            st.markdown(f"""<div class="eval-card" style="background-color:#F8F9FA; border-top: 5px solid #1E3A8A;">
                <img src="{img_url}" style="width:50px; height:50px; border-radius:50%; object-fit:cover;" onerror="this.src='https://ui-avatars.com/api/?name={name}'">
                <p style="font-weight:bold; margin:0;">{nick}</p>
                <p style="font-size:1.2em; font-weight:bold; color:#1E3A8A;">{done} / {total_props}</p>
            </div>""", unsafe_allow_html=True)

elif menu_choice == "👤 Evaluators & Links":
    st.header("👤 Evaluators & Access Links")
    with st.expander("➕ Add New Evaluator"):
        with st.form("eval_form", clear_on_submit=True):
            e_name = st.text_input("Full Name")
            e_nick = st.text_input("Nickname")
            e_mail = st.text_input("Email")
            e_file = st.file_uploader("Photo", type=['png', 'jpg'])
            if st.form_submit_button("Create Evaluator"):
                if e_name and e_nick:
                    with conn.session as s:
                        s.execute(text("INSERT INTO evaluators (name, nickname, email, has_submitted) VALUES (:n, :nk, :em, FALSE)"), 
                                  {"n": e_name.strip(), "nk": e_nick.strip(), "em": e_mail.strip()}); s.commit()
                    if e_file:
                        file_path = f"{e_name.strip().replace(' ', '_')}.png"
                        supabase.storage.from_(BUCKET_NAME).upload(path=file_path, file=e_file.getvalue(), file_options={"content-type": "image/png"})
                    st.rerun()

    st.divider()
    status_df = conn.query("SELECT * FROM evaluators ORDER BY name ASC;", ttl=0)
    for _, row in status_df.iterrows():
        e, nick, mail = row['name'], row['nickname'], row.get('email', 'No Email')
        is_locked = bool(row['has_submitted'])
        c1, c2, c3, c4, c5 = st.columns([1, 3, 2, 1, 1])
        img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{e.replace(' ', '_')}.png?t={cache_buster}"
        c1.markdown(f'<img src="{img_url}" style="width:40px; height:40px; border-radius:50%; object-fit:cover;" onerror="this.src=\'https://ui-avatars.com/api/?name={e}\'">', unsafe_allow_html=True)
        with c2:
            st.write(f"**{nick}** ({e})")
            st.caption(f"Status: {'🔒 LOCKED' if is_locked else '🔓 OPEN'}")
        c3.write(f"`{mail}`")
        if c4.button("✏️", key=f"ed_{e}"): edit_evaluator_dialog(e, nick)
        if c5.button("🗑️", key=f"dl_{e}"): confirm_delete_dialog("evaluators", "name", e)

elif menu_choice == "📋 Proposals":
    st.header("📋 Manage Proposals")
    p_name = st.text_input("Add Proposal Title")
    if st.button("Add Single"):
        if p_name: add_item_sql("proposals", "title", p_name); st.rerun()
    st.divider()
    props = get_items_sql("proposals", "title")
    for p in props:
        c1, c2, c3 = st.columns([5, 1, 1])
        c1.write(f"• {p}")
        if c2.button("✏️", key=f"ep_{p}"): edit_proposal_dialog(p)
        if c3.button("🗑️", key=f"dp_{p}"): confirm_delete_dialog("proposals", "title", p)

elif menu_choice == "📜 History":
    st.header("📜 Archived Evaluations")
    df_hist = conn.query("SELECT * FROM scores_history ORDER BY archive_timestamp DESC;", ttl=0)
    st.dataframe(df_hist, use_container_width=True)

elif menu_choice == "🔑 User Management":
    st.header("🔑 System Admin Accounts")
    users_df = conn.query("SELECT id, username, role FROM users ORDER BY id ASC;", ttl=0)
    for _, row in users_df.iterrows():
        c1, c2, c3 = st.columns([3, 1, 1])
        c1.write(f"👤 {row['username']} ({row['role']})")
        if c2.button("🔑", key=f"pw_{row['id']}"): reset_password_dialog(row['username'])
        if c3.button("🗑️", key=f"du_{row['id']}"): confirm_delete_dialog("users", "id", row['id'])
