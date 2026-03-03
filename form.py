import streamlit as st
import pandas as pd
import os
from datetime import datetime

# --- Configuration ---
DATA_FILE = "asm_scores.csv"
TITLES_FILE = "proposal_titles.txt"
EVALS_FILE = "evaluators_list.txt"
CRITERIA = [
    ('Strategic Alignment', 0.25), ('Potential Impact', 0.20), 
    ('Feasibility', 0.15), ('Budget Justification', 0.15), 
    ('Timeline Readiness', 0.10), ('Execution Strategy', 0.15)
]

st.set_page_config(page_title="ASM Evaluator Entry", layout="centered")

def get_list(f): 
    return [l.strip() for l in open(f, "r").readlines() if l.strip()] if os.path.exists(f) else []

EVALUATORS = get_list(EVALS_FILE)
PROPOSALS = get_list(TITLES_FILE)

# --- User Identification ---
user_id = st.query_params.get("user")
if user_id is None or not EVALUATORS:
    st.warning("⚠️ Access Denied. Please use your personalized link.")
    st.stop()

try:
    current_user = EVALUATORS[int(user_id)]
except:
    st.error("Invalid User ID.")
    st.stop()

st.title(f"👤 {current_user}")

selected_proposal = st.selectbox("Select Proposal Title", ["-- Select --"] + PROPOSALS)

if selected_proposal != "-- Select --":
    # --- LOAD EXISTING DATA ---
    existing_data = None
    if os.path.exists(DATA_FILE):
        try:
            df_load = pd.read_csv(DATA_FILE)
            # Ensure the first column is named 'Evaluator' for matching
            if not df_load.empty and 'Evaluator' not in df_load.columns:
                df_load.rename(columns={df_load.columns[0]: 'Evaluator'}, inplace=True)
            
            # Match by both User and Proposal Title
            match = df_load[(df_load['Evaluator'] == current_user) & (df_load['Proposal_Title'] == selected_proposal)]
            if not match.empty:
                existing_data = match.iloc[0]
        except Exception as e:
            st.error(f"Error reading data: {e}")

    if "is_editing" not in st.session_state:
        st.session_state.is_editing = False

    # --- VIEW MODE ---
    if existing_data is not None and not st.session_state.is_editing:
        st.success(f"✅ Record found for: {selected_proposal}")
        st.metric("Your Total Score", f"{existing_data['Total']} / 5.0")
        if st.button("✏️ Edit Scores", use_container_width=True):
            st.session_state.is_editing = True
            st.rerun()
            
    # --- FORM / EDIT MODE ---
    else:
        with st.form("evaluation_form", clear_on_submit=True):
            st.info("ℹ️ **Flexible Scoring**: If a criterion is not applicable, you may leave it at 0.0.")
            new_scores = []
            for name, weight in CRITERIA:
                d_val = float(existing_data[name]) if (existing_data is not None) else 0.0
                val = st.number_input(f"{name} ({int(weight*100)}%)", 0.0, 5.0, d_val, 0.1)
                new_scores.append(val)
            
            d_comm = str(existing_data['Comments']) if (existing_data is not None) else ""
            user_comments = st.text_area("Comments / Remarks", value=d_comm, placeholder="Enter any notes here...")
            
            d_recom = existing_data['Recommendation'] if (existing_data is not None) else "Approve"
            recom = st.radio("Recommendation", ["Approve", "Revise", "Reject"], 
                             index=["Approve", "Revise", "Reject"].index(d_recom), horizontal=True)
            
            if st.form_submit_button("📤 Submit Evaluation", use_container_width=True):
                # --- CALCULATION LOGIC (Proportional Weighting) ---
                weighted_sum = 0
                total_weight_used = 0
                
                for score, (name, weight) in zip(new_scores, CRITERIA):
                    if score > 0: 
                        weighted_sum += (score * weight)
                        total_weight_used += weight
                
                # If everything is 0, total is 0. Otherwise, normalize based on used weights.
                final_total = round(weighted_sum / total_weight_used, 2) if total_weight_used > 0 else 0.0

                ts = datetime.now().strftime("%d-%m-%Y %I:%M %p")
                final_row = [current_user, selected_proposal] + new_scores + [final_total, recom, user_comments, ts]
                cols = ['Evaluator', 'Proposal_Title'] + [c[0] for c in CRITERIA] + ['Total', 'Recommendation', 'Comments', 'Last_Updated']
                
                # --- ROBUST SAVE LOGIC ---
                if os.path.exists(DATA_FILE):
                    df_save = pd.read_csv(DATA_FILE)
                    
                    # Fix missing 'Evaluator' header if necessary
                    if 'Evaluator' not in df_save.columns:
                        df_save.rename(columns={df_save.columns[0]: 'Evaluator'}, inplace=True)
                    
                    # Remove old entry to prevent duplicates
                    mask = ~((df_save['Evaluator'] == current_user) & (df_save['Proposal_Title'] == selected_proposal))
                    df_save = df_save[mask]
                    
                    new_df = pd.concat([df_save, pd.DataFrame([final_row], columns=cols)], ignore_index=True)
                else:
                    new_df = pd.DataFrame([final_row], columns=cols)
                
                new_df.to_csv(DATA_FILE, index=False)
                st.session_state.is_editing = False
                st.success("🎉 Submission Successful!")
                st.rerun()

else:
    st.info("Please select a proposal title to begin.")