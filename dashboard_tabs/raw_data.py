"""Raw Data tab: the visualization sample as a browsable table."""
import streamlit as st


def render(ctx):
    viz_df = ctx.viz_df

    st.subheader("Data Inspector")
    st.dataframe(viz_df.head(1000), width="stretch")
    st.caption("Showing first 1000 rows of visualization sample.")

    csv = viz_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        "⬇️ Download Sample Data as CSV",
        csv,
        "swot_sample_data.csv",
        "text/csv",
        key='download-csv'
    )

# === TEMPORAL RESULTS TAB (static, one-time analysis; local + Streamlit Cloud) ===
