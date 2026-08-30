import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime, timedelta
import numpy as np

st.set_page_config(page_title="Alba PIP", layout="wide", page_icon="🧬")
st.title("🧬 Alba Portfolio Intelligence Platform")
st.caption("**Live Mock Feeds** — Xero (Finance) • BambooHR (HR) • Plaid (Banking) • yfinance (Benchmarks) | Professional Executive Reports")

# ====================== MOCK BACKEND ======================
@st.cache_data
def mock_xero_finance():
    return {
        "cash_balance": 412500,
        "runway_months": 4.8,
        "monthly_burn": -138000,
        "revenue_actual": 261000,
        "revenue_budget": 300000,
        "gross_margin": 62,
        "last_updated": "4 hours ago"
    }

@st.cache_data
def mock_bamboohr_data():
    return {
        "headcount": 29,
        "plan_headcount": 32,
        "attrition_rate": 14,
        "voluntary_attrition": 11,
        "last_updated": "Yesterday"
    }

@st.cache_data
def mock_plaid_banking():
    return {
        "current_balance": 412500,
        "last_30d_outflow": -245000,
        "last_30d_inflow": 112000,
        "last_updated": "2 hours ago"
    }

@st.cache_data
def mock_yfinance_benchmarks():
    tickers = ["^IXIC", "SPY", "^VIX"]
    data = yf.download(tickers, period="6mo")['Adj Close']
    return data

# ====================== SIDEBAR – ON-DEMAND PULLS ======================
st.sidebar.header("🔌 On-Demand Data Feeds")
if st.sidebar.button("📊 Pull Finance Data (Xero)"):
    st.session_state.finance = mock_xero_finance()
    st.sidebar.success("✅ Xero Demo Connected")

if st.sidebar.button("👥 Pull HR Data (BambooHR)"):
    st.session_state.hr = mock_bamboohr_data()
    st.sidebar.success("✅ BambooHR Connected")

if st.sidebar.button("🏦 Pull Banking Data (Plaid)"):
    st.session_state.banking = mock_plaid_banking()
    st.sidebar.success("✅ Plaid Sandbox Connected")

if st.sidebar.button("📈 Pull Benchmarks (yfinance)"):
    st.session_state.benchmarks = mock_yfinance_benchmarks()
    st.sidebar.success("✅ Market benchmarks loaded")

# ====================== PORTFOLIO OVERVIEW ======================
st.header("📊 Portfolio Overview")
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Portfolio Companies", "4")
col2.metric("Avg Health Score", "68", "↑3")
col3.metric("Red Alerts", "1")
col4.metric("Avg Cash Runway", "6.1 mo", "↓0.4")
col5.metric("Data Freshness", "On-Demand")

# ====================== COMPANY DEEP DIVE ======================
st.header("🔍 Company Deep Dive – Acme AI (Demo)")
finance = st.session_state.get("finance", mock_xero_finance())
hr = st.session_state.get("hr", mock_bamboohr_data())
banking = st.session_state.get("banking", mock_plaid_banking())

tab_finance, tab_hr, tab_banking, tab_bench, tab_ai = st.tabs([
    "Finance (Xero)", "HR (BambooHR)", "Banking (Plaid)", "Benchmarks", "AI Executive Summary"
])

with tab_finance:
    st.subheader("Finance Report – Xero")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cash Balance", f"${finance['cash_balance']:,.0f}")
    c2.metric("Cash Runway", f"{finance['runway_months']} months")
    c3.metric("Monthly Burn", f"${finance['monthly_burn']:,.0f}")
    c4.metric("Revenue vs Budget", f"{finance['revenue_actual']/finance['revenue_budget']*100:.0f}%")

    # Cash Waterfall
    fig_waterfall = go.Figure(go.Waterfall(
        name="Cash Flow", orientation="v",
        measure=["relative", "relative", "total"],
        x=["Operating Inflows", "Operating Outflows", "Ending Cash"],
        y=[finance['revenue_actual'], finance['monthly_burn'], finance['cash_balance']]))
    fig_waterfall.update_layout(title="Cash Waterfall (Xero-style)", height=400)
    st.plotly_chart(fig_waterfall, use_container_width=True)

    # Revenue Bridge
    fig_pnl = px.bar(x=["Budget", "Actual", "Variance"], y=[300000, 261000, -39000],
                     title="Revenue vs Budget Bridge")
    st.plotly_chart(fig_pnl, use_container_width=True)

with tab_hr:
    st.subheader("HR Report – BambooHR")
    c1, c2, c3 = st.columns(3)
    c1.metric("Headcount", hr['headcount'])
    c2.metric("Attrition Rate", f"{hr['attrition_rate']}%")
    c3.metric("Voluntary Attrition", f"{hr['voluntary_attrition']}%")
    dates = pd.date_range(end=datetime.today(), periods=6, freq='M')
    fig_hr = px.line(x=dates, y=[28, 29, 31, 30, 27, 29], title="Headcount Trend")
    st.plotly_chart(fig_hr, use_container_width=True)

with tab_banking:
    st.subheader("Banking Report – Plaid")
    st.metric("Current Balance", f"${banking['current_balance']:,.0f}")
    trans_dates = pd.date_range(end=datetime.today(), periods=8, freq='D')
    amounts = [-45000, 12000, -8000, -22000, 15000, -35000, 8000, -18000]
    fig_bank = px.bar(x=trans_dates, y=amounts, title="Recent Transactions")
    st.plotly_chart(fig_bank, use_container_width=True)

with tab_bench:
    st.subheader("Benchmark Report")
    bench_data = st.session_state.get("benchmarks", mock_yfinance_benchmarks())
    fig_bench = px.line(bench_data, title="Portfolio vs Market Indices (6 months)")
    st.plotly_chart(fig_bench, use_container_width=True)

with tab_ai:
    st.subheader("🤖 AI Executive Summary")
    if st.button("Generate Board-Ready Narrative"):
        st.markdown(f"""
        **Acme AI – Amber (Health Score 68/100)**  
        Finance (Xero): Cash runway **{finance['runway_months']} months** and declining.  
        HR (BambooHR): Attrition **{hr['attrition_rate']}%**.  
        Banking (Plaid): Net outflows accelerating.  
        **GP Action**: Escalate collections and freeze non-essential hiring.
        """)

st.caption("✅ Alba PIP Prototype • Mocked backend • Beautiful executive visuals • Ready for real API integration")