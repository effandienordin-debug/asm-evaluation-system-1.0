import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import io
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# --- Page Config ---
st.set_page_config(page_title="ASM Result Dashboard", layout="wide")

# --- CSS STYLES (Same as before) ---
st.markdown("""
    <style>
    .stApp { background-color: #FFFFFF !important; color: #000000 !important; }
    [data-testid="stMetricValue"] { color: #1E3A8A !important; }
    div[data-testid="stExpander"] { background-color: #F8F9FA !important; border: 1px solid #E5E7EB !important; }
    .proposal-header { 
        background-color: #1E3A8A; color: white; padding: 10px; border-radius: 5px; 
        margin-top: 20px; margin-bottom: 10px; font-weight: bold;
    }
    .wrapped-table {
        width: 100%; border-collapse: collapse; font-family: sans-serif; font-size: 13px; table-layout: fixed;
    }
    .wrapped-table th { background-color: #f3f4f6; border: 1px solid #e5e7eb; padding: 8px; text-align: left; }
    .wrapped-table td { border: 1px solid #e5e7eb; padding: 8px; vertical-align: top; word-wrap: break-word; line-height: 1.4; }
    .comment-bubble { background-color: #f0f2f6; border-radius: 10px; padding: 12px; margin: 2px 0; font-size: 13px; }
    </style>
    """, unsafe_allow_html=True)

# --- PDF Generation Logic (Updated for Comments) ---
def generate_pdf(dataframe, criteria_cols):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=landscape(A4),
        rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=50
    )
    elements = []
    styles = getSampleStyleSheet()
    timestamp = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    
    # Custom styles for PDF
    comment_style = styles["BodyText"]
    comment_style.fontSize = 7
    comment_style.leading = 9 # line spacing
    
    title_style = styles["Title"]
    title_style.textColor = colors.HexColor("#1E3A8A")

    elements.append(Paragraph("ASM Evaluation Full Results Report", title_style))
    elements.append(Spacer(1, 12))

    available_width = 781 
    # Header: Proposal, Evaluator, C1, C2, C3, C4, C5, C6, Total, Rec
    headers = ['Proposal', 'Evaluator'] + [c.replace('_', ' ').title().split(' ')[0] for c in criteria_cols] + ['Total', 'Rec']
    
    col_widths = [
        available_width * 0.28, # Proposal
        available_width * 0.12, # Evaluator
        available_width * 0.065, available_width * 0.065, available_width * 0.065, 
        available_width * 0.065, available_width * 0.065, available_width * 0.065,
        available_width * 0.05, # Total
        available_width * 0.09  # Rec
    ]

    data = [headers]

    for _, row in dataframe.iterrows():
        # Row 1: The Scores
        score_row = [
            Paragraph(str(row.get('proposal_title', '-')), comment_style),
            Paragraph(str(row.get('evaluator', '-')), comment_style),
        ]
        for c in criteria_cols:
            score_row.append(str(row.get(c, 0)))
        
        score_row.append(f"{row.get('total', 0):.2f}")
        score_row.append(str(row.get('recommendation', '-')))
        data.append(score_row)

        # Row 2: The Comment (Spanning across the table)
        raw_comm = str(row.get('comments', 'No comments provided.'))
        comment_text = f"<b>Justification:</b> {raw_comm}"
        
        # We create a row where the first cell contains the comment and we will merge it later
        comment_row = [Paragraph(comment_text, comment_style), "", "", "", "", "", "", "", "", ""]
        data.append(comment_row)

    # Build Table
    t = Table(data, colWidths=col_widths, repeatRows=1)
    
    # Styling logic
    table_styles = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]

    # Loop to apply merging and background colors to comment rows
    # Every even row (starting from index 2) is a comment row
    for i in range(1, len(data)):
        if i % 2 == 0:
            # Merge the comment across all columns
            table_styles.append(('SPAN', (0, i), (-1, i)))
            table_styles.append(('ALIGN', (0, i), (-1, i), 'LEFT'))
            table_styles.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor("#F0F2F6")))
        else:
            # Normal score row background
            table_styles.append(('BACKGROUND', (0, i), (-1, i), colors.whitesmoke))

    t.setStyle(TableStyle(table_styles))
    
    elements.append(t)

    def add_footer(canvas, doc):
        canvas.saveState()
        footer_text = f"ASM Evaluation Report | Generated on: {timestamp} | Page {doc.page}"
        canvas.setFont('Helvetica', 8)
        canvas.drawCentredString(landscape(A4)[0]/2, 30, footer_text)
        canvas.restoreState()

    doc.build(elements, onFirstPage=add_footer, onLaterPages=add_footer)
    buffer.seek(0)
    return buffer

# --- Database Connection ---
conn = st.connection("postgresql", type="sql")
CRITERIA_COLS = ['strategic_alignment', 'potential_impact', 'feasibility', 'budget_justification', 'timeline_readiness', 'execution_strategy']

# --- SIDEBAR: ADMIN ACCESS ---
if "admin_authenticated" not in st.session_state:
    st.session_state["admin_authenticated"] = False

with st.sidebar:
    st.title("🔐 Admin Controls")
    
    if not st.session_state["admin_authenticated"]:
        admin_pass_input = st.text_input("Enter Admin Password", type="password")
        if st.button("Login", type="primary", use_container_width=True):
            if admin_pass_input == "asm_admin_pass":
                st.session_state["admin_authenticated"] = True
                st.rerun()
            else:
                st.error("Incorrect Password")
    else:
        st.success("Admin Access Granted")
        if st.button("🔓 Logout Admin", use_container_width=True):
            st.session_state["admin_authenticated"] = False
            st.rerun()
        st.divider()
        
        all_data = conn.query("SELECT * FROM scores ORDER BY proposal_title ASC;", ttl=0)
        if not all_data.empty:
            try:
                pdf_file = generate_pdf(all_data, CRITERIA_COLS)
                st.download_button(
                    label="📥 Download Full PDF (incl. Comments)",
                    data=pdf_file,
                    file_name=f"ASM_Full_Results_{datetime.now().strftime('%Y%m%d')}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"Error: {e}")

# --- DASHBOARD UI (Rest of the code remains the same) ---
col_ref1, col_ref2 = st.columns([6, 1])
with col_ref2:
    auto_refresh = st.toggle("🔄 Auto", value=True)
if auto_refresh:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=10000, key="dashrefresh")

df = conn.query("SELECT * FROM scores;", ttl=0)

if not df.empty:
    st.title("📊 Live Evaluation Dashboard")
    unique_proposals = df['proposal_title'].unique()
    
    for proposal in unique_proposals:
        prop_df = df[df['proposal_title'] == proposal].copy()
        st.markdown(f"<div class='proposal-header'>📂 Proposal: {proposal}</div>", unsafe_allow_html=True)
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Avg Score", f"{prop_df['total'].mean():.2f}")
        m2.metric("Evaluators", len(prop_df))
        m3.metric("Max Score", f"{prop_df['total'].max():.2f}")
        m4.metric("Min Score", f"{prop_df['total'].min():.2f}")

        c1, c2 = st.columns([1, 1])
        with c1:
            fig_bar = px.bar(prop_df, x='evaluator', y='total', range_y=[0,5], title="Scores", color='total', color_continuous_scale='GnBu')
            st.plotly_chart(fig_bar, use_container_width=True)
        with c2:
            avg_crit = prop_df[CRITERIA_COLS].mean()
            fig_radar = go.Figure(data=go.Scatterpolar(r=avg_crit.values, theta=[c.replace('_', ' ').title() for c in CRITERIA_COLS], fill='toself', line_color='#1E3A8A'))
            fig_radar.update_layout(polar=dict(radialaxis=dict(range=[0, 5])))
            st.plotly_chart(fig_radar, use_container_width=True)

        with st.expander(f"View Detailed Reviews for {proposal}", expanded=True):
            header_row = "".join([f"<th class='col-crit'>{c.replace('_', ' ').title()}</th>" for c in CRITERIA_COLS])
            table_html = f"<table class='wrapped-table'><thead><tr><th class='col-eval'>Evaluator</th>{header_row}<th class='col-total'>Total</th><th class='col-rec'>Recommendation</th><th class='col-comm'>Comments</th></tr></thead><tbody>"
            for _, row in prop_df.iterrows():
                crit_data = "".join([f"<td class='col-crit'>{row.get(c, 0)}</td>" for c in CRITERIA_COLS])
                raw_comm = str(row.get('comments', '-'))
                formatted_comment = "".join([f"<p> {line.strip()}</p>" for line in raw_comm.split('\n') if line.strip()])
                table_html += f"<tr><td><b>{row['evaluator']}</b></td>{crit_data}<td>{row['total']:.2f}</td><td>{row.get('recommendation', '-')}</td><td><div class='comment-bubble'>{formatted_comment}</div></td></tr>"
            table_html += "</tbody></table>"
            st.markdown(table_html, unsafe_allow_html=True)
        st.divider()
else:
    st.title("📊 Live Evaluation Dashboard")
    st.info("Awaiting submissions...")
