"""
app.py – Streamlit dashboard for Azure OpenAI cost data.

Reads the normalised parquet file produced by the collector CLI and renders:
  - KPI cards (total tokens, total cost, effective price, avg discount %)
  - Stacked bar: cost by meter per subscription
  - Line: daily cost trend
  - Table: top 20 meters by cost with effective price and discount
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_PARQUET = Path("data/normalized/openai_cost_last_month.parquet")
PARQUET_PATH = Path(
    os.environ.get("COST_DASHBOARD_PARQUET", str(DEFAULT_PARQUET))
)

st.set_page_config(
    page_title="Azure OpenAI Cost Dashboard",
    page_icon="💰",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@st.cache_data(show_spinner="Loading data …")
def load_data(path: Path) -> pd.DataFrame:
    """Load the parquet file and coerce column types."""
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)

    # Coerce types
    for col in ("total_quantity", "total_cost", "avg_effective_price",
                "avg_payg_price", "discount_pct", "discount_abs",
                "effective_price_per_1m"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

    return df


def fmt_number(val: float, decimals: int = 2) -> str:
    return f"{val:,.{decimals}f}"


# ---------------------------------------------------------------------------
# Main dashboard
# ---------------------------------------------------------------------------


def main() -> None:
    st.title("💰 Azure OpenAI Cost Dashboard")
    st.caption("Last month's token usage, effective prices, and discounts across all subscriptions.")

    # Load data
    df = load_data(PARQUET_PATH)

    if df.empty:
        st.warning(
            "No data found.  Run the collector first:\n\n"
            "```bash\n"
            "python -m src.collect.cli collect --month last\n"
            "```"
        )
        st.info(f"Expected parquet at: `{PARQUET_PATH}`")
        return

    # ---------------------------------------------------------------------------
    # Sidebar filters
    # ---------------------------------------------------------------------------
    st.sidebar.header("Filters")

    # Subscription filter
    sub_col = "subscription_id" if "subscription_id" in df.columns else None
    if sub_col:
        all_subs = sorted(df[sub_col].dropna().unique().tolist())
        selected_subs = st.sidebar.multiselect(
            "Subscription", all_subs, default=all_subs
        )
        df = df[df[sub_col].isin(selected_subs)] if selected_subs else df

    # Meter filter
    meter_col = "meter_name" if "meter_name" in df.columns else None
    if meter_col:
        all_meters = sorted(df[meter_col].dropna().unique().tolist())
        selected_meters = st.sidebar.multiselect(
            "Meter (Input/Output/PTU)", all_meters, default=all_meters
        )
        df = df[df[meter_col].isin(selected_meters)] if selected_meters else df

    # Date range filter
    if "date" in df.columns and df["date"].notna().any():
        min_date = df["date"].min().date()
        max_date = df["date"].max().date()
        date_range = st.sidebar.date_input(
            "Date range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )
        if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
            start, end = date_range
            df = df[(df["date"].dt.date >= start) & (df["date"].dt.date <= end)]

    if df.empty:
        st.warning("No data matches the current filters.")
        return

    # ---------------------------------------------------------------------------
    # KPI Cards
    # ---------------------------------------------------------------------------
    qty_col = "total_quantity" if "total_quantity" in df.columns else "quantity"
    cost_col = "total_cost" if "total_cost" in df.columns else "cost"
    eff_col = (
        "effective_price_per_1m"
        if "effective_price_per_1m" in df.columns
        else "avg_effective_price"
    )
    disc_col = "discount_pct" if "discount_pct" in df.columns else None
    currency = (
        df["currency"].dropna().iloc[0] if "currency" in df.columns and not df.empty else ""
    )

    total_tokens = df[qty_col].sum() if qty_col in df.columns else 0
    total_cost = df[cost_col].sum() if cost_col in df.columns else 0
    avg_eff = df[eff_col].mean() if eff_col in df.columns else 0
    avg_disc = df[disc_col].mean() if disc_col else 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Tokens", f"{total_tokens:,.0f}")
    col2.metric("Total Cost", f"{total_cost:,.2f} {currency}")
    col3.metric("Avg Eff. Price / 1M Tokens", f"{avg_eff:,.4f} {currency}")
    col4.metric("Avg Discount %", f"{avg_disc:.1f}%")

    st.divider()

    # ---------------------------------------------------------------------------
    # Visualisations
    # ---------------------------------------------------------------------------

    # 1. Stacked bar: cost by meter per subscription
    if sub_col and meter_col and cost_col in df.columns:
        st.subheader("Cost by Meter per Subscription")
        bar_df = (
            df.groupby([sub_col, meter_col], dropna=False)[cost_col]
            .sum()
            .reset_index()
        )
        fig_bar = px.bar(
            bar_df,
            x=sub_col,
            y=cost_col,
            color=meter_col,
            barmode="stack",
            labels={
                sub_col: "Subscription",
                cost_col: f"Cost ({currency})",
                meter_col: "Meter",
            },
            title="Cost by Meter per Subscription",
        )
        fig_bar.update_layout(xaxis_tickangle=-30)
        st.plotly_chart(fig_bar, use_container_width=True)

    # 2. Line: daily cost trend
    if "date" in df.columns and cost_col in df.columns:
        st.subheader("Daily Cost Trend")
        daily_df = (
            df.groupby(df["date"].dt.date)[cost_col]
            .sum()
            .reset_index()
            .rename(columns={"date": "Day", cost_col: f"Cost ({currency})"})
        )
        fig_line = px.line(
            daily_df,
            x="Day",
            y=f"Cost ({currency})",
            markers=True,
            title="Daily Azure OpenAI Cost",
        )
        st.plotly_chart(fig_line, use_container_width=True)

    # 3. Table: top 20 meters by cost
    st.subheader("Top 20 Meters by Cost")
    display_cols = [c for c in [
        meter_col,
        sub_col,
        "product_name",
        qty_col,
        cost_col,
        "avg_effective_price",
        "avg_payg_price",
        "discount_pct",
        "effective_price_per_1m",
        "currency",
    ] if c and c in df.columns]

    top20 = (
        df[display_cols]
        .sort_values(cost_col, ascending=False)
        .head(20)
        .reset_index(drop=True)
        if cost_col in df.columns
        else df[display_cols].head(20)
    )

    # Format for display
    fmt_df = top20.copy()
    for col in (qty_col, cost_col):
        if col in fmt_df.columns:
            fmt_df[col] = fmt_df[col].apply(lambda v: f"{v:,.2f}")
    for col in ("avg_effective_price", "avg_payg_price", "effective_price_per_1m"):
        if col in fmt_df.columns:
            fmt_df[col] = fmt_df[col].apply(lambda v: f"{v:,.6f}")
    if "discount_pct" in fmt_df.columns:
        fmt_df["discount_pct"] = fmt_df["discount_pct"].apply(lambda v: f"{v:.1f}%")

    st.dataframe(fmt_df, use_container_width=True)

    # ---------------------------------------------------------------------------
    # Raw data expander
    # ---------------------------------------------------------------------------
    with st.expander("Raw data"):
        st.dataframe(df, use_container_width=True)

    st.caption(f"Data source: `{PARQUET_PATH}` · {len(df):,} rows")


if __name__ == "__main__":
    main()
else:
    # When run via `streamlit run`, Streamlit imports the module, so call main()
    main()
