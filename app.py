"""
app.py  —  Streamlit UI for the XML Pipeline
---------------------------------------------
Run with:  streamlit run app.py
"""

import streamlit as st
import pandas as pd
import tempfile
import zipfile
import io
from pathlib import Path

from generator import generate_layout, save_layout
from validator import validate_file
from reporter  import html_report, text_report

st.set_page_config(
    page_title="Chip Layout XML Pipeline",
    page_icon="🔬",
    layout="wide",
)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🔬 XML Pipeline")
    st.caption("Chip Layout Generator · Validator · Reporter")
    st.divider()
    page = st.radio("Navigate", ["Generate", "Validate", "Report"], label_visibility="collapsed")

# ── Page: Generate ────────────────────────────────────────────────────────────
if page == "Generate":
    st.title("Generate Chip Layout XML")
    st.caption("Configure layouts below, then generate and download valid XML files.")

    st.subheader("Layout configurations")
    default_data = pd.DataFrame([
        {"project_name": "Alpha_Test",       "created_by": "Anson", "description": "Alpha mask test",         "num_components": 10, "num_test_points": 5, "layer_count": 3},
        {"project_name": "Beta_Integration", "created_by": "Anson", "description": "Beta integration run",    "num_components": 8,  "num_test_points": 4, "layer_count": 2},
        {"project_name": "Gamma_HiRes",      "created_by": "Anson", "description": "High resolution layout",  "num_components": 15, "num_test_points": 7, "layer_count": 4},
    ])
    df = st.data_editor(default_data, num_rows="dynamic", use_container_width=True)

    if st.button("Generate XML files", type="primary"):
        configs = df.to_dict("records")
        if not configs:
            st.warning("Add at least one row.")
        else:
            zip_buf = io.BytesIO()
            xml_texts = {}
            with zipfile.ZipFile(zip_buf, "w") as zf:
                for cfg in configs:
                    try:
                        root  = generate_layout(
                            project_name    = str(cfg["project_name"]),
                            created_by      = str(cfg["created_by"]),
                            description     = str(cfg["description"]),
                            num_components  = int(cfg["num_components"]),
                            num_test_points = int(cfg["num_test_points"]),
                            layer_count     = int(cfg["layer_count"]),
                        )
                        fname = str(cfg["project_name"]).replace(" ", "_") + ".xml"
                        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tf:
                            save_layout(root, tf.name)
                            content = Path(tf.name).read_text()
                        zf.writestr(fname, content)
                        xml_texts[fname] = content
                        st.success(f"Generated: {fname}")
                    except Exception as e:
                        st.error(f"{cfg['project_name']}: {e}")

            zip_buf.seek(0)
            st.download_button(
                label="Download all as ZIP",
                data=zip_buf,
                file_name="chip_layouts.zip",
                mime="application/zip",
            )

            st.subheader("Preview")
            sel = st.selectbox("Select a file to preview", list(xml_texts.keys()))
            if sel:
                st.code(xml_texts[sel], language="xml")

# ── Page: Validate ────────────────────────────────────────────────────────────
elif page == "Validate":
    st.title("Validate XML Layouts")
    st.caption("Upload one or more XML files to validate against the chip layout XSD schema.")

    uploaded = st.file_uploader(
        "Upload XML file(s)", type=["xml"], accept_multiple_files=True
    )

    if uploaded:
        if st.button("Run validation", type="primary"):
            results = []
            for uf in uploaded:
                with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tf:
                    tf.write(uf.read())
                    tf_path = tf.name
                res = validate_file(tf_path)
                res["file"] = uf.name
                results.append(res)

            st.session_state["validation_results"] = results

    if "validation_results" in st.session_state:
        results = st.session_state["validation_results"]
        passed  = sum(1 for r in results if r["valid"])
        failed  = len(results) - passed

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total",     len(results))
        c2.metric("Passed",    passed,  delta=None)
        c3.metric("Failed",    failed,  delta=None)
        c4.metric("Pass rate", f"{100*passed/len(results):.0f}%" if results else "N/A")

        st.divider()

        for r in results:
            icon = "✅" if r["valid"] else "❌"
            with st.expander(f"{icon} {r['file']}  ({r['elapsed']*1000:.1f} ms)"):
                if r["stats"]:
                    s = r["stats"]
                    cols = st.columns(5)
                    cols[0].metric("Layout ID",   s.get("layout_id", "?"))
                    cols[1].metric("Project",     s.get("project_name", "?"))
                    cols[2].metric("Layers",      s.get("layers", 0))
                    cols[3].metric("Components",  s.get("components", 0))
                    cols[4].metric("Test points", s.get("test_points", 0))
                if r["errors"]:
                    st.error("Validation errors:")
                    for e in r["errors"]:
                        st.code(e)

# ── Page: Report ──────────────────────────────────────────────────────────────
elif page == "Report":
    st.title("Validation Report")
    st.caption("Upload XML files to generate a downloadable HTML and text report.")

    uploaded = st.file_uploader(
        "Upload XML file(s)", type=["xml"], accept_multiple_files=True, key="report_upload"
    )

    if uploaded:
        if st.button("Generate report", type="primary"):
            results = []
            for uf in uploaded:
                with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tf:
                    tf.write(uf.read())
                    tf_path = tf.name
                res = validate_file(tf_path)
                res["file"] = uf.name
                results.append(res)

            html = html_report(results)
            txt  = text_report(results)

            st.subheader("HTML report preview")
            st.components.v1.html(html, height=500, scrolling=True)

            col1, col2 = st.columns(2)
            with col1:
                st.download_button("Download HTML report", html,
                                   file_name="report.html", mime="text/html")
            with col2:
                st.download_button("Download text report", txt,
                                   file_name="report.txt",  mime="text/plain")

            st.subheader("Plain text")
            st.code(txt)
