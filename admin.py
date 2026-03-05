import streamlit as st
import pandas as pd
import time
import qrcode
import re
from io import BytesIO
from datetime import datetime
from sqlalchemy import text
from supabase import create_client
from streamlit_autorefresh import st_autorefresh

# --- 1. CONFIG & CONNECTIONS ---
st.set_page_config(page_title="ASM Admin Panel", layout="wide")

# Initialize Session State immediately to prevent KeyErrors
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

SUPABASE_URL = load_secret("supabase_url")
SUPABASE_KEY = load_secret("supabase_key")
BUCKET_NAME = "evaluator-photos"

# --- 2. LOGIN LOGIC (Database Driven) ---
def check_password():
    if st.session_state["authenticated"]:
        return True

    st.markdown("<h1 style='text-align: center;'>🛡️ ASM Admin Access</h1>", unsafe_allow_html=True)
    _, center, _ = st.columns([1, 1.5, 1])
    
    with center:
        with st.form("login_form"):
            u_input = st.text_input("Username")
            p_input = st.text_input("Password", type="password")
            submit = st.form_submit_button("Sign In", use_container_width=True)
            
            if submit:
                # Query plain string to avoid UnhashableParamError
                query = "SELECT username, password_hash, role FROM users WHERE username = :u"
                user_data = conn.query(query, params={"u": u_input}, ttl=0)
                
                if not user_data.empty and user_data.iloc[0]['password_hash'] == p_input:
                    st.session_state["authenticated"] = True
                    st.session_state["username"] = user_data.iloc[0]['username']
                    st.session_state["user_role"] = user_data.iloc[0]['role']
                    st.rerun()
                else:
                    st.error("❌ Invalid username or password")
    return False

# --- 3. INITIALIZE CLIENTS ---
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error("Supabase Connection Error.")

conn = st.connection("postgresql", type="sql")

if not check_password():
    st.stop() 

# --- 4. THEME & CSS ---
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

# --- 5. DIALOGS ---

@st.dialog("🔑 Add System User")
def add_user_dialog():
    new_un = st.text_input("New Username")
    new_pw = st.text_input("New Password", type="password")
    new_role = st.selectbox("Role", ["SuperAdmin", "Editor", "Viewer"])
    if st.button("Create User", type="primary"):
        with conn.session as s:
            s.execute(text("INSERT INTO users (username, password_hash, role) VALUES (:u, :p, :r)"),
                      {"u": new_un.strip(), "p": new_pw.strip(), "r": new_role})
            s.commit()
        st.success("User added!")
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

@st.dialog("✏️ Edit Evaluator")
def edit_evaluator_dialog(old_name, old_nick):
    new_name = st.text_input("Full Name", value=old_name)
    new_nick = st.text_input("Nickname", value=old_nick)
    new_photo = st.file_uploader("Update Photo (Optional)", type=['png', 'jpg', 'jpeg'])
    if st.button("Save Changes", type="primary"):
        clean_new_name = new_name.strip()
        with conn.session as s:
            s.execute(text("UPDATE evaluators SET name = :new, nickname = :nick WHERE name = :old"), 
                      {"new": clean_new_name, "nick": new_nick.strip(), "old": old_name})
            s.execute(text("UPDATE scores SET evaluator = :new WHERE evaluator = :old"), 
                      {"new": clean_new_name, "old": old_name})
            s.commit()
        if new_photo:
            file_path = f"{clean_new_name.replace(' ', '_')}.png"
            supabase.storage.from_(BUCKET_NAME).upload(path=file_path, file=new_photo.getvalue(), file_options={"content-type": "image/png", "x-upsert": "true"})
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

@st.dialog("🗑️ Delete Archive Record")
def delete_archive_dialog(ts):
    st.warning(f"Are you sure you want to permanently delete archive record from: {ts}?")
    if st.button("Yes, Delete Permanently", type="primary"):
        with conn.session as s:
            s.execute(text("DELETE FROM scores_history WHERE archive_timestamp = :ts"), {"ts": ts})
            s.commit()
        st.success("Record deleted.")
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
    st.write(f"User: **{st.session_state['username']}**")
    st.caption(f"Role: {st.session_state['user_role']}")
    
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()
    
    st.divider()
    auto_refresh = st.toggle("🔄 Auto Refresh (15s)", value=False)
    if auto_refresh: st_autorefresh(interval=15000, key="admin_refresh")
    
    # RBAC: Only SuperAdmin sees User Management
    menu_options = ["📊 Tracker", "📋 Proposals", "👤 Evaluators & Links", "📜 History"]
    if st.session_state["user_role"] == "SuperAdmin":
        menu_options.append("🔑 User Management")
        
    menu_choice = st.radio("Navigate to:", menu_options)
    
    # RBAC: Editor and SuperAdmin can archive
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
    # Tracker logic (same as original)
    try:
        df_scores = conn.query("SELECT * FROM scores;", ttl=0)
    except: df_scores = pd.DataFrame()

    props_all = get_items_sql("proposals", "title")
    try:
        evals_df = conn.query("SELECT name, nickname FROM evaluators ORDER BY name ASC;", ttl=0)
    except: evals_df = pd.DataFrame()
    
    total_props_count = len(props_all)
    total_evals_count = len(evals_df)
    total_required = total_props_count * total_evals_count
    current_total_submissions = len(df_scores) if not df_scores.empty else 0

    if not df_scores.empty:
        numeric_cols = df_scores.select_dtypes(include=['number']).columns
        st.subheader("Current Session Averages")
        st.table(df_scores[numeric_cols].mean().round(2).rename("Global Avg"))
    
    if total_required > 0:
        st.divider()
        progress_val = min(current_total_submissions / total_required, 1.0)
        st.progress(progress_val)
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
                        <p style="font-size:0.7em; color:#666; letter-spacing:1px;">{'FINISHED' if is_done else 'IN PROGRESS'}</p>
                    </div>
                """, unsafe_allow_html=True)

elif menu_choice == "📋 Proposals":
    st.header("📋 Manage Proposals")
    # RBAC: Viewer cannot add
    if st.session_state["user_role"] != "Viewer":
        p_name = st.text_input("Add Proposal Title")
        if st.button("Add Single"):
            if p_name: add_item_sql("proposals", "title", p_name); st.rerun()
        
        with st.expander("Bulk Add Proposals"):
            bulk_p = st.text_area("Paste list (one per line)")
            if st.button("Save Bulk"):
                for item in bulk_p.split('\n'):
                    if item.strip(): add_item_sql("proposals", "title", item)
                st.rerun()

    props = get_items_sql("proposals", "title")
    st.subheader(f"Existing Proposals ({len(props)})")
    for p in props:
        c1, c2, c3 = st.columns([5, 1, 1])
        c1.write(f"• {p}")
        # RBAC: Viewer cannot edit/delete
        if st.session_state["user_role"] in ["SuperAdmin", "Editor"]:
            if c2.button("✏️", key=f"edit_p_{p}"): edit_proposal_dialog(p)
            if c3.button("🗑️", key=f"del_p_{p}"): confirm_delete_dialog("proposals", "title", p)

elif menu_choice == "👤 Evaluators & Links":
    st.header("👤 Evaluators & Access Links")
    col_add, col_links = st.columns([1, 1])
    
    with col_add:
        st.subheader("Add Evaluator")
        if st.session_state["user_role"] != "Viewer":
            with st.form("eval_form", clear_on_submit=True):
                e_name = st.text_input("Full Name (Official)")
                e_nick = st.text_input("Nickname (For Login Link)")
                e_file = st.file_uploader("Photo", type=['png', 'jpg'])
                if st.form_submit_button("Create"):
                    if e_name and e_nick:
                        with conn.session as s:
                            s.execute(text("INSERT INTO evaluators (name, nickname, has_submitted) VALUES (:n, :nk, FALSE)"), 
                                      {"n": e_name.strip(), "nk": e_nick.strip()})
                            s.commit()
                        if e_file:
                            path = f"{e_name.strip().replace(' ', '_')}.png"
                            supabase.storage.from_(BUCKET_NAME).upload(path=path, file=e_file.getvalue(), file_options={"content-type": "image/png", "x-upsert": "true"})
                        st.rerun()
        else:
            st.info("View-only mode.")

    with col_links:
        st.subheader("Access Links")
        evals_df = conn.query("SELECT name, nickname FROM evaluators ORDER BY name ASC;", ttl=0)
        if not evals_df.empty:
            target_url = "https://asm-evaluation-system-10-evaluation-form.streamlit.app"
            link_data = []
            for _, row in evals_df.iterrows():
                id_to_use = row['nickname'] if row['nickname'] else row['name']
                link_data.append({
                    "Nickname": row['nickname'],
                    "Full Name": row['name'], 
                    "Link": f"{target_url}/?user={id_to_use.replace(' ', '%20')}"
                })
            st.table(pd.DataFrame(link_data)[["Nickname", "Link"]])
            if st.button("🖼️ Generate QR Codes"):
                qr_cols = st.columns(3)
                for idx, d in enumerate(link_data):
                    qr = qrcode.QRCode(version=1, box_size=10, border=4)
                    qr.add_data(d['Link'])
                    qr.make(fit=True)
                    img = qr.make_image(fill_color="black", back_color="white")
                    buf = BytesIO()
                    img.save(buf, format="PNG")
                    with qr_cols[idx % 3]:
                        st.image(buf.getvalue(), caption=f"Login: {d['Nickname']}", use_container_width=True)

    st.divider()
    st.subheader("⚙️ System Management")
    with conn.session as s:
        s.execute(text("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);"))
        s.execute(text("INSERT INTO settings (key, value) VALUES ('evaluator_password', '1234') ON CONFLICT (key) DO NOTHING;"))
        s.commit()

    pass_df = conn.query("SELECT value FROM settings WHERE key = 'evaluator_password' LIMIT 1", ttl=0)
    current_db_pass = pass_df.iloc[0]['value'] if not pass_df.empty else "1234"

    col_pass1, col_pass2 = st.columns([2, 1])
    new_eval_pass = col_pass1.text_input("Set Global Evaluator Password", value=current_db_pass) 
    
    if st.session_state["user_role"] in ["SuperAdmin", "Editor"]:
        if col_pass2.button("Update Password", use_container_width=True, type="primary"):
            with conn.session as s:
                s.execute(text("UPDATE settings SET value = :v WHERE key = 'evaluator_password'"), {"v": new_eval_pass.strip()})
                s.commit()
            st.success(f"✅ Password updated to: {new_eval_pass}")
            time.sleep(1)
            st.rerun()

    st.write("---")
    st.subheader("🔓 Access Control")
    status_df = conn.query("SELECT name, nickname, has_submitted FROM evaluators ORDER BY name ASC;", ttl=0)

    for _, row in status_df.iterrows():
        e = row['name']
        nick = row['nickname']
        is_locked = bool(row['has_submitted'])
        c1, c2, c3, c4, c5 = st.columns([1, 3, 1, 1, 2])
        img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{e.replace(' ', '_')}.png?t={cache_buster}"
        c1.markdown(f'<img src="{img_url}" style="width:40px; height:40px; border-radius:50%; object-fit:cover;" onerror="this.src=\'https://ui-avatars.com/api/?name={e}\'">', unsafe_allow_html=True)
        c2.write(f"**{nick}** ({e}) \n*Status: {'🔒 LOCKED' if is_locked else '🔓 OPEN'}*")
        
        if st.session_state["user_role"] in ["SuperAdmin", "Editor"]:
            if c3.button("✏️", key=f"ed_{e}"): edit_evaluator_dialog(e, nick)
            if c4.button("🗑️", key=f"dl_{e}"): confirm_delete_dialog("evaluators", "name", e)
            if is_locked:
                if c5.button("Reset Access", key=f"re_{e}", use_container_width=True):
                    with conn.session as s:
                        s.execute(text("UPDATE evaluators SET has_submitted = FALSE WHERE name = :n"), {"n": e})
                        s.commit()
                    st.rerun()
            else:
                c5.button("Session Active", key=f"pr_{e}", disabled=True, use_container_width=True)

elif menu_choice == "🔑 User Management":
    st.header("🔑 System Admin Accounts")
    if st.button("➕ Add New Admin User"):
        add_user_dialog()
    users_df = conn.query("SELECT id, username, role FROM users ORDER BY username ASC;", ttl=0)
    st.table(users_df)

elif menu_choice == "📜 History":
    st.header("📜 Archived Evaluations")
    try:
        df_hist = conn.query("SELECT * FROM scores_history ORDER BY archive_timestamp DESC;", ttl=0)
        if not df_hist.empty:
            h_cols = st.columns([2, 2, 2, 1])
            h_cols[0].write("**Date**")
            h_cols[1].write("**Evaluator**")
            h_cols[2].write("**Proposal**")
            h_cols[3].write("**Action**")
            st.divider()
            for i, row in df_hist.iterrows():
                c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
                ts = row['archive_timestamp']
                date_str = ts.strftime("%Y-%m-%d %H:%M") if hasattr(ts, 'strftime') else str(ts)
                c1.write(date_str)
                c2.write(row['evaluator'])
                c3.write(row['proposal_title'])
                if st.session_state["user_role"] == "SuperAdmin":
                    if c4.button("🗑️", key=f"del_hist_{i}"):
                        delete_archive_dialog(row['archive_timestamp'])
        else:
            st.info("No archived records found.")
    except Exception as e:
        st.error(f"Error loading history: {e}")
