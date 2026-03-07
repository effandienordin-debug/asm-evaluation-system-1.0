import streamlit as st
import pandas as pd
import time
import re
from datetime import datetime
from sqlalchemy import text
from supabase import create_client
from streamlit_autorefresh import st_autorefresh
import extra_streamlit_components as stx

# --- 1. INITIALIZATION ---
cookie_manager = stx.CookieManager(key="main_cookie_manager")
st.set_page_config(page_title="ASM Admin Panel", layout="wide")
cache_buster = datetime.now().strftime("%Y%m%d%H%M%S")

if "authenticated" not in st.session_state:
    st.session_state.update({"authenticated": False, "username": None, "user_role": "Viewer"})

def load_secret(key):
    if key in st.secrets: return st.secrets[key]
    st.error(f"❌ Missing Secret: **{key}**"); st.stop()

# Connections
SUPABASE_URL = load_secret("supabase_url")
SUPABASE_KEY = load_secret("supabase_key")
BUCKET_NAME = "evaluator-photos"
conn = st.connection("postgresql", type="sql")

try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error(f"Supabase Connection Error: {e}")

# --- 2. DATABASE HELPERS ---
def get_items_sql(table, column):
    try:
        df = conn.query(f"SELECT {column} FROM {table} ORDER BY {column} ASC;", ttl=0)
        return df[column].dropna().tolist() if not df.empty else []
    except Exception as e:
        st.error(f"DB Error: {e}"); return []

def add_item_sql(table, column, value):
    try:
        with conn.session as s:
            s.execute(text(f"INSERT INTO {table} ({column}) VALUES (:val) ON CONFLICT DO NOTHING;"), {"val": value.strip()})
            s.commit()
    except Exception as e:
        st.error(f"DB Error: {e}")

# --- 3. DIALOGS (CRITICAL: MUST BE DEFINED HERE) ---

@st.dialog("📚 Bulk Add Proposals")
def bulk_add_proposals_dialog():
    st.write("Paste titles separated by **new lines** or **commas**.")
    raw_text = st.text_area("Proposals List", height=200)
    if st.button("Add All", type="primary"):
        items = [i.strip() for i in re.split(r'[\n,]+', raw_text) if i.strip()]
        if items:
            with conn.session as s:
                for title in items:
                    s.execute(text("INSERT INTO proposals (title) VALUES (:v) ON CONFLICT DO NOTHING"), {"v": title})
                s.commit()
            st.success(f"Added {len(items)} proposals!"); time.sleep(1); st.rerun()

@st.dialog("✏️ Edit Proposal")
def edit_proposal_dialog(old_val):
    new_val = st.text_input("New Title", value=old_val)
    if st.button("Update"):
        with conn.session as s:
            s.execute(text("UPDATE proposals SET title = :n WHERE title = :o"), {"n": new_val, "o": old_val})
            s.execute(text("UPDATE scores SET proposal_title = :n WHERE proposal_title = :o"), {"n": new_val, "o": old_val})
            s.commit()
        st.rerun()

@st.dialog("🗑️ Confirm Delete")
def confirm_delete_dialog(table, column, value):
    st.warning(f"Delete '{value}' permanently?")
    if st.button("Confirm Delete", type="primary"):
        with conn.session as s:
            s.execute(text(f"DELETE FROM {table} WHERE {column} = :v"), {"v": value})
            s.commit()
        st.rerun()

# --- 4. AUTHENTICATION ---
def check_password():
    if st.session_state["authenticated"]: return True
    
    saved_user = cookie_manager.get(cookie="asm_admin_user")
    if saved_user:
        user_check = conn.query("SELECT username, role FROM users WHERE username = :u", params={"u": saved_user}, ttl=0)
        if not user_check.empty:
            st.session_state.update({"authenticated": True, "username": user_check.iloc[0]['username'], "user_role": user_check.iloc[0]['role']})
            return True

    st.markdown("<h1 style='text-align: center;'>🛡️ ASM Admin</h1>", unsafe_allow_html=True)
    with st.container(border=True):
        u_input = st.text_input("Username").strip()
        p_input = st.text_input("Password", type="password").strip()
        if st.button("Sign In", use_container_width=True):
            user_data = conn.query("SELECT username, password_hash, role FROM users WHERE LOWER(username) = LOWER(:u)", params={"u": u_input}, ttl=0)
            if not user_data.empty and str(user_data.iloc[0]['password_hash']) == p_input:
                st.session_state.update({"authenticated": True, "username": user_data.iloc[0]['username'], "user_role": user_data.iloc[0]['role']})
                cookie_manager.set("asm_admin_user", user_data.iloc[0]['username'])
                st.rerun()
            else: st.error("❌ Invalid Credentials")
    return False

if not check_password(): st.stop()

# --- 5. SIDEBAR ---
with st.sidebar:
    st.title("🛡️ ASM Admin")
    try:
        st.page_link("admin.py", label="Home Dashboard", icon="🏠")
        st.page_link("pages/Reports.py", label="Detailed Reports", icon="📊")
    except: st.caption("Navigation Ready")

    st.divider()
    menu_options = ["📊 Tracker", "📋 Proposals", "👤 Evaluators & Links", "📜 History"]
    if st.session_state["user_role"] == "SuperAdmin": menu_options.append("🔑 User Management")
    menu_choice = st.radio("Go to Section:", menu_options)
    
    if st.button("🚪 Logout", use_container_width=True):
        cookie_manager.delete("asm_admin_user")
        st.session_state.clear(); st.rerun()

# --- 6. MAIN CONTENT ---
if menu_choice == "📊 Tracker":
    st.header("📊 Live Progress")
    df_scores = conn.query("SELECT * FROM scores;", ttl=0)
    props_all = get_items_sql("proposals", "title")
    evals_df = conn.query("SELECT name, nickname FROM evaluators ORDER BY name ASC;", ttl=0)
    
    # Progress Calculation
    total_props = len(props_all)
    total_req = total_props * len(evals_df)
    current_sub = len(df_scores) if not df_scores.empty else 0

    if total_req > 0:
        st.progress(min(current_sub / total_req, 1.0))
        st.write(f"**Total Progress:** {current_sub} / {total_req}")

    cols = st.columns(4)
    for i, row in evals_df.iterrows():
        name = row['name']
        done = len(df_scores[df_scores['evaluator'] == name]) if not df_scores.empty else 0
        img = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{name.replace(' ', '_')}.png?t={cache_buster}"
        with cols[i % 4]:
            st.markdown(f'<div style="border:1px solid #ddd; padding:10px; border-radius:10px; text-align:center;"><img src="{img}" style="width:50px; border-radius:50%;"><br><b>{name}</b><br>{done}/{total_props}</div>', unsafe_allow_html=True)

elif menu_choice == "📋 Proposals":
    st.header("📋 Proposals")
    if st.session_state["user_role"] != "Viewer":
        if st.button("📚 Bulk Add"): bulk_add_proposals_dialog()
        
        with st.expander("➕ Add Single"):
            with st.form("single_p"):
                p_name = st.text_input("Title")
                if st.form_submit_button("Add"):
                    if p_name.strip(): 
                        add_item_sql("proposals", "title", p_name)
                        st.rerun()
    
    props = get_items_sql("proposals", "title")
    for p in props:
        c1, c2, c3 = st.columns([5, 1, 1])
        c1.write(f"• {p}")
        if st.session_state["user_role"] in ["SuperAdmin", "Editor"]:
            if c2.button("✏️", key=f"ed_{p}"): edit_proposal_dialog(p)
            if c3.button("🗑️", key=f"del_{p}"): confirm_delete_dialog("proposals", "title", p)

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


