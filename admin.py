import streamlit as st
import pandas as pd
from datetime import datetime
from sqlalchemy import text
from supabase import create_client
from streamlit_autorefresh import st_autorefresh

# --- 1. CONFIG & CONNECTIONS ---
st.set_page_config(page_title="ASM Admin Panel", layout="wide")

# Replace with your actual Supabase Credentials
SUPABASE_URL = "https://your-project-id.supabase.co"
SUPABASE_KEY = "your-anon-key"
BUCKET_NAME = "evaluator-photos"

# Initialize Clients with Error Catching
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error("Failed to connect to Supabase. Check your URL/Key.")

conn = st.connection("postgresql", type="sql")

# --- 2. FORCED WHITE THEME CSS ---
st.markdown("""
    <style>
    .stApp { background-color: #FFFFFF !important; color: #000000 !important; }
    [data-testid="stMetricValue"] { color: #1E3A8A !important; }
    div[data-testid="stExpander"] { background-color: #F8F9FA !important; border: 1px solid #E5E7EB !important; }
    .stTable { color: #000000 !important; }
    .eval-card {
        padding:15px; border-radius:10px; border: 1px solid #E2E8F0; 
        text-align:center; margin-bottom:10px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 3. HELPER FUNCTIONS ---
def get_items_sql(table, column):
    try:
        query = f"SELECT {column} FROM {table} ORDER BY {column} ASC;"
        df = conn.query(query, ttl=0) 
        return df[column].dropna().tolist() if not df.empty else []
    except:
        return []

def add_item_sql(table, column, value):
    with conn.session as s:
        query = text(f"INSERT INTO {table} ({column}) VALUES (:val) ON CONFLICT DO NOTHING;")
        s.execute(query, {"val": value})
        s.commit()

# --- 4. AUTO-REFRESH (Safely implemented) ---
# We put this in a toggle so it doesn't interfere while you are adding data
st.title("🛡️ ASM Admin Control Center")

col_ref1, col_ref2 = st.columns([6, 1])
with col_ref2:
    auto_refresh = st.toggle("🔄 Auto-Refresh", value=False)

if auto_refresh:
    # Use a key to prevent it from resetting form inputs unnecessarily
    st_autorefresh(interval=10000, key="admin_refresh_interval")

# --- 5. TABS ---
tab1, tab2, tab3 = st.tabs(["📋 Proposals", "👤 Evaluators", "🔗 Links"])

with tab1:
    st.subheader("Manage Proposals")
    mode_p = st.radio("Add Mode (Proposals)", ["Single", "Bulk"], horizontal=True)
    if mode_p == "Single":
        p_name = st.text_input("Proposal Title", key="psingle")
        if st.button("Add Proposal"):
            if p_name: 
                add_item_sql("proposals", "title", p_name.strip())
                st.rerun()
    else:
        bulk_p = st.text_area("Paste Proposals (one per line)", key="pbulk")
        if st.button("Bulk Add Proposals"):
            for item in bulk_p.split('\n'):
                if item.strip(): add_item_sql("proposals", "title", item.strip())
            st.rerun()

    props = get_items_sql("proposals", "title")
    with st.expander(f"🔍 View Proposals ({len(props)})"):
        for p in props:
            c1, c2 = st.columns([6, 1])
            c1.write(f"• {p}")
            if c2.button("🗑️", key=f"del_p_{p}"):
                with conn.session as s:
                    s.execute(text("DELETE FROM proposals WHERE title = :v"), {"v": p})
                    s.commit()
                st.rerun()

with tab2:
    st.subheader("Manage Evaluators")
    # Use a form to prevent Auto-Refresh from clearing fields mid-type
    with st.form("evaluator_form", clear_on_submit=True):
        e_name = st.text_input("Evaluator Full Name")
        e_photo = st.file_uploader("Upload Profile Photo", type=['png', 'jpg', 'jpeg'])
        submit_eval = st.form_submit_button("Add Evaluator", type="primary")

    if submit_eval:
        if e_name:
            # 1. Database Entry
            add_item_sql("evaluators", "name", e_name.strip())
            
            # 2. Supabase Upload with Error Catching
            if e_photo:
                try:
                    file_path = f"{e_name.strip().replace(' ', '_')}.png"
                    supabase.storage.from_(BUCKET_NAME).upload(
                        path=file_path, 
                        file=e_photo.getvalue(),
                        file_options={"content-type": e_photo.type, "x-upsert": "true"}
                    )
                    st.success(f"✅ {e_name} and Photo Saved!")
                except Exception as e:
                    st.error(f"Storage Error: {e}. Check if bucket '{BUCKET_NAME}' is public.")
            else:
                st.success(f"✅ {e_name} added (No photo).")
            st.rerun()

    evals = get_items_sql("evaluators", "name")
    with st.expander(f"🔍 View Evaluators ({len(evals)})"):
        for e in evals:
            c1, c2, c3 = st.columns([1, 5, 1])
            img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{e.replace(' ', '_')}.png"
            c1.image(img_url, width=40)
            c2.write(e)
            if c3.button("🗑️", key=f"del_e_{e}"):
                with conn.session as s:
                    s.execute(text("DELETE FROM evaluators WHERE name = :v"), {"v": e})
                    s.commit()
                st.rerun()

with tab3:
    # (Link logic remains the same as your previous code)
    st.subheader("Access Links")
    eval_list = get_items_sql("evaluators", "name")
    if eval_list:
        base_url = st.text_input("App URL", value="http://localhost:8501").rstrip('/')
        link_data = []
        for i, name in enumerate(eval_list):
            url = f"{base_url}/?user={i}"
            link_data.append({"Evaluator": name, "Link": url})
        st.dataframe(pd.DataFrame(link_data), use_container_width=True, hide_index=True)

# --- 6. SUMMARY & TRACKER ---
st.divider()
st.header("📊 Executive Summary & Tracker")
try:
    df = conn.query("SELECT * FROM scores;", ttl=0)
except:
    df = pd.DataFrame()

if not df.empty:
    # Summary calculation (logic same as previous)
    pass

# TRACKER (Fixed Image loading)
evals_total = get_items_sql("evaluators", "name")
unique_submitted = df['evaluator'].unique().tolist() if not df.empty else []

if evals_total:
    st.write(f"**Participation:** {len(unique_submitted)} of {len(evals_total)} Evaluators active.")
    cols = st.columns(4)
    for i, name in enumerate(evals_total):
        is_done = name in unique_submitted
        bg = "#E6FFFA" if is_done else "#F8F9FA"
        img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{name.replace(' ', '_')}.png"
        
        with cols[i % 4]:
            st.markdown(f"""
                <div class="eval-card" style="background-color:{bg};">
                    <img src="{img_url}" style="width:50px; height:50px; border-radius:50%; object-fit:cover;" 
                    onerror="this.src='https://ui-avatars.com/api/?name={name}'">
                    <p style="font-size:0.9em; font-weight:bold; margin:0;">{name}</p>
                </div>
            """, unsafe_allow_html=True)
