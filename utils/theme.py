"""
eBay Hunter — Professional dark theme with custom CSS.
"""

import streamlit as st

# ─── Color Palette ──────────────────────────────────────────────
# eBay-inspired, modern dark theme
COLORS = {
    # Core
    "bg_primary":    "#0B1120",   # Deep navy background
    "bg_secondary":  "#111827",   # Card/panel background
    "bg_surface":    "#1E293B",   # Input/widget background
    "bg_hover":      "#334155",   # Hover state
    "border":        "#334155",   # Subtle borders
    "border_focus":  "#3B82F6",   # Focus ring

    # Text
    "text_primary":  "#F8FAFC",   # Main text
    "text_secondary":"#94A3B8",   # Secondary/muted text
    "text_dim":      "#64748B",   # Very muted

    # Brand
    "accent_blue":   "#3B82F6",   # Primary action
    "accent_red":    "#EF4444",   # eBay red, danger
    "accent_green":  "#10B981",   # Success, profit
    "accent_amber":  "#F59E0B",   # Warning
    "accent_purple": "#8B5CF6",   # Pending

    # Gradients
    "gradient_start":"#1E40AF",
    "gradient_end":  "#3B82F6",
}

CSS = f"""
<style>
/* ─── Global Reset ──────────────────────────────────────────── */
:root {{
    --bg-primary: {COLORS['bg_primary']};
    --bg-secondary: {COLORS['bg_secondary']};
    --bg-surface: {COLORS['bg_surface']};
    --bg-hover: {COLORS['bg_hover']};
    --border: {COLORS['border']};
    --border-focus: {COLORS['border_focus']};
    --text-primary: {COLORS['text_primary']};
    --text-secondary: {COLORS['text_secondary']};
    --text-dim: {COLORS['text_dim']};
    --accent-blue: {COLORS['accent_blue']};
    --accent-red: {COLORS['accent_red']};
    --accent-green: {COLORS['accent_green']};
    --accent-amber: {COLORS['accent_amber']};
    --accent-purple: {COLORS['accent_purple']};
}}

/* ─── App Container ─────────────────────────────────────────── */
.stApp {{
    background: linear-gradient(135deg, var(--bg-primary) 0%, #0F172A 50%, #0B1120 100%);
    color: var(--text-primary);
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}}

/* ─── Sidebar ───────────────────────────────────────────────── */
section[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, #0F172A 0%, #1E293B 100%) !important;
    border-right: 1px solid var(--border) !important;
    padding-top: 1rem;
}}
section[data-testid="stSidebar"] .stMarkdown h1 {{
    color: var(--text-primary) !important;
    font-size: 1.5rem !important;
    font-weight: 700 !important;
    letter-spacing: -0.02em;
}}
section[data-testid="stSidebar"] .stMarkdown h2,
section[data-testid="stSidebar"] .stMarkdown h3 {{
    color: var(--text-primary) !important;
}}
section[data-testid="stSidebar"] .stMarkdown p {{
    color: var(--text-secondary) !important;
}}
section[data-testid="stSidebar"] .stCaption {{
    color: var(--text-dim) !important;
}}

/* ─── Headers ───────────────────────────────────────────────── */
h1, h2, h3, h4, h5, h6 {{
    color: var(--text-primary) !important;
    font-weight: 600 !important;
    letter-spacing: -0.01em;
}}

/* ─── Cards / Containers ───────────────────────────────────── */
[data-testid="stExpander"] {{
    background: var(--bg-secondary) !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
    overflow: hidden;
}}
[data-testid="stExpander"] summary {{
    color: var(--text-primary) !important;
    font-weight: 500 !important;
}}
[data-testid="stExpander"] [data-testid="stExpanderDetails"] {{
    background: var(--bg-surface) !important;
}}

/* ─── Tabs ──────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {{
    gap: 4px;
    background: var(--bg-secondary);
    border-radius: 10px;
    padding: 4px;
    border: 1px solid var(--border);
}}
.stTabs [data-baseweb="tab"] {{
    background: transparent !important;
    color: var(--text-secondary) !important;
    border-radius: 8px !important;
    padding: 10px 20px !important;
    font-weight: 500 !important;
    transition: all 0.2s ease;
    border: none !important;
}}
.stTabs [data-baseweb="tab"]:hover {{
    background: var(--bg-hover) !important;
    color: var(--text-primary) !important;
}}
.stTabs [aria-selected="true"] {{
    background: var(--accent-blue) !important;
    color: white !important;
    font-weight: 600 !important;
    box-shadow: 0 2px 8px rgba(59, 130, 246, 0.3);
}}
.stTabs [data-baseweb="tab-highlight"] {{
    display: none !important;
}}
.stTabs [data-baseweb="tab-border"] {{
    display: none !important;
}}

/* ─── Buttons ───────────────────────────────────────────────── */
.stButton > button {{
    background: linear-gradient(135deg, var(--accent-blue) 0%, #2563EB 100%) !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 10px 24px !important;
    font-weight: 600 !important;
    letter-spacing: 0.01em;
    transition: all 0.2s ease !important;
    box-shadow: 0 2px 8px rgba(59, 130, 246, 0.25) !important;
}}
.stButton > button:hover {{
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 16px rgba(59, 130, 246, 0.4) !important;
    background: linear-gradient(135deg, #2563EB 0%, #1D4ED8 100%) !important;
}}
.stButton > button:active {{
    transform: translateY(0) !important;
}}
.stDownloadButton > button {{
    background: var(--bg-surface) !important;
    color: var(--text-primary) !important;
    border: 1px solid var(--border) !important;
}}

/* ─── Inputs ────────────────────────────────────────────────── */
.stTextInput > div > div > input,
.stNumberInput > div > div > input,
.stSelectbox > div > div,
.stTextArea > div > div > textarea {{
    background: var(--bg-surface) !important;
    color: var(--text-primary) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    transition: border-color 0.2s ease;
}}
.stTextInput > div > div > input:focus,
.stNumberInput > div > div > input:focus {{
    border-color: var(--accent-blue) !important;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15) !important;
}}
.stTextInput label, .stNumberInput label, .stSelectbox label,
.stTextArea label {{
    color: var(--text-secondary) !important;
    font-weight: 500 !important;
}}

/* ─── Sliders ───────────────────────────────────────────────── */
.stSlider > div > div > div > div {{
    background: var(--accent-blue) !important;
}}
.stSlider > div > div > div > div > div {{
    background: white !important;
    border: 2px solid var(--accent-blue) !important;
    box-shadow: 0 2px 6px rgba(59, 130, 246, 0.3);
}}

/* ─── Status Messages ───────────────────────────────────────── */
.stSuccess {{
    background: rgba(16, 185, 129, 0.1) !important;
    border: 1px solid rgba(16, 185, 129, 0.3) !important;
    border-radius: 10px !important;
    color: #6EE7B7 !important;
}}
.stError {{
    background: rgba(239, 68, 68, 0.1) !important;
    border: 1px solid rgba(239, 68, 68, 0.3) !important;
    border-radius: 10px !important;
    color: #FCA5A5 !important;
}}
.stWarning {{
    background: rgba(245, 158, 11, 0.1) !important;
    border: 1px solid rgba(245, 158, 11, 0.3) !important;
    border-radius: 10px !important;
    color: #FCD34D !important;
}}
.stInfo {{
    background: rgba(59, 130, 246, 0.1) !important;
    border: 1px solid rgba(59, 130, 246, 0.3) !important;
    border-radius: 10px !important;
    color: #93C5FD !important;
}}

/* ─── Status Bar ────────────────────────────────────────────── */
[data-testid="stStatus"] {{
    background: var(--bg-secondary) !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
}}
[data-testid="stStatus"] [data-testid="stStatusText"] {{
    color: var(--text-primary) !important;
    font-weight: 500 !important;
}}

/* ─── Metrics ───────────────────────────────────────────────── */
[data-testid="stMetric"] {{
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px 20px;
    transition: border-color 0.2s;
}}
[data-testid="stMetric"]:hover {{
    border-color: var(--accent-blue);
}}
[data-testid="stMetricValue"] {{
    color: var(--text-primary) !important;
    font-weight: 700 !important;
    font-size: 1.4rem !important;
}}
[data-testid="stMetricLabel"] {{
    color: var(--text-secondary) !important;
    font-weight: 500 !important;
    text-transform: uppercase !important;
    font-size: 0.75rem !important;
    letter-spacing: 0.05em !important;
}}
[data-testid="stMetricDelta"] > div {{
    font-weight: 600 !important;
}}

/* ─── Dividers ──────────────────────────────────────────────── */
hr {{
    border: none !important;
    border-top: 1px solid var(--border) !important;
    margin: 1rem 0 !important;
}}

/* ─── Code Blocks ───────────────────────────────────────────── */
.stCodeBlock, pre {{
    background: var(--bg-surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
}}

/* ─── Scrollbar ─────────────────────────────────────────────── */
::-webkit-scrollbar {{
    width: 6px;
    height: 6px;
}}
::-webkit-scrollbar-track {{
    background: var(--bg-primary);
}}
::-webkit-scrollbar-thumb {{
    background: var(--bg-hover);
    border-radius: 3px;
}}
::-webkit-scrollbar-thumb:hover {{
    background: var(--text-dim);
}}

/* ─── DataFrame / Table ─────────────────────────────────────── */
[data-testid="stDataFrame"] {{
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
}}

/* ─── Spinner ───────────────────────────────────────────────── */
.stSpinner > div {{
    border-top-color: var(--accent-blue) !important;
}}

/* ─── Radio / Checkbox ──────────────────────────────────────── */
.stRadio > div {{
    gap: 8px;
}}
.stRadio label {{
    color: var(--text-secondary) !important;
}}
.stCheckbox label {{
    color: var(--text-secondary) !important;
}}
</style>
"""


def apply_theme():
    """Inject the custom CSS into the Streamlit page."""
    st.markdown(CSS, unsafe_allow_html=True)


# ─── Color Constants (importable) ───────────────────────────────
SUCCESS = "#10B981"
ERROR = "#EF4444"
WARNING = "#F59E0B"
INFO = "#3B82F6"
PENDING = "#8B5CF6"
PROFIT_GREEN = "#10B981"
LOSS_RED = "#EF4444"
