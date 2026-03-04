import streamlit as st
import pandas as pd
import os
from datetime import datetime
from sqlalchemy import text
from supabase import create_client

# --- 1. CONFIG & CONNECTIONS ---
st.set_page_config(page_title="ASM Admin Panel", layout="wide")

# Replace with your actual Supabase Credentials
SUPABASE_URL = "https://your-project-id.supabase.co"
SUPABASE_KEY = "your-anon-key"
BUCKET_NAME = "evaluator-photos"

# Initialize Clients
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
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

# --- 3. HELPER FUNCTIONS (SQL BASED) ---
def get_items_sql(table, column):
    query = f"SELECT {column} FROM {table} ORDER BY {column} ASC;"
    df = conn.query(query, ttl=0) 
    return df[column].dropna().tolist() if not df.empty else []

def add_item_sql(table, column, value):
    with conn.session as s:
        query = text(f"INSERT INTO {table} ({column}) VALUES (:val) ON CONFLICT DO NOTHING;")
        s.execute(query, {"val": value})
        s.commit()

# --- 4. DIALOGS ---
@st.dialog("⚠️ Confirm Clear")
def confirm_clear(table, label):
    st.write(f"Are you sure you want to delete **ALL** {label} in the database?")
    if st.button(f"Yes, Clear All {label}", type="primary"):
        with conn.session as s:
            s.execute(text(f"DELETE FROM {table};"))
            s.commit()
        st.rerun()

# --- 5. MAIN UI ---
st.title("🛡️ ASM Admin Control Center")

# --- AUTO-REFRESH TOGGLE ---
col_ref1, col_ref2 = st.columns([6, 1])
with col_ref2:
    auto_refresh = st.toggle("🔄 Auto", value=False, help="Refresh summary every 10s")
if auto_refresh:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=10000, key="adminrefresh")

tab1, tab2, tab3 = st.tabs(["📋 Proposals", "👤 Evaluators", "🔗 Links"])

# --- TAB 1: PROPOSALS ---
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
        if st.button("🚨 Clear All Proposals", type="secondary"): confirm_clear("proposals", "Proposals")

# --- TAB 2: EVALUATORS (With Supabase Image Upload) ---
with tab2:
    st.subheader("Manage Evaluators")
    e_name = st.text_input("Evaluator Full Name")
    e_photo = st.file_uploader("Upload Profile Photo", type=['png', 'jpg', 'jpeg'])
    
    if st.button("Add Evaluator", type="primary"):
        if e_name:
            add_item_sql("evaluators", "name", e_name.strip())
            if e_photo:
                file_path = f"{e_name.strip().replace(' ', '_')}.png"
                supabase.storage.from_(BUCKET_NAME).upload(
                    path=file_path, file=e_photo.getvalue(),
                    file_options={"content-type": e_photo.type, "x-upsert": "true"}
                )
            st.success(f"✅ {e_name} added.")
            st.rerun()

    evals = get_items_sql("evaluators", "name")
    with st.expander(f"🔍 View Evaluators ({len(evals)})"):
        for e in evals:
            c1, c2, c3 = st.columns([1, 5, 1])
            img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{e.replace(' ', '_')}.png"
            c1.image(img_url, width=40) # Supabase URL
            c2.write(e)
            if c3.button("🗑️", key=f"del_e_{e}"):
                with conn.session as s:
                    s.execute(text("DELETE FROM evaluators WHERE name = :v"), {"v": e})
                    s.commit()
                st.rerun()
        if st.button("🚨 Clear All Evaluators"): confirm_clear("evaluators", "Evaluators")

# --- TAB 3: LINKS ---
with tab3:
    st.subheader("Access Links")
    eval_list = get_items_sql("evaluators", "name")
    if eval_list:
        base_url = st.text_input("App URL", value="http://localhost:8501").rstrip('/')
        link_data = []
        copy_text = "📋 *ASM EVALUATOR LINKS*\n\n"
        for i, name in enumerate(eval_list):
            url = f"{base_url}/?user={i}"
            link_data.append({"Evaluator": name, "Link": url})
            copy_text += f"👤 {name}: {url}\n"
        st.dataframe(pd.DataFrame(link_data), use_container_width=True, hide_index=True)
        st.text_area("Copy-Paste Block", value=copy_text, height=150)

st.divider()

# --- 6. EXECUTIVE SUMMARY & TRACKER ---
st.header("📊 Executive Summary & Tracker")
df = conn.query("SELECT * FROM scores;", ttl=0)

if not df.empty:
    with st.expander("👀 View Global Performance Summary", expanded=True):
        col_stats, col_leader = st.columns([2, 1])
        
        # Criteria Averages
        CRIT_COLS = ['strategic_alignment', 'potential_impact', 'feasibility', 'budget_justification', 'timeline_readiness', 'execution_strategy']
        grand_means = df[CRIT_COLS].mean().round(2)
        
        with col_stats:
            st.write("**Average Score per Criteria:**")
            st.table(grand_means.rename("Score / 5.0"))

        with col_leader:
            st.write("**Top Rated Proposal:**")
            prop_avgs = df.groupby('proposal_title')['total'].mean()
            leader = prop_avgs.idxmax()
            st.success(f"🏆 **{leader}**\n\nAvg Score: {prop_avgs.max():.2f}")

        st.write("**Detailed Raw Data:**")
        st.dataframe(df, use_container_width=True, hide_index=True)

# --- TRACKER WITH PHOTOS ---
evals_total = get_items_sql("evaluators", "name")
unique_submitted = df['evaluator'].unique().tolist() if not df.empty else []

if evals_total:
    progress = min(len(unique_submitted) / len(evals_total), 1.0)
    st.progress(progress)
    st.write(f"**Participation:** {len(unique_submitted)} of {len(evals_total)} Evaluators active.")
    
    cols = st.columns(4)
    for i, name in enumerate(evals_total):
        is_done = name in unique_submitted
        status = "✅ Active" if is_done else "⌛ Waiting"
        bg = "#E6FFFA" if is_done else "#F8F9FA"
        txt = "#2C7A7B" if is_done else "#718096"
        img_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{name.replace(' ', '_')}.png"
        
        with cols[i % 4]:
            st.markdown(f"""
                <div class="eval-card" style="background-color:{bg}; color:{txt};">
                    <img src="{img_url}" style="width:50px; height:50px; border-radius:50%; object-fit:cover; margin-bottom:5px;" onerror="this.src='https://ui-avatars.com/api/?name={name}'">
                    <p style="font-size:0.9em; font-weight:bold; margin:0;">{name}</p>
                    <p style="font-size:0.8em; margin:0;">{status}</p>
                </div>
            """, unsafe_allow_html=True)

# --- 7. SESSION CONTROL ---
st.divider()
st.header("🚀 Session Control")
if st.button("🆕 Archive & Reset Dashboard", type="primary", use_container_width=True):
    if not df.empty:
        df['archive_time'] = datetime.now().strftime("%Y-%m-%d %H:%M")
        # Copy scores to history table
        with conn.session as s:
            s.execute(text("INSERT INTO history SELECT * FROM scores;"))
            s.execute(text("DELETE FROM scores;"))
            s.commit()
        st.balloons()
        st.rerun()
