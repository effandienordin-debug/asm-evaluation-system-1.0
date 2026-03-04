import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import os
from datetime import datetime

# --- Page Config ---
st.set_page_config(page_title="ASM Admin Panel", layout="wide")

# --- FORCED WHITE THEME CSS ---
st.markdown("""
    <style>
    .stApp { background-color: #FFFFFF !important; color: #000000 !important; }
    [data-testid="stMetricValue"] { color: #1E3A8A !important; }
    div[data-testid="stExpander"] { background-color: #F8F9FA !important; border: 1px solid #E5E7EB !important; }
    .stTable { color: #000000 !important; }
    </style>
    """, unsafe_allow_html=True)

# --- Connect to Google Sheets ---
conn = st.connection("gsheets", type=GSheetsConnection)

# --- Helper Functions (Now using GSheets) ---
def get_cloud_list(worksheet_name, col_name):
    try:
        df = conn.read(worksheet=worksheet_name, ttl="5s")
        return df[col_name].dropna().tolist()
    except:
        return []

def save_cloud_list(worksheet_name, items, col_name):
    df = pd.DataFrame(items, columns=[col_name])
    conn.update(worksheet=worksheet_name, data=df)

# --- Dialogs ---
@st.dialog("⚠️ Confirm Clear")
def confirm_clear(worksheet_name, label, col_name):
    st.write(f"Are you sure you want to delete **ALL** {label} from the cloud?")
    if st.button(f"Yes, Clear All {label}", type="primary"):
        save_cloud_list(worksheet_name, [], col_name)
        st.rerun()

# --- Shared UI Component ---
def manage_list_ui(label, worksheet_name, col_name, session_key_prefix):
    st.subheader(f"Manage {label}")
    existing = get_cloud_list(worksheet_name, col_name)
    input_key = f"input_{session_key_prefix}"

    def add_item_callback():
        val = st.session_state[input_key].strip()
        if val and val not in existing:
            existing.append(val)
            save_cloud_list(worksheet_name, existing, col_name)
            st.session_state[input_key] = "" 
            st.toast(f"✅ Added {val}")

    mode = st.radio(f"Add Mode ({label})", ["Single", "Bulk"], horizontal=True, key=f"mode_{session_key_prefix}")

    if mode == "Single":
        c1, c2 = st.columns([3, 1])
        c1.text_input(f"Add New {label}", key=input_key)
        c2.markdown("<div style='padding-top: 28px;'></div>", unsafe_allow_html=True)
        c2.button("Add", key=f"btn_s_{session_key_prefix}", on_click=add_item_callback, use_container_width=True)
    else:
        bulk_text = st.text_area(f"Paste {label} (one per line)", key=f"bulk_{session_key_prefix}", height=100)
        if st.button(f"Bulk Add {label}", key=f"btn_b_{session_key_prefix}", type="primary"):
            new_items = [t.strip() for t in bulk_text.split('\n') if t.strip()]
            for ni in new_items:
                if ni not in existing: existing.append(ni)
            save_cloud_list(worksheet_name, existing, col_name)
            st.rerun()

    if existing:
        with st.expander(f"🔍 View / Delete {label} ({len(existing)})"):
            search_query = st.text_input(f"Search {label}...", key=f"search_{session_key_prefix}")
            filtered = [item for item in existing if search_query.lower() in item.lower()]
            for item in filtered:
                col_t, col_d = st.columns([6, 1])
                col_t.write(f"• {item}")
                if col_d.button("🗑️", key=f"del_{session_key_prefix}_{item}"):
                    existing.remove(item)
                    save_cloud_list(worksheet_name, existing, col_name)
                    st.rerun()
        
        if st.button(f"🚨 Clear All {label}", key=f"clr_{session_key_prefix}", use_container_width=True):
            confirm_clear(worksheet_name, label, col_name)

# --- Main Admin UI ---
try:
    st.image("80x68.png", width=100)
except:
    st.info("Akademi Sains Malaysia")

st.title("🛡️ Admin Control Center")

tab1, tab2, tab3 = st.tabs(["📋 Proposals", "👤 Evaluators", "🔗 Links"])

with tab1: manage_list_ui("Proposals", "Proposals", "Title", "prop")
with tab2: manage_list_ui("Evaluators", "Evaluators", "Name", "eval")
with tab3:
    st.subheader("Personalized Access Links")
    EVALUATORS = get_cloud_list("Evaluators", "Name")
    if EVALUATORS:
        base_url = st.text_input("Application Base URL", value="https://your-app.streamlit.app").rstrip('/')
        copy_text = "📋 *ASM EVALUATOR LINKS*\n\n"
        link_data = []
        for i, name in enumerate(EVALUATORS):
            link = f"{base_url}/?user={i}"
            copy_text += f"👤 {name}:\n🔗 {link}\n\n"
            link_data.append({"Evaluator": name, "URL": link})
        st.dataframe(pd.DataFrame(link_data), use_container_width=True, hide_index=True)
        st.text_area("Copy-Paste Block", value=copy_text, height=200)

st.divider()

# --- Tracker & Executive Summary ---
st.header("📊 Executive Summary & Tracker")
EVALS_LIST = get_cloud_list("Evaluators", "Name")

# Load Scores from Sheet1
try:
    df = conn.read(worksheet="Sheet1", ttl="5s")
except:
    df = pd.DataFrame()

if not df.empty:
    if 'Evaluator' not in df.columns:
        df.rename(columns={df.columns[0]: 'Evaluator'}, inplace=True)
        
    with st.expander("👀 View Global Performance Summary", expanded=True):
        col_stats, col_leader = st.columns([2, 1])
        numeric_cols = df.select_dtypes(include=['number']).columns
        grand_means = df[numeric_cols].mean().round(2)
        
        with col_stats:
            st.write("**Average Score per Criteria:**")
            st.table(grand_means.rename("Score / 5.0"))

        with col_leader:
            st.write("**Top Rated Proposal:**")
            if 'Proposal_Title' in df.columns:
                prop_avgs = df.groupby('Proposal_Title')['Total'].mean()
                leader = prop_avgs.idxmax()
                st.success(f"🏆 **{leader}**\n\nAvg Score: {prop_avgs.max():.2f}")

        st.dataframe(df, use_container_width=True, hide_index=True)

# --- Submission Tracker ---
unique_submitted = df['Evaluator'].unique().tolist() if not df.empty else []
count = len(unique_submitted)
total_evals = len(EVALS_LIST)

if total_evals > 0:
    progress_val = min(count / total_evals, 1.0)
    st.progress(progress_val)
    st.write(f"**Participation:** {count} of {total_evals} Evaluators have submitted reviews.")
    
    cols = st.columns(4)
    for i, name in enumerate(EVALS_LIST):
        is_done = name in unique_submitted
        bg_color = "#28a745" if is_done else "#F1F5F9"
        text_color = "white" if is_done else "#475569"
        p_count = len(df[df['Evaluator'] == name]) if is_done else 0
        
        with cols[i % 4]:
            st.markdown(f"""
                <div style="padding:15px; border-radius:10px; background-color:{bg_color}; color:{text_color}; border: 1px solid #E2E8F0; text-align:center; margin-bottom:10px;">
                    <p style="font-size:0.85em; font-weight:bold; margin:0;">{name}</p>
                    <p style="font-size:1em; font-weight:bold; margin-top:5px;">{'✅ ' + str(p_count) + ' Done' if is_done else '⌛ WAITING'}</p>
                </div>
            """, unsafe_allow_html=True)

st.divider()

# --- Session Control (Archive to Google Sheets) ---
st.header("🚀 Session Control")
force_mode = st.toggle("⚠️ Enable Force Archive")
can_archive = (count >= total_evals and total_evals > 0) or force_mode

if st.button("🆕 Archive & Reset Dashboard", type="primary", use_container_width=True, disabled=not can_archive):
    if not df.empty:
        df['Archive_Time'] = datetime.now().strftime("%d-%m-%Y %I:%M %p")
        try:
            hist_df = conn.read(worksheet="History")
            new_hist = pd.concat([hist_df, df], ignore_index=True)
        except:
            new_hist = df
        
        conn.update(worksheet="History", data=new_hist)
        # Clear Sheet1 (Keeping only headers)
        headers_only = pd.DataFrame(columns=df.columns)
        conn.update(worksheet="Sheet1", data=headers_only)
        st.balloons()
        st.rerun()
