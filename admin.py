import streamlit as st
import pandas as pd
import time
import re
import msal  
from io import BytesIO
from datetime import datetime
from sqlalchemy import text
from supabase import create_client
from streamlit_autorefresh import st_autorefresh
import extra_streamlit_components as stx

cookie_manager = stx.CookieManager(key="main_cookie_manager")

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

# Azure SSO Config
CLIENT_ID = load_secret("azure_client_id")
CLIENT_SECRET = load_secret("azure_client_secret")
TENANT_ID = load_secret("azure_tenant_id")
REDIRECT_URI = load_secret("azure_redirect_uri")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = ["User.Read"]

SUPABASE_URL = load_secret("supabase_url")
SUPABASE_KEY = load_secret("supabase_key")
BUCKET_NAME = "evaluator-photos"
conn = st.connection("postgresql", type="sql")

# --- 2. SSO & LOGIN LOGIC ---
def get_msal_app():
    return msal.ConfidentialClientApplication(
        CLIENT_ID, authority=AUTHORITY, client_credential=CLIENT_SECRET
    )

def check_password():
    # REMOVE this line: cookie_manager = stx.CookieManager()
    
    if st.session_state.get("authenticated"):
        return True

    # Use the globally defined cookie_manager
    saved_user = cookie_manager.get(cookie="asm_admin_user")
    if saved_user:
        # Verify user still exists in DB
        user_check = conn.query("SELECT username, role FROM users WHERE username = :u", params={"u": saved_user}, ttl=0)
        if not user_check.empty:
            st.session_state["authenticated"] = True
            st.session_state["username"] = user_check.iloc[0]['username']
            st.session_state["user_role"] = user_check.iloc[0]['role']
            return True

    # --- SSO / CODE LOGIC (Keep your existing code here) ---
    query_params = st.query_params
    if "code" in query_params:
        # ... (your existing msal code) ...
        # After successful login, set the cookie:
        # cookie_manager.set("asm_admin_user", email, expires_at=datetime.now() + timedelta(days=1))
        pass

    # --- LOGIN FORM ---
    st.markdown("<h1 style='text-align: center;'>🛡️ ASM Admin Access</h1>", unsafe_allow_html=True)
    _, center, _ = st.columns([1, 1.5, 1])
    
    with center:
        # (Your SSO button code)
        
        with st.form("login_form"):
            u_input = st.text_input("Local Username").strip()
            p_input = st.text_input("Local Password", type="password").strip()
            if st.form_submit_button("Sign In with Password", use_container_width=True):
                user_data = conn.query("SELECT username, password_hash, role FROM users WHERE LOWER(username) = LOWER(:u)", params={"u": u_input}, ttl=0)
                if not user_data.empty and str(user_data.iloc[0]['password_hash']) == p_input:
                    # ✅ SUCCESSFUL LOGIN
                    st.session_state["authenticated"] = True
                    st.session_state["username"] = user_data.iloc[0]['username']
                    st.session_state["user_role"] = user_data.iloc[0]['role']
                    
                    # ✅ SAVE COOKIE (lasts 1 day)
                    cookie_manager.set("asm_admin_user", user_data.iloc[0]['username'])
                    
                    st.rerun()
                else:
                    st.error("❌ Invalid Credentials")
    return False

if not check_password():
    st.stop()

# --- 3. INITIALIZE CLIENTS ---
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error(f"Supabase Connection Error: {e}")

# --- 4. THEME & CSS ---
st.markdown("""
    <style>
    .stApp { background-color: #FFFFFF !important; color: #000000 !important; }
    [data-testid="stMetricValue"] { color: #1E3A8A !important; }
    div[data-testid="stExpander"] { background-color: #F8F9FA !important; border: 1px solid #E5E7EB !important; }
    .eval-card { padding:15px; border-radius:10px; border: 1px solid #E2E8F0; text-align:center; margin-bottom:10px; min-height: 140px; }
    </style>
    """, unsafe_allow_html=True)

# --- 5. DIALOGS ---
@st.dialog("📚 Bulk Add Proposals")
def bulk_add_proposals_dialog():
    st.write("Paste your proposal titles below. Separate by **new lines** or **commas**.")
    raw_text = st.text_area("Proposals List", height=200, placeholder="Proposal A\nProposal B")
    
    if st.button("Add All Proposals", type="primary"):
        # 1. Split and Clean
        items = re.split(r'[\n,]+', raw_text)
        cleaned_items = [i.strip() for i in items if i.strip()]
        
        # 2. Validation
        if not cleaned_items:
            st.error("🚨 The list cannot be blank! Please enter at least one proposal title.")
        else:
            with conn.session as s:
                for title in cleaned_items:
                    s.execute(text("INSERT INTO proposals (title) VALUES (:val) ON CONFLICT DO NOTHING;"), 
                             {"val": title})
                s.commit()
            st.success(f"✅ Successfully added {len(cleaned_items)} proposals!")
            time.sleep(1)
            st.rerun()

@st.dialog("✏️ Edit Evaluator")
def edit_evaluator_dialog(old_name, old_nick, old_email, old_pwd):
    new_name = st.text_input("Full Name", value=str(old_name or ""))
    new_nick = st.text_input("Nickname", value=str(old_nick or ""))
    new_email = st.text_input("Email", value=str(old_email or ""))
    new_pwd = st.text_input("Access Password", value=str(old_pwd or ""))
    new_photo = st.file_uploader("Update Photo (Optional)", type=['png', 'jpg', 'jpeg'])
    
    if st.button("Save Changes", type="primary"):
        clean_name = new_name.strip() if new_name else ""
        clean_nick = new_nick.strip() if new_nick else ""
        clean_email = new_email.strip() if new_email else ""
        clean_pwd = new_pwd.strip() if new_pwd else ""
        
        if not clean_name:
            st.error("Name cannot be empty!")
            return

        with conn.session as s:
            s.execute(text("""
                UPDATE evaluators 
                SET name = :new, nickname = :nick, email = :em, password = :pw 
                WHERE name = :old
            """), {
                "new": clean_name, "nick": clean_nick, 
                "em": clean_email, "pw": clean_pwd, "old": old_name
            })
            s.execute(text("UPDATE scores SET evaluator = :new WHERE evaluator = :old"), {"new": clean_name, "old": old_name})
            s.commit()
        
        if new_photo:
            file_path = f"{clean_name.replace(' ', '_')}.png"
            supabase.storage.from_(BUCKET_NAME).upload(
                path=file_path, 
                file=new_photo.getvalue(), 
                file_options={"content-type": "image/png", "x-upsert": "true"}
            )
        
        st.success("Evaluator updated!")
        time.sleep(1)
        st.rerun()

@st.dialog("📧 Send Access Link")
def send_email_dialog(name, recipient_email, nickname):
    target_url = "https://asm-evaluation-system-10-evaluation-form.streamlit.app"
    link = f"{target_url}/?user={nickname.replace(' ', '%20')}"
    st.write(f"Sending personalized link to **{name}** at `{recipient_email}`")
    st.info(f"Link: {link}")
    if st.button("Confirm & Send via System", type="primary"):
        st.success(f"✅ Link sent to {recipient_email}")
        time.sleep(1)
        st.rerun()

@st.dialog("🔑 Add System User")
def add_user_dialog():
    new_un = st.text_input("New Username (or Email for SSO)")
    new_pw = st.text_input("New Password", type="password")
    new_role = st.selectbox("Role", ["SuperAdmin", "Editor", "Viewer"])
    if st.button("Create User", type="primary"):
        with conn.session as s:
            s.execute(text("INSERT INTO users (username, password_hash, role) VALUES (:u, :p, :r)"),
                      {"u": new_un.strip(), "p": new_pw.strip(), "r": new_role})
            s.commit()
        st.success("User added!")
        st.rerun()

@st.dialog("✏️ Edit System User")
def edit_user_dialog(user_id, current_un, current_role):
    new_un = st.text_input("Username", value=current_un)
    new_pw = st.text_input("New Password (blank to keep current)", type="password")
    new_role = st.selectbox("Role", ["SuperAdmin", "Editor", "Viewer"], 
                            index=["SuperAdmin", "Editor", "Viewer"].index(current_role))
    if st.button("Save Changes", type="primary"):
        with conn.session as s:
            if new_pw.strip():
                s.execute(text("UPDATE users SET username = :u, password_hash = :p, role = :r WHERE id = :id"),
                          {"u": new_un.strip(), "p": new_pw.strip(), "r": new_role, "id": user_id})
            else:
                s.execute(text("UPDATE users SET username = :u, role = :r WHERE id = :id"),
                          {"u": new_un.strip(), "r": new_role, "id": user_id})
            s.commit()
        st.rerun()

@st.dialog("🗑️ Delete System User")
def delete_user_confirm(user_id, username):
    st.warning(f"Delete admin '{username}'?")
    if username == st.session_state["username"]:
        st.error("You cannot delete your own account!")
    else:
        if st.button("Yes, Delete User", type="primary"):
            with conn.session as s:
                s.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
                s.commit()
            st.rerun()

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
            s.execute(text(f"DELETE FROM {table} WHERE {column} = :val"), {"val": value})
            s.commit()
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

# --- 6. HELPER FUNCTIONS ---
def get_items_sql(table, column):
    try:
        df = conn.query(f"SELECT {column} FROM {table} ORDER BY {column} ASC;", ttl=0)
        return df[column].dropna().tolist() if not df.empty else []
    except: return []

def add_item_sql(table, column, value):
    with conn.session as s:
        s.execute(text(f"INSERT INTO {table} ({column}) VALUES (:val) ON CONFLICT DO NOTHING;"), {"val": value.strip()})
        s.commit()

# --- 7. SIDEBAR NAVIGATION ---
cache_buster = int(time.time())

with st.sidebar:
    st.title("🛡️ ASM Admin")
    
    if st.button("🚪 Logout", use_container_width=True):
        cookie_manager.delete("asm_admin_user") 
        st.session_state["authenticated"] = False
        st.session_state["username"] = None
        st.rerun()
    
    st.divider()
    auto_refresh = st.toggle("🔄 Auto Refresh (15s)", value=False)
    if auto_refresh: 
        st_autorefresh(interval=15000, key="admin_refresh")
    
    menu_options = ["📊 Tracker", "📋 Proposals", "👤 Evaluators & Links", "📜 History"]
    if st.session_state.get("user_role") == "SuperAdmin":
        menu_options.append("🔑 User Management")
    
    menu_choice = st.radio("Navigate to:", menu_options)
    
    if st.session_state["user_role"] in ["SuperAdmin", "Editor"]:
        st.divider()
        st.subheader("🚀 Session Control")
        force_mode = st.toggle("⚠️ Enable Force Archive")
        if st.button("🆕 Archive & Reset", type="primary", use_container_width=True, disabled=not force_mode):
            with conn.session as s:
                s.execute(text("INSERT INTO scores_history SELECT *, NOW() as archive_timestamp FROM scores;"))
                s.execute(text("TRUNCATE TABLE scores RESTART IDENTITY CASCADE;"))
                s.commit()
            st.balloons()
            time.sleep(1)
            st.rerun()

# --- 8. MAIN CONTENT AREA ---

if menu_choice == "📊 Tracker":
    st.header("📊 Live Proposal Progress")
    df_scores = conn.query("SELECT * FROM scores;", ttl=0)
    props_all = get_items_sql("proposals", "title")
    evals_df = conn.query("SELECT name, nickname FROM evaluators ORDER BY name ASC;", ttl=0)
    
    total_props_count = len(props_all)
    total_required = total_props_count * len(evals_df)
    current_total_submissions = len(df_scores) if not df_scores.empty else 0

    if not df_scores.empty:
        numeric_cols = df_scores.select_dtypes(include=['number']).columns
        st.subheader("Current Session Averages")
        st.table(df_scores[numeric_cols].mean().round(2).rename("Global Avg"))
    
    if total_required > 0:
        st.divider()
        st.progress(min(current_total_submissions / total_required, 1.0))
        st.write(f"**Total System Progress:** {current_total_submissions} / {total_required} Evaluations Completed")

        st.subheader("Evaluator Status")
        cols = st.columns(4)
        for i, row in evals_df.iterrows():
            name = row['name']
            nick = row['nickname'] if row['nickname'] else name
            done_count = len(df_scores[df_scores['evaluator'] == name]) if not df_scores.empty else 0
            is_done = (done_count >= total_props_count) and total_props_count > 0
            bg = "#E6FFFA" if is_done else "#FFFBEB"
            border_col = '#38B2AC' if is_done else '#ECC94B'
            img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{name.replace(' ', '_')}.png?t={cache_buster}"
            
            with cols[i % 4]:
                st.markdown(f"""
                    <div class="eval-card" style="background-color:{bg}; border-top: 5px solid {border_col};">
                        <img src="{img_url}" style="width:50px; height:50px; border-radius:50%; object-fit:cover;" onerror="this.src='https://ui-avatars.com/api/?name={name}'">
                        <p style="font-weight:bold; margin:0; color:#333;">{nick}</p>
                        <p style="font-size:0.7em; color:#999;">{name}</p>
                        <p style="font-size:1.2em; font-weight:bold; color:#1E3A8A; margin:5px 0;">{done_count} / {total_props_count}</p>
                    </div>
                """, unsafe_allow_html=True)

elif menu_choice == "📋 Proposals":
    st.header("📋 Manage Proposals")
    
    if st.session_state["user_role"] != "Viewer":
        col_a, col_b = st.columns([1, 4])
        with col_a:
            if st.button("📚 Bulk Add"):
                bulk_add_proposals_dialog()
        
        with st.expander("➕ Add Single Proposal"):
            with st.form("add_proposal_form", clear_on_submit=True):
                p_name = st.text_input("Proposal Title*") # Added asterisk
                if st.form_submit_button("Add Single"):
                    # 3. Validation: Check if the single title is blank
                    if not p_name.strip():
                        st.error("🚨 Proposal title cannot be blank!")
                    else:
                        add_item_sql("proposals", "title", p_name.strip())
                        st.success("✅ Proposal added!")
                        time.sleep(1)
                        st.rerun()
    
    st.divider()
    
    # List and Manage Proposals
    props = get_items_sql("proposals", "title")
    if not props:
        st.info("No proposals found. Use the buttons above to add some.")
    else:
        for p in props:
            c1, c2, c3 = st.columns([5, 1, 1])
            c1.write(f"• {p}")
            if st.session_state["user_role"] in ["SuperAdmin", "Editor"]:
                if c2.button("✏️", key=f"edit_p_{p}"): edit_proposal_dialog(p)
                if c3.button("🗑️", key=f"del_p_{p}"): confirm_delete_dialog("proposals", "title", p)

elif menu_choice == "👤 Evaluators & Links":
    st.header("👤 Evaluators & Access Links")
    
    # Line 401: The IF statement
    if st.session_state["user_role"] != "Viewer":
        # Line 402: This MUST be indented (4 spaces or 1 tab)
        with st.expander("➕ Add New Evaluator"):
            with st.form("eval_form", clear_on_submit=True):
                col1, col2 = st.columns(2)
                e_name = col1.text_input("Full Name*")
                e_nick = col1.text_input("Nickname*")
                e_mail = col2.text_input("Primary Email*")
                e_pass = col2.text_input("Assign Password*")
                e_file = st.file_uploader("Photo (Optional)", type=['png', 'jpg'])
                
                if st.form_submit_button("Create Evaluator", use_container_width=True):
                    # Validation: Cannot be blank
                    if not e_name.strip() or not e_nick.strip() or not e_mail.strip() or not e_pass.strip():
                        st.error("🚨 All fields marked with * are required.")
                    else:
                        with conn.session as s:
                            s.execute(text("""
                                INSERT INTO evaluators (name, nickname, email, password, has_submitted) 
                                VALUES (:n, :nk, :em, :pw, FALSE)
                            """), {"n": e_name.strip(), "nk": e_nick.strip(), "em": e_mail.strip(), "pw": e_pass.strip()})
                            s.commit()
                        
                        if e_file:
                            file_path = f"{e_name.strip().replace(' ', '_')}.png"
                            supabase.storage.from_(BUCKET_NAME).upload(
                                path=file_path, 
                                file=e_file.getvalue(), 
                                file_options={"content-type": "image/png", "x-upsert": "true"}
                            )
                        st.success("Evaluator created!")
                        time.sleep(1)
                        st.rerun()
    st.divider()
    st.subheader("🔓 Access Control & Identity Mapping")
    status_df = conn.query("SELECT * FROM evaluators ORDER BY name ASC;", ttl=0)
    
    for _, row in status_df.iterrows():
        e = row['name']
        nick = row['nickname']
        pers_email = row.get('email', '')
        pwd = row.get('password', '')
        is_locked = bool(row['has_submitted'])
        
        c1, c2, c3, c4, c5, c6 = st.columns([0.5, 2.5, 1.5, 0.8, 0.8, 0.8])
        
        img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{e.replace(' ', '_')}.png?t={cache_buster}"
        c1.markdown(f'<img src="{img_url}" style="width:40px; height:40px; border-radius:50%; object-fit:cover;" onerror="this.src=\'https://ui-avatars.com/api/?name={e}\'">', unsafe_allow_html=True)
        
        with c2:
            st.write(f"**{nick}**")
            st.caption(f"📧 {pers_email} | {'🔒 LOCKED' if is_locked else '🔓 OPEN'}")
        
        with c3:
            st.caption("Access Password:")
            st.write(f"`{pwd if pwd else 'None Set'}`")

        if st.session_state["user_role"] in ["SuperAdmin", "Editor"]:
            if c4.button("✏️", key=f"edit_eval_btn_{e}"):
                edit_evaluator_dialog(e, nick, pers_email, pwd)
            if c5.button("📧", key=f"link_send_{e}"):
                send_email_dialog(e, pers_email, nick)
            if c6.button("🔄", key=f"unlock_re_{e}"):
                with conn.session as s:
                    s.execute(text("UPDATE evaluators SET has_submitted = FALSE WHERE name = :n"), {"n": e})
                    s.commit()
                st.rerun()

elif menu_choice == "🔑 User Management":
    st.header("🔑 System Admin Accounts")
    if st.button("➕ Add New Admin"):
        add_user_dialog()
    
    users_df = conn.query("SELECT id, username, role, sso_email FROM users ORDER BY id ASC;", ttl=0)
    for _, row in users_df.iterrows():
        c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
        with c1:
            st.write(f"👤 {row['username']}")
            st.caption(f"MS Auth: {row['sso_email'] or 'None'}")
        c2.write(f"**{row['role']}**")
        if c3.button("✏️", key=f"edit_u_{row['id']}"):
            edit_user_dialog(row['id'], row['username'], row['role'])
        if c4.button("🗑️", key=f"del_u_{row['id']}"):
            delete_user_confirm(row['id'], row['username'])

elif menu_choice == "📜 History":
    st.header("📜 Archived Evaluations")
    df_hist = conn.query("SELECT * FROM scores_history ORDER BY archive_timestamp DESC;", ttl=0)
    st.dataframe(df_hist, use_container_width=True)

