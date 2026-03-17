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
from streamlit_autorefresh import st_autorefresh # Moved to top

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="ASM Result Dashboard", layout="wide")

# --- 2. UPDATED CSS STYLES (Ensures Header Visibility) ---
st.markdown("""
    <style>
    .stApp { background-color: #FFFFFF !important; color: #000000 !important; }
    
    @media print {
        /* 1. FORCE HEADER VISIBILITY */
        header, [data-testid="stHeader"] {
            display: none !important; /* Hides the Streamlit bar, not your content */
        }
        
        /* Ensure our custom titles and headers are visible */
        h1, h2, h3, .proposal-header {
            visibility: visible !important;
            display: block !important;
            color: #1E3A8A !important;
        }

        /* 2. HIDE SIDEBAR & BUTTONS */
        [data-testid="stSidebar"], .stButton, [data-testid="stToolbar"] {
            display: none !important;
        }

        /* 3. FIX PROPOSAL HEADERS */
        .proposal-header {
            page-break-before: always !important;
            background-color: #1E3A8A !important;
            color: white !important;
            padding: 15px !important;
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
        }

        /* 4. LAYOUT ADJUSTMENTS */
        .main .block-container {
            padding-top: 0 !important;
            margin-top: 0 !important;
        }
    }
    </style>
    """, unsafe_allow_html=True)

# --- 3. PDF GENERATION LOGIC ---
def generate_pdf(dataframe, criteria_cols):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=50)
    elements = []
    styles = getSampleStyleSheet()
    timestamp = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    
    comment_style = styles["BodyText"]
    comment_style.fontSize = 7
    comment_style.leading = 9 
    
    title_style = styles["Title"]
    title_style.textColor = colors.HexColor("#1E3A8A")

    elements.append(Paragraph("ASM Evaluation Full Results Report", title_style))
    elements.append(Spacer(1, 12))

    available_width = 781 
    headers = ['Proposal', 'Evaluator'] + [c.replace('_', ' ').title().split(' ')[0] for c in criteria_cols] + ['Total', 'Rec']
    
    col_widths = [available_width * 0.28, available_width * 0.12] + [available_width * 0.065]*6 + [available_width * 0.05, available_width * 0.09]

    data = [headers]

    for _, row in dataframe.iterrows():
        score_row = [
            Paragraph(str(row.get('proposal_title', '-')), comment_style),
            Paragraph(str(row.get('evaluator', '-')), comment_style),
        ]
        for c in criteria_cols:
            score_row.append(str(row.get(c, 0)))
        
        score_row.append(f"{row.get('total', 0):.2f}")
        score_row.append(str(row.get('recommendation', '-')))
        data.append(score_row)

        raw_comm = str(row.get('comments', 'No comments provided.'))
        comment_text = f"<b>Comments:</b> {raw_comm}"
        comment_row = [Paragraph(comment_text, comment_style)] + [""] * (len(headers) - 1)
        data.append(comment_row)

    t = Table(data, colWidths=col_widths, repeatRows=1)
    table_styles = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]

    for i in range(1, len(data)):
        if i % 2 == 0: # This is the comment row
            table_styles.append(('SPAN', (0, i), (-1, i)))
            table_styles.append(('ALIGN', (0, i), (-1, i), 'LEFT'))
            table_styles.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor("#F0F2F6")))
        else:
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

# --- 4. DATABASE & AUTHENTICATION ---
conn = st.connection("postgresql", type="sql")
CRITERIA_COLS = ['strategic_alignment', 'potential_impact', 'feasibility', 'budget_justification', 'timeline_readiness', 'execution_strategy']

if "admin_authenticated" not in st.session_state:
    st.session_state["admin_authenticated"] = False

if not st.session_state["admin_authenticated"]:
    st.title("🔐 ASM Dashboard Login")
    admin_pass_input = st.text_input("Password", type="password")
    if st.button("Access Dashboard", type="primary"):
        if admin_pass_input == "asm_admin_pass":
            st.session_state["admin_authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect Password")
    st.stop()

# --- 6. AUTHENTICATED SIDEBAR ---
with st.sidebar:
    st.title("⚙️ Admin Panel")
    if st.button("🔓 Logout Admin", use_container_width=True):
        st.session_state["admin_authenticated"] = False
        st.rerun()
    
    st.divider()
    all_data = conn.query("SELECT * FROM scores ORDER BY proposal_title ASC;", ttl=0)
    if not all_data.empty:
        pdf_file = generate_pdf(all_data, CRITERIA_COLS)
        st.download_button(label="📥 Download Full PDF", data=pdf_file, file_name=f"ASM_Full_Report.pdf", mime="application/pdf", use_container_width=True)

# --- 7. DASHBOARD UI (Main Content) ---
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
        avg_score = prop_df['total'].mean()
        # Rubric Percentage calculation: (Avg Score / Max Possible 5.0) * 100
        score_percentage = (avg_score / 5.0) * 100

        st.markdown(f"<div class='proposal-header'>📂 Proposal: {proposal}</div>", unsafe_allow_html=True)
        
        # --- ADDED METRICS: MIN, MEDIAN, PERCENTAGE ---
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("Avg Score", f"{avg_score:.2f}")
        m2.metric("Percentage", f"{score_percentage:.1f}%")
        m3.metric("Median", f"{prop_df['total'].median():.2f}")
        m4.metric("Min Score", f"{prop_df['total'].min():.2f}")
        m5.metric("Max Score", f"{prop_df['total'].max():.2f}")
        m6.metric("Evaluators", len(prop_df))

        c1, c2 = st.columns([1, 1])
        with c1:
            fig_bar = px.bar(prop_df, x='evaluator', y='total', range_y=[0,5], 
                             title="Scores by Evaluator", color='total', color_continuous_scale='GnBu')
            st.plotly_chart(fig_bar, use_container_width=True, key=f"bar_{proposal}")
        with c2:
            avg_crit = prop_df[CRITERIA_COLS].mean()
            fig_radar = go.Figure(data=go.Scatterpolar(
                r=avg_crit.values, 
                theta=[c.replace('_', ' ').title() for c in CRITERIA_COLS], 
                fill='toself', line_color='#1E3A8A'
            ))
            fig_radar.update_layout(polar=dict(radialaxis=dict(range=[0, 5])), title="Criteria Performance (Rubric)")
            st.plotly_chart(fig_radar, use_container_width=True, key=f"radar_{proposal}")

        # --- UPDATED TABLE RENDERING (Fixes HTML tag display issue) ---
        with st.expander(f"View Detailed Reviews for {proposal}", expanded=True):
            header_row = "".join([f"<th class='col-crit'>{c.replace('_', ' ').title()}</th>" for c in CRITERIA_COLS])
            
            # Start building table as a clean string with NO leading spaces
            table_html = f"<table class='wrapped-table'><thead><tr><th class='col-eval'>Evaluator</th>{header_row}<th class='col-total'>Total</th><th class='col-rec'>Recommendation</th><th class='col-comm'>Comments</th></tr></thead><tbody>"
            
            for _, row in prop_df.iterrows():
                crit_data = "".join([f"<td class='col-crit'>{row.get(c, 0)}</td>" for c in CRITERIA_COLS])
                raw_comm = str(row.get('comments', '-')).replace('\n', '<br>')
                
                # Assemble row string flatly
                table_html += "<tr>"
                table_html += f"<td class='col-eval'><b>{row['evaluator']}</b></td>"
                table_html += crit_data
                table_html += f"<td class='col-total'>{row['total']:.2f}</td>"
                table_html += f"<td class='col-rec'>{row.get('recommendation', '-')}</td>"
                table_html += f"<td class='col-comm'><div class='comment-bubble'>{raw_comm}</div></td>"
                table_html += "</tr>"
            
            table_html += "</tbody></table>"
            st.markdown(table_html, unsafe_allow_html=True)
            
        st.divider()
else:
    st.title("📊 Live Evaluation Dashboard")
    st.info("Awaiting submissions...")
