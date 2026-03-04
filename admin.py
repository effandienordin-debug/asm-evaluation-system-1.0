import streamlit as st
import pandas as pd
import time
import qrcode
from io import BytesIO
from datetime import datetime
from sqlalchemy import text
from supabase import create_client
from streamlit_autorefresh import st_autorefresh

# --- 1. CONFIG & CONNECTIONS ---
st.set_page_config(page_title="ASM Admin Panel", layout="wide")

# Safe Secret Loading to prevent KeyError
def load_secret(key):
    if key in st.secrets:
        return st.secrets[key]
    st.error(f"❌ Missing Secret: **{key}**")
    st.info(f"Go to Settings > Secrets and ensure **{key}** is defined at the TOP of the file.")
    st.stop()

SUPABASE_URL = load_secret("supabase_url")
SUPABASE_KEY = load_secret("supabase_key")
ADMIN_PASSWORD = load_secret("password") # We'll use this in the login logic
BUCKET_NAME = "evaluator-photos"

# --- 2. LOGIN LOGIC ---
def check_password():
    """Returns True if the user had the correct password."""
    def password_entered():
        # Now uses the ADMIN_PASSWORD we safely loaded above
        if st.session_state["password"] == ADMIN_PASSWORD: 
            st.session_state["password_correct"] = True
            del st.session_state["password"] 
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.title("🛡️ ASM Admin Login")
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.title("🛡️ ASM Admin Login")
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        st.error("😕 Password incorrect")
        return False
    else:
        return True

if not check_password():
    st.stop() 

# --- 3. INITIALIZE CLIENTS ---
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error("Supabase Connection Error.")

# Automatically uses [connections.postgresql] from secrets
conn = st.connection("postgresql", type="sql")

# --- 4. FORCED WHITE THEME CSS ---
st.markdown("""
    <style>
    .stApp { background-color: #FFFFFF !important; color: #000000 !important; }
    [data-testid="stMetricValue"] { color: #1E3A8A !important; }
    div[data-testid="stExpander"] { background-color: #F8F9FA !important; border: 1px solid #E5E7EB !important; }
    .eval-card {
        padding:15px; border-radius:10px; border: 1px solid #E2E8F0; 
        text-align:center; margin-bottom:10px; min-height: 120px;
    }
    div[data-testid="stSidebarUserContent"] .stRadio > div {
        gap: 10px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 5. DIALOGS ---
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
def edit_evaluator_dialog(old_name):
    new_name = st.text_input("Edit Evaluator Name", value=old_name)
    new_photo = st.file_uploader("Update Photo (Optional)", type=['png', 'jpg', 'jpeg'])
    if st.button("Save Changes", type="primary"):
        clean_new_name = new_name.strip()
        with conn.session as s:
            s.execute(text("UPDATE evaluators SET name = :new WHERE name = :old"), {"new": clean_new_name, "old": old_name})
            s.execute(text("UPDATE scores SET evaluator = :new WHERE evaluator = :old"), {"new": clean_new_name, "old": old_name})
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

# --- 7. SIDEBAR NAVIGATION & CONTROL ---
cache_buster = int(time.time())

with st.sidebar:
    st.title("🛡️ ASM Admin")
    
    if st.button("🚪 Logout"):
        st.session_state["password_correct"] = False
        st.rerun()
        
    st.divider()
    
    auto_refresh = st.toggle("🔄 Auto Refresh (15s)", value=False)
    if auto_refresh: st_autorefresh(interval=15000, key="admin_refresh")
    
    st.subheader("📁 Menu")
    menu_choice = st.radio(
        "Navigate to:",
        ["📊 Tracker", "📋 Proposals", "👤 Evaluators & Links", "📜 History"],
        label_visibility="collapsed"
    )
    
    st.sidebar.markdown("---")
    st.sidebar.subheader("🚀 Session Control")
    
    try:
        df_current = conn.query("SELECT evaluator FROM scores;", ttl=0)
    except: df_current = pd.DataFrame()
    evals_all = get_items_sql("evaluators", "name")
    unique_submitted = df_current['evaluator'].unique().tolist() if not df_current.empty else []
    
    force_mode = st.toggle("⚠️ Enable Force Archive")
    can_archive = (len(unique_submitted) >= len(evals_all) and len(evals_all) > 0) or force_mode

    if st.button("🆕 Archive & Reset", type="primary", use_container_width=True, disabled=not can_archive):
        with conn.session as s:
            s.execute(text("INSERT INTO scores_history SELECT *, NOW() as archive_timestamp FROM scores;"))
            s.execute(text("TRUNCATE TABLE scores RESTART IDENTITY CASCADE;"))
            s.commit()
        st.balloons()
        time.sleep(1)
        st.rerun()

# --- 8. MAIN CONTENT AREA ---

if menu_choice == "📊 Tracker":
    st.header("📊 Live Performance Metrics")
    try:
        df = conn.query("SELECT * FROM scores;", ttl=0)
    except: df = pd.DataFrame()

    if not df.empty:
        numeric_cols = df.select_dtypes(include=['number']).columns
        st.table(df[numeric_cols].mean().round(2).rename("Global Avg"))
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No scores submitted in the current session.")

    if evals_all:
        st.divider()
        progress = min(len(unique_submitted) / len(evals_all), 1.0)
        st.progress(progress)
        st.write(f"**Participation:** {len(unique_submitted)} / {len(evals_all)} Completed")

        cols = st.columns(4)
        for i, name in enumerate(evals_all):
            is_done = name in unique_submitted
            bg = "#E6FFFA" if is_done else "#F8F9FA"
            img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{name.replace(' ', '_')}.png?t={cache_buster}"
            with cols[i % 4]:
                st.markdown(f"""<div class="eval-card" style="background-color:{bg}; border-top: 5px solid {'#38B2AC' if is_done else '#CBD5E0'};">
                    <img src="{img_url}" style="width:50px; height:50px; border-radius:50%; object-fit:cover;" onerror="this.src='https://ui-avatars.com/api/?name={name}'">
                    <p style="font-weight:bold; margin:0; color:#333;">{name}</p>
                    <p style="font-size:0.8em; color:#666;">{'✅ DONE' if is_done else '⌛ WAITING'}</p>
                </div>""", unsafe_allow_html=True)

elif menu_choice == "📋 Proposals":
    st.header("📋 Manage Proposals")
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
        if c2.button("✏️", key=f"edit_p_{p}"): edit_proposal_dialog(p)
        if c3.button("🗑️", key=f"del_p_{p}"): confirm_delete_dialog("proposals", "title", p)

elif menu_choice == "👤 Evaluators & Links":
    st.header("👤 Evaluators & Access Links")
    col_add, col_links = st.columns([1, 1])
    
    with col_add:
        st.subheader("Add Evaluator")
        with st.form("eval_form", clear_on_submit=True):
            e_name = st.text_input("Name")
            e_file = st.file_uploader("Photo", type=['png', 'jpg'])
            if st.form_submit_button("Create"):
                if e_name:
                    add_item_sql("evaluators", "name", e_name)
                    if e_file:
                        path = f"{e_name.strip().replace(' ', '_')}.png"
                        supabase.storage.from_(BUCKET_NAME).upload(path=path, file=e_file.getvalue(), file_options={"content-type": "image/png", "x-upsert": "true"})
                    st.rerun()

    with col_links:
        st.subheader("Access Links")
        if evals_all:
            target_url = "https://asm-evaluation-system-10-evaluation-form.streamlit.app"
            link_data = [{"Name": n, "Link": f"{target_url}/?user={n.replace(' ', '%20')}"} for n in evals_all]
            
            st.table(pd.DataFrame(link_data))
            
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
                        st.image(buf.getvalue(), caption=d['Name'], use_container_width=True)

            if st.button("📋 Show Links for Copying"):
                st.info("Columns are separated. Copy the column you need.")
                c_n, c_l = st.columns(2)
                with c_n:
                    st.caption("Names")
                    st.code("\n".join([d['Name'] for d in link_data]))
                with c_l:
                    st.caption("Clean Links (Copy these)")
                    st.code("\n".join([d['Link'] for d in link_data]))
        else:
            st.info("Add evaluators to generate links.")

    st.divider()
    st.subheader("Manage Existing Evaluators")
    for e in evals_all:
        c1, c2, c3, c4 = st.columns([1, 4, 1, 1])
        img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{e.replace(' ', '_')}.png?t={cache_buster}"
        c1.image(img_url, width=40)
        c2.write(e)
        if c3.button("✏️", key=f"edit_e_{e}"): edit_evaluator_dialog(e)
        if c4.button("🗑️", key=f"del_e_{e}"): confirm_delete_dialog("evaluators", "name", e)

elif menu_choice == "📜 History":
    st.header("📜 Historical Sessions")
    try:
        df_history = conn.query("SELECT * FROM scores_history ORDER BY archive_timestamp DESC;", ttl=0)
    except:
        with conn.session as s:
            s.execute(text("CREATE TABLE IF NOT EXISTS scores_history AS SELECT *, NOW() as archive_timestamp FROM scores WHERE 1=0;"))
            s.commit()
        df_history = pd.DataFrame()

    if not df_history.empty:
        csv = df_history.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download All History (CSV)", data=csv, file_name="asm_history.csv", mime="text/csv")
        st.dataframe(df_history, use_container_width=True)
        if st.toggle("Show Wipe Button"):
            if st.button("🔥 Delete All History"):
                with conn.session as s:
                    s.execute(text("TRUNCATE TABLE scores_history;"))
                    s.commit()
                st.rerun()
    else:
        st.info("No data in archive.")

