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

# Initialize Cookie Manager
cookie_manager = stx.CookieManager(key="main_cookie_manager")

# --- 1. CONFIG & CONNECTIONS ---
st.set_page_config(page_title="ASM Admin Panel", layout="wide")
cache_buster = datetime.now().strftime("%Y%m%d%H%M%S")

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

# Azure & DB Config
CLIENT_ID = load_secret("azure_client_id")
CLIENT_SECRET = load_secret("azure_client_secret")
TENANT_ID = load_secret("azure_tenant_id")
SUPABASE_URL = load_secret("supabase_url")
SUPABASE_KEY = load_secret("supabase_key")
BUCKET_NAME = "evaluator-photos"
conn = st.connection("postgresql", type="sql")

# --- 2. HELPER FUNCTIONS (CRITICAL FIX: Added missing functions) ---
def get_items_sql(table, column):
    try:
        df = conn.query(f"SELECT {column} FROM {table} ORDER BY {column} ASC;", ttl=0)
        return df[column].dropna().tolist() if not df.empty else []
    except Exception as e:
        st.error(f"DB Error (get_items): {e}")
        return []

def add_item_sql(table, column, value):
    try:
        with conn.session as s:
            s.execute(text(f"INSERT INTO {table} ({column}) VALUES (:val) ON CONFLICT DO NOTHING;"), {"val": value.strip()})
            s.commit()
    except Exception as e:
        st.error(f"DB Error (add_item): {e}")

# --- 3. LOGIN LOGIC ---
def check_password():
    if st.session_state.get("authenticated"):
        return True
    saved_user = cookie_manager.get(cookie="asm_admin_user")
    if saved_user:
        user_check = conn.query("SELECT username, role FROM users WHERE username = :u", params={"u": saved_user}, ttl=0)
        if not user_check.empty:
            st.session_state["authenticated"] = True
            st.session_state["username"] = user_check.iloc[0]['username']
            st.session_state["user_role"] = user_check.iloc[0]['role']
            return True
    
    st.markdown("<h1 style='text-align: center;'>🛡️ ASM Admin Access</h1>", unsafe_allow_html=True)
    _, center, _ = st.columns([1, 1.5, 1])
    with center:
        with st.form("login_form"):
            u_input = st.text_input("Username").strip()
            p_input = st.text_input("Password", type="password").strip()
            if st.form_submit_button("Sign In", use_container_width=True):
                user_data = conn.query("SELECT username, password_hash, role FROM users WHERE LOWER(username) = LOWER(:u)", params={"u": u_input}, ttl=0)
                if not user_data.empty and str(user_data.iloc[0]['password_hash']) == p_input:
                    st.session_state.update({"authenticated": True, "username": user_data.iloc[0]['username'], "user_role": user_data.iloc[0]['role']})
                    cookie_manager.set("asm_admin_user", user_data.iloc[0]['username'])
                    st.rerun()
                else:
                    st.error("❌ Invalid Credentials")
    return False

if not check_password():
    st.stop()

# --- 4. INITIALIZE SUPABASE ---
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error(f"Supabase Connection Error: {e}")

# --- 5. SIDEBAR NAVIGATION ---
with st.sidebar:
    st.title("🛡️ ASM Admin")
    st.subheader("📍 Navigation")
    
    # Path handling to prevent url_pathname KeyError
    try:
        st.page_link("admin.py", label="Home Dashboard", icon="🏠")
    except:
        if st.button("🏠 Home"): st.switch_page("admin.py")
        
    try:
        st.page_link("pages/📊_reports.py", label="Detailed Reports", icon="📊")
    except:
        st.caption("Detailed Reports (unavailable)")

    st.divider()
    menu_options = ["📊 Tracker", "📋 Proposals", "👤 Evaluators & Links", "📜 History"]
    if st.session_state.get("user_role") == "SuperAdmin":
        menu_options.append("🔑 User Management")
    menu_choice = st.radio("Go to Section:", menu_options)
    
    st.divider()
    if st.button("🚪 Logout", use_container_width=True):
        cookie_manager.delete("asm_admin_user")
        st.session_state.clear()
        st.rerun()

# --- 6. MAIN CONTENT ---
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
        
        # Adjusting column widths to fit the extra button (added a 7th column c7)
        c1, c2, c3, c4, c5, c6, c7 = st.columns([0.5, 2.5, 1.5, 0.6, 0.6, 0.6, 0.6])
        
        img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{e.replace(' ', '_')}.png?t={cache_buster}"
        c1.markdown(f'<img src="{img_url}" style="width:40px; height:40px; border-radius:50%; object-fit:cover;" onerror="this.src=\'https://ui-avatars.com/api/?name={e}\'">', unsafe_allow_html=True)
        
        with c2:
            st.write(f"**{nick}**")
            st.caption(f"📧 {pers_email} | {'🔒 LOCKED' if is_locked else '🔓 OPEN'}")
        
        with c3:
            st.caption("Access Password:")
            st.write(f"`{pwd if pwd else 'None Set'}`")

        if st.session_state["user_role"] in ["SuperAdmin", "Editor"]:
            # Edit Button
            if c4.button("✏️", key=f"edit_eval_btn_{e}", help="Edit Details"):
                edit_evaluator_dialog(e, nick, pers_email, pwd)
            
            # Email Link Button
            if c5.button("📧", key=f"link_send_{e}", help="Send Link"):
                send_email_dialog(e, pers_email, nick)
            
            # Unlock Button
            if c6.button("🔄", key=f"unlock_re_{e}", help="Unlock Submission"):
                with conn.session as s:
                    s.execute(text("UPDATE evaluators SET has_submitted = FALSE WHERE name = :n"), {"n": e})
                    s.commit()
                st.rerun()
            
            # NEW: Delete Button 🗑️
            if c7.button("🗑️", key=f"del_eval_{e}", help="Delete Evaluator"):
                confirm_delete_dialog("evaluators", "name", e)

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

