"""Display the scoring owner's methodology and the data-source limitations."""
import streamlit as st

from src import config
from src.report_generator import methodology_text


def render() -> None:
    """Render the shared methodology document when available."""
    st.title("Methodology")
    if content := methodology_text():
        st.markdown(content)
    else:
        st.info("The scoring methodology document has not been supplied in this build.")
    st.subheader("Data sources and limitations")
    st.markdown(
        "- SEC EDGAR supplies public filing data where available. Coverage varies by company.\n"
        "- Uploaded PDFs and manual inputs require analyst confirmation.\n"
        "- Missing data may prevent ratios or the full score from being calculated.\n"
        "- Synthetic fixtures are for demonstration and testing."
    )
    st.caption(config.FINANCIAL_INSTITUTION_MESSAGE)
    st.caption(config.SCORE_DISCLAIMER)
