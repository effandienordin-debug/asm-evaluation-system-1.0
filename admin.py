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

# --- 2. HELPER FUNCTIONS ---
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

# --- 2.5 DIALOGS ---
@st.dialog("📚 Bulk Add Evaluators")
def bulk_add_evaluators_dialog():
    st.markdown("""
    **Format:** `Type, Full Name, Nickname, Email`  
    Use **SSO** for staff or **EXT** for external (manual login).
    """)

    template_csv = "Type,Full Name,Nickname,Email\nSSO,John Doe,John,john@akademisains.gov.my\nEXT,Jane Smith,Jane,jane@gmail.com"
    st.download_button(
        label="📥 Download CSV Template",
        data=template_csv,
        file_name="evaluator_bulk_template.csv",
        mime="text/csv"
    )
    st.divider()
    
    raw_data = st.text_area(
        "List of Evaluators", 
        height=250, 
        placeholder="SSO, John Doe, John, john@akademisains.gov.my\nEXT, Jane Smith, Jane, jane@gmail.com"
    )
    
    if st.button("Import All", type="primary"):
        # --- FIX: CHECK IF TEXT AREA IS BLANK ---
        if not raw_data.strip():
            st.error("🚨 Please paste evaluator data before importing!")
            return

        lines = [line.strip() for line in raw_data.split('\n') if line.strip()]
        count = 0
        error_lines = []
        
        with conn.session as s:
            for line in lines:
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 4:
                    etype, name, nick, email_val = parts[0].upper(), parts[1], parts[2], parts[3]
                    sso_email = email_val if etype == "SSO" else None
                    pers_email = email_val if etype == "EXT" else None
                    pwd = "SSO_USER" if etype == "SSO" else "ASM123!" 

                    try:
                        s.execute(text("""
                            INSERT INTO evaluators (name, nickname, email, sso_email, password, has_submitted) 
                            VALUES (:n, :nk, :em, :sso, :pw, FALSE) 
                            ON CONFLICT (name) DO NOTHING;
                        """), {"n": name, "nk": nick, "em": pers_email, "sso": sso_email, "pw": pwd})
                        count += 1
                    except Exception as e:
                        error_lines.append(f"{name}: {str(e)}")
                else:
                    error_lines.append(f"Invalid format: {line}")
            s.commit()
            
        if error_lines:
            st.warning(f"Imported {count} users, but had {len(error_lines)} issues.")
            with st.expander("View Errors"):
                for err in error_lines: st.write(err)
        else:
            st.success(f"✅ Successfully imported {count} evaluators!")
        
        time.sleep(1.5); st.rerun()

@st.dialog("📚 Bulk Add Proposals")
def bulk_add_proposals_dialog():
    st.write("Paste titles below. Separate by **new lines** or **commas**.")
    raw_text = st.text_area("Proposals List", height=200, placeholder="Proposal A\nProposal B")
    
    if st.button("Add All Proposals", type="primary"):
        # --- FIX: CHECK IF TEXT AREA IS BLANK ---
        if not raw_text.strip():
            st.error("🚨 Proposal list cannot be empty!")
            return

        items = [i.strip() for i in re.split(r'[\n,]+', raw_text) if i.strip()]
        with conn.session as s:
            for title in items:
                s.execute(text("INSERT INTO proposals (title) VALUES (:val) ON CONFLICT DO NOTHING;"), {"val": title})
            s.commit()
        st.success(f"✅ Added {len(items)} proposals!")
        time.sleep(1); st.rerun()

@st.dialog("✏️ Edit Proposal")
def edit_proposal_dialog(old_val):
    new_val = st.text_input("Edit Proposal Title", value=old_val)
    if st.button("Update Title", type="primary"):
        if not new_val.strip():
            st.error("🚨 Title cannot be blank!")
            return
        with conn.session as s:
            s.execute(text("UPDATE proposals SET title = :new WHERE title = :old"), {"new": new_val.strip(), "old": old_val})
            s.execute(text("UPDATE scores SET proposal_title = :new WHERE proposal_title = :old"), {"new": new_val.strip(), "old": old_val})
            s.commit()
        st.rerun()

@st.dialog("🗑️ Confirm Delete")
def confirm_delete_dialog(table, column, value):
    st.warning(f"Delete '{value}' permanently from {table}?")
    if st.button("Yes, Delete", type="primary"):
        with conn.session as s:
            s.execute(text(f"DELETE FROM {table} WHERE {column} = :val"), {"val": value})
            s.commit()
        st.rerun()

@st.dialog("✏️ Edit Evaluator")
def edit_evaluator_dialog(name, nick, email, pwd):
    st.write(f"Editing: **{name}**")
    new_nick = st.text_input("Nickname", value=nick)
    new_email = st.text_input("Email", value=email)
    new_pwd = st.text_input("Password", value=pwd)
    eval_data = conn.query("SELECT sso_email FROM evaluators WHERE name = :n", params={"n": name}, ttl=0)
    current_sso = eval_data.iloc[0]['sso_email'] if not eval_data.empty else ""
    new_sso = st.text_input("Microsoft/SSO Email", value=current_sso if current_sso else "")
    new_file = st.file_uploader("Update Photo (Optional)", type=['png', 'jpg'])
    
    if st.button("Save Changes", type="primary"):
        with conn.session as s:
            s.execute(text("""
                UPDATE evaluators 
                SET nickname = :nk, email = :em, password = :pw, sso_email = :sso
                WHERE name = :n
            """), {"nk": new_nick, "em": new_email, "pw": new_pwd, "sso": new_sso, "n": name})
            s.commit()
        if new_file:
            file_path = f"{name.strip().replace(' ', '_')}.png"
            supabase.storage.from_(BUCKET_NAME).upload(path=file_path, file=new_file.getvalue(), file_options={"x-upsert": "true"})
        st.success("Changes saved!"); time.sleep(1); st.rerun()

@st.dialog("➕ Add Admin User")
def add_user_dialog():
    with st.form("new_user_form"):
        u = st.text_input("Username").strip()
        p = st.text_input("Password", type="password").strip()
        r = st.selectbox("Role", ["Viewer", "Editor", "SuperAdmin"])
        if st.form_submit_button("Create Account"):
            if not u or not p: st.error("🚨 Username/Password required!")
            else:
                try:
                    with conn.session as s:
                        s.execute(text("INSERT INTO users (username, password_hash, role) VALUES (:u, :p, :r)"), {"u": u, "p": p, "r": r})
                        s.commit()
                    st.success(f"✅ User {u} created!"); time.sleep(1); st.rerun()
                except Exception as e: st.error(f"❌ Error: {e}")
                    
@st.dialog("🔑 Edit Admin User")
def edit_user_dialog(user_id, username, role):
    new_role = st.selectbox("Update Role", ["Viewer", "Editor", "SuperAdmin"], index=["Viewer", "Editor", "SuperAdmin"].index(role))
    new_pass = st.text_input("Update Password (leave blank to keep current)", type="password")
    
    if st.button("Save Changes", type="primary"):
        with conn.session as s:
            if new_pass:
                s.execute(text("UPDATE users SET role = :r, password_hash = :p WHERE id = :id"), 
                          {"r": new_role, "p": new_pass, "id": user_id})
            else:
                s.execute(text("UPDATE users SET role = :r WHERE id = :id"), 
                          {"r": new_role, "id": user_id})
            s.commit()
        st.success("User updated!"); time.sleep(1); st.rerun()

# --- 3. LOGIN LOGIC ---
def check_password():
    if st.session_state.get("authenticated"): return True
    saved_user = cookie_manager.get(cookie="asm_admin_user")
    if saved_user:
        user_check = conn.query("SELECT username, role FROM users WHERE username = :u", params={"u": saved_user}, ttl=0)
        if not user_check.empty:
            st.session_state.update({"authenticated": True, "username": user_check.iloc[0]['username'], "user_role": user_check.iloc[0]['role']})
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
                else: st.error("❌ Invalid Credentials")
    return False

if not check_password(): st.stop()

# --- 4. INITIALIZE SUPABASE ---
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error(f"Supabase Error: {e}")

# --- 5. SIDEBAR NAVIGATION ---
with st.sidebar:
    st.title("🛡️ ASM Admin")
    st.subheader("📍 Navigation")
    if st.button("🏠 Home", use_container_width=True): st.switch_page("admin.py")
    st.divider()
    menu_options = ["📊 Tracker", "📋 Proposals", "👤 Evaluators & Links", "📜 History"]
    if st.session_state.get("user_role") == "SuperAdmin": menu_options.append("🔑 User Management")
    menu_choice = st.radio("Go to Section:", menu_options)
    
    st.divider()
    st.subheader("⚙️ Settings")
    auto_refresh = st.toggle("🔄 Auto Refresh (10s)", value=False)
    if auto_refresh:
        st_autorefresh(interval=10000, key="data_refresh")
        st.caption("Live Updates: **ON**")
    
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
   
    if df_scores.empty:
        st.info("ℹ️ **No evaluations have been submitted yet.**")
    else:
        numeric_cols = df_scores.select_dtypes(include=['number']).columns
        st.subheader("Current Session Averages")
        st.table(df_scores[numeric_cols].mean().round(2).rename("Global Avg"))
    
    if not evals_df.empty and len(props_all) > 0:
        total_props_count = len(props_all)
        total_required = total_props_count * len(evals_df)
        current_total_submissions = len(df_scores) if not df_scores.empty else 0
        st.divider()
        st.progress(min(current_total_submissions / total_required, 1.0) if total_required > 0 else 0)
        st.write(f"**Total System Progress:** {current_total_submissions} / {total_required} Evaluations Completed")

        st.subheader("Evaluator Status")
        cols = st.columns(4)
        for i, row in evals_df.iterrows():
            name = row['name']
            nick = row['nickname'] if row['nickname'] else name
            done_count = len(df_scores[df_scores['evaluator'] == name]) if not df_scores.empty else 0
            is_done = (done_count >= total_props_count)
            bg = "#E6FFFA" if is_done else "#FFFBEB"
            border_col = '#38B2AC' if is_done else '#ECC94B'
            img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{name.replace(' ', '_')}.png?t={cache_buster}"
            with cols[i % 4]:
                st.markdown(f"""
                    <div style="background-color:{bg}; border-top: 5px solid {border_col}; padding:15px; border-radius:8px; text-align:center; margin-bottom:10px;">
                        <img src="{img_url}" style="width:60px; height:60px; border-radius:50%; object-fit:cover;" onerror="this.src='https://ui-avatars.com/api/?name={name}'">
                        <p style="font-weight:bold; margin:5px 0 0 0; color:#333;">{nick}</p>
                        <p style="font-size:1.1em; font-weight:bold; color:#1E3A8A;">{done_count} / {total_props_count}</p>
                    </div>
                """, unsafe_allow_html=True)

    if st.session_state["user_role"] == "SuperAdmin":
        st.divider()
        with st.expander("⚠️ Danger Zone"):
            st.warning("Archiving will move all current scores to history and reset the tracker.")
            if st.button("🗄️ Force Archive & Reset Session", type="primary"):
                try:
                    with conn.session as s:
                        s.execute(text("""
                            INSERT INTO scores_history (evaluator, proposal_title, total_score, archive_timestamp)
                            SELECT evaluator, proposal_title, total_score, CURRENT_TIMESTAMP 
                            FROM scores;
                        """))
                        s.execute(text("TRUNCATE TABLE scores;"))
                        s.execute(text("UPDATE evaluators SET has_submitted = FALSE;"))
                        s.commit()
                    st.success("✅ Session archived and reset!")
                    time.sleep(1.5); st.rerun()
                except Exception as e:
                    st.error(f"Archive failed: {e}")

elif menu_choice == "📋 Proposals":
    st.header("📋 Manage Proposals")
    if st.session_state["user_role"] != "Viewer":
        col_a, _ = st.columns([1, 4])
        with col_a:
            if st.button("📚 Bulk Add"): bulk_add_proposals_dialog()
        with st.expander("➕ Add Single Proposal"):
            with st.form("add_p", clear_on_submit=True):
                p_name = st.text_input("Proposal Title*")
                if st.form_submit_button("Add"):
                    # --- FIX: SINGLE PROPOSAL BLANK CHECK ---
                    if p_name.strip():
                        add_item_sql("proposals", "title", p_name.strip())
                        st.success("✅ Added!"); time.sleep(1); st.rerun()
                    else:
                        st.error("🚨 Proposal title cannot be blank!")

    st.divider()
    props = get_items_sql("proposals", "title")
    for idx, p in enumerate(props):
        c1, c2, c3 = st.columns([5, 1, 1])
        c1.write(f"• {p}")
        if st.session_state["user_role"] in ["SuperAdmin", "Editor"]:
            if c2.button("✏️", key=f"edit_p_{idx}_{p}"): edit_proposal_dialog(p)
            if c3.button("🗑️", key=f"del_p_{idx}_{p}"): confirm_delete_dialog("proposals", "title", p)

elif menu_choice == "👤 Evaluators & Links":
    st.header("👤 Evaluators & Access Links")
    if st.session_state["user_role"] != "Viewer":
        col_bulk, _ = st.columns([1, 4])
        with col_bulk:
            if st.button("📚 Bulk Add Evaluators"): 
                bulk_add_evaluators_dialog()
        
        with st.expander("➕ Add Single Evaluator"):
            etype = st.radio("Type", ["ASM Staff (SSO)", "External (Manual)"], horizontal=True)
            with st.form("eval_form", clear_on_submit=True):
                col1, col2 = st.columns(2)
                e_name = col1.text_input("Full Name*").strip()
                e_nick = col1.text_input("Nickname*").strip()
                
                if etype == "ASM Staff (SSO)":
                    e_sso = col2.text_input("Microsoft Email*", placeholder="user@akademisains.gov.my")
                    e_mail = col2.text_input("Alt Email")
                    e_pass = "SSO_USER"
                else:
                    e_sso = None
                    e_mail = col2.text_input("Email*")
                    e_pass = col2.text_input("Password*")
                
                e_file = st.file_uploader("Photo", type=['png', 'jpg'])
                
                if st.form_submit_button("Save"):
                    if not e_name:
                        st.error("🚨 Name is required!")
                    else:
                        try:
                            with conn.session as s:
                                s.execute(text("""
                                    INSERT INTO evaluators (name, nickname, email, sso_email, password, has_submitted) 
                                    VALUES (:n, :nk, :em, :sso, :pw, FALSE)
                                    ON CONFLICT (name) DO NOTHING;
                                """), {"n": e_name, "nk": e_nick, "em": e_mail, "sso": e_sso, "pw": e_pass})
                                s.commit()
                            
                            if e_file:
                                file_path = f"{e_name.replace(' ', '_')}.png"
                                supabase.storage.from_(BUCKET_NAME).upload(
                                    path=file_path, file=e_file.getvalue(), file_options={"x-upsert": "true"}
                                )
                            
                            st.success(f"✅ {e_name} Added!")
                            time.sleep(1); st.rerun()
                        except Exception as e:
                            st.error(f"❌ Database Error: {e}")

    st.divider()
    status_df = conn.query("SELECT * FROM evaluators ORDER BY name ASC;", ttl=0)
    for idx, row in status_df.iterrows():
        e = row['name']
        nick = row['nickname']
        pers_email = row.get('email', '')
        sso_val = row.get('sso_email')
        
        c1, c2, c3, c4, c5, c6, c7 = st.columns([0.5, 2.5, 1.5, 0.6, 0.6, 0.6, 0.6])
        img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{e.replace(' ', '_')}.png?t={cache_buster}"
        c1.markdown(f'<img src="{img_url}" style="width:40px; height:40px; border-radius:50%;" onerror="this.src=\'https://ui-avatars.com/api/?name={e}\'">', unsafe_allow_html=True)
        with c2:
            st.write(f"**{nick}**")
            st.caption(f"📧 {pers_email} | SSO: {sso_val if sso_val else 'None'}")
        c3.write(f"`{row.get('password')}`")
        if st.session_state["user_role"] in ["SuperAdmin", "Editor"]:
            if c4.button("✏️", key=f"eval_edit_{idx}_{e}"): edit_evaluator_dialog(e, nick, pers_email, row.get('password'))
            if c6.button("🔄", key=f"eval_reset_{idx}_{e}"):
                with conn.session as s:
                    s.execute(text("UPDATE evaluators SET has_submitted = FALSE WHERE name = :n"), {"n": e})
                    s.commit()
                st.rerun()
            if c7.button("🗑️", key=f"eval_del_{idx}_{e}"): confirm_delete_dialog("evaluators", "name", e)

elif menu_choice == "🔑 User Management":
    st.header("🔑 System Admin Accounts")
    if st.button("➕ Add New Admin"): add_user_dialog()
    st.divider()
    users_df = conn.query("SELECT id, username, role FROM users ORDER BY id ASC;", ttl=0)
    for idx, row in users_df.iterrows():
        c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
        c1.write(f"👤 **{row['username']}**")
        c2.write(f"Role: `{row['role']}`")
        if c3.button("✏️", key=f"admin_edit_{row['id']}"): edit_user_dialog(row['id'], row['username'], row['role'])
        if row['username'] != st.session_state["username"]:
            if c4.button("🗑️", key=f"admin_del_{row['id']}"): confirm_delete_dialog("users", "id", row['id'])

elif menu_choice == "📜 History":
    st.header("📜 Archived Evaluations")
    df_hist = conn.query("SELECT * FROM scores_history ORDER BY archive_timestamp DESC;", ttl=0)
    if not df_hist.empty:
        csv_history = df_hist.to_csv(index=False).encode('utf-8')
        col_dl, _ = st.columns([1, 3])
        with col_dl:
            st.download_button(label="📥 Download History (CSV)", data=csv_history, file_name=f"asm_history_{cache_buster}.csv", mime="text/csv", use_container_width=True)
        st.dataframe(df_hist, use_container_width=True)
    else:
        st.info("ℹ️ No archived data found.")
