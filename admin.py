import streamlit as st
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
    /* Table text color fix */
    .stTable { color: #000000 !important; }
    </style>
    """, unsafe_allow_html=True)

# --- File Paths ---
DATA_FILE = "asm_scores.csv"
HISTORY_FILE = "asm_history.csv"
TITLES_FILE = "proposal_titles.txt"
EVALS_FILE = "evaluators_list.txt"

# --- Helper Functions ---
def get_list_from_file(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            return [line.strip() for line in f.readlines() if line.strip()]
    return []

def save_list_to_file(file_path, items):
    with open(file_path, "w") as f:
        for item in items:
            f.write(item + "\n")

# --- Dialogs ---
@st.dialog("⚠️ Confirm Clear")
def confirm_clear(file_path, label):
    st.write(f"Are you sure you want to delete **ALL** {label}?")
    if st.button(f"Yes, Clear All {label}", type="primary"):
        if os.path.exists(file_path):
            os.remove(file_path)
            with open(file_path, 'w') as f: pass 
        st.rerun()

# --- Shared UI Component ---
def manage_list_ui(label, file_path, session_key_prefix):
    st.subheader(f"Manage {label}")
    existing = get_list_from_file(file_path)
    input_key = f"input_{session_key_prefix}"

    def add_item_callback():
        val = st.session_state[input_key].strip()
        if val and val not in existing:
            existing.append(val)
            save_list_to_file(file_path, existing)
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
            save_list_to_file(file_path, existing)
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
                    save_list_to_file(file_path, existing)
                    st.rerun()
        
        if st.button(f"🚨 Clear All {label}", key=f"clr_{session_key_prefix}", use_container_width=True):
            confirm_clear(file_path, label)

# --- Main Admin UI ---
try:
    st.image("80x68.png", width=100)
except:
    st.info("Akademi Sains Malaysia")

st.title("🛡️ Admin Control Center")

tab1, tab2, tab3 = st.tabs(["📋 Proposals", "👤 Evaluators", "🔗 Links"])

with tab1: manage_list_ui("Proposals", TITLES_FILE, "prop")
with tab2: manage_list_ui("Evaluators", EVALS_FILE, "eval")
with tab3:
    st.subheader("Personalized Access Links")
    EVALUATORS = get_list_from_file(EVALS_FILE)
    if EVALUATORS:
        base_url = st.text_input("Application Base URL", value="http://localhost:8501").rstrip('/')
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
EVALS_LIST = get_list_from_file(EVALS_FILE)

if os.path.exists(DATA_FILE):
    df = pd.read_csv(DATA_FILE)
    if not df.empty:
        # Self-healing column check
        if 'Evaluator' not in df.columns:
            df.rename(columns={df.columns[0]: 'Evaluator'}, inplace=True)
            
        with st.expander("👀 View Global Performance Summary", expanded=True):
            col_stats, col_leader = st.columns([2, 1])
            
            # Numeric columns only
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
                    leader_score = prop_avgs.max()
                    st.success(f"🏆 **{leader}**\n\nAvg Score: {leader_score:.2f}")

            st.write("**Detailed Raw Data:**")
            st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        df = pd.DataFrame()
else:
    df = pd.DataFrame()

# --- Submission Tracker Logic (Crash Proof) ---
unique_submitted = df['Evaluator'].unique().tolist() if not df.empty else []
count = len(unique_submitted)
total_evals = len(EVALS_LIST)

if total_evals > 0:
    # Fix for Progress Value invalid value [0.0, 1.0]: 1.2
    progress_val = min(count / total_evals, 1.0)
    st.progress(progress_val)
    st.write(f"**Participation:** {count} of {total_evals} Evaluators have submitted reviews.")
    
    cols = st.columns(4)
    for i, name in enumerate(EVALS_LIST):
        is_done = name in unique_submitted
        bg_color = "#28a745" if is_done else "#F1F5F9"
        text_color = "white" if is_done else "#475569"
        
        # Check how many proposals this person reviewed
        p_count = len(df[df['Evaluator'] == name]) if is_done else 0
        status_text = f"✅ {p_count} Done" if is_done else "⌛ WAITING"
        
        with cols[i % 4]:
            st.markdown(f"""
                <div style="padding:15px; border-radius:10px; background-color:{bg_color}; color:{text_color}; border: 1px solid #E2E8F0; text-align:center; margin-bottom:10px;">
                    <p style="font-size:0.85em; font-weight:bold; margin:0;">{name}</p>
                    <p style="font-size:1em; font-weight:bold; margin-top:5px;">{status_text}</p>
                </div>
            """, unsafe_allow_html=True)

st.divider()

# --- Session Control ---
st.header("🚀 Session Control")
force_mode = st.toggle("⚠️ Enable Force Archive")
# Archive allowed if everyone is done OR force mode is on
can_archive = (count >= total_evals and total_evals > 0) or force_mode

if st.button("🆕 Archive & Reset Dashboard", type="primary", use_container_width=True, disabled=not can_archive):
    if not df.empty:
        df['Archive_Time'] = datetime.now().strftime("%d-%m-%Y %I:%M %p")
        if os.path.exists(HISTORY_FILE):
            pd.concat([pd.read_csv(HISTORY_FILE), df], ignore_index=True).to_csv(HISTORY_FILE, index=False)
        else:
            df.to_csv(HISTORY_FILE, index=False)
        os.remove(DATA_FILE)
        st.balloons()
        st.rerun()