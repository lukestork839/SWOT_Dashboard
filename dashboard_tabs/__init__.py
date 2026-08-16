"""Per-tab renderers for the SWOT dashboards.

Each module exposes render(ctx) taking a common.TabContext; common.py holds the
shared presentation constants, helpers, and Streamlit cache wrappers. The
researcher entrypoint (dashboard_swot.py) renders every tab; the village
entrypoint composes a subset from the same modules.
"""
