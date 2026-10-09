import streamlit as st
import requests

# Page Configuration
st.set_page_config(
    page_title="MedHistory - AI Clinical Co-Pilot",
    page_icon="💊",
    layout="wide"
)

# Backend API Endpoint
API_URL = "http://localhost:8000/analyze-prescription"

st.title("💊 MedHistory: Clinical Prescription Safety Agent")
st.markdown("*Upload a medical prescription or diagnostic report to automatically detect drugs, symptoms, and active medication conflicts.*")

# Sidebar - Patient Profile
st.sidebar.header("👤 Patient Profile")
patient_id = st.sidebar.text_input("Patient ID", value="patient_001")

st.sidebar.subheader("📋 Active Medication History")
if "med_history" not in st.session_state:
    st.session_state["med_history"] = ["Warfarin"]

for med in st.session_state["med_history"]:
    st.sidebar.markdown(f"- **{med}**")

st.sidebar.divider()
st.sidebar.info("💡 Powered by open-weight BioBERT models (`d4data/biomedical-ner-all`) and clinical interaction engines.")

# Main Interface Layout
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("📄 Upload Document")
    uploaded_file = st.file_uploader("Choose a prescription image (PNG/JPG)", type=["png", "jpg", "jpeg"])

    if uploaded_file is not None:
        st.image(uploaded_file, caption="Uploaded Prescription", use_container_width=True)
        
        if st.button("🔍 Analyze Prescription", type="primary"):
            with st.spinner("Extracting entities via BioBERT & checking drug interactions..."):
                try:
                    files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
                    params = {"patient_id": patient_id}
                    
                    response = requests.post(API_URL, params=params, files=files)
                    
                    if response.status_code == 200:
                        st.session_state["last_result"] = response.json()
                        st.success("Analysis Complete!")
                    else:
                        st.error(f"Error from backend API: {response.status_code}")
                except Exception as e:
                    st.error(f"Failed to connect to backend engine: {e}")

with col2:
    st.subheader("📊 Clinical Analysis & Safety Alerts")
    
    if "last_result" in st.session_state:
        res = st.session_state["last_result"]
        
        # Critical Safety Alert Banner
        if res.get("has_critical_warning"):
            st.error("🚨 CRITICAL CONTRAINDICATION DETECTED!")
        else:
            st.success("✅ No Severe Conflicts Detected")

        # Extracted Entities
        st.markdown("### Extracted Entities (BioBERT)")
        entities = res.get("extracted_entities", {})
        
        e_col1, e_col2, e_col3 = st.columns(3)
        with e_col1:
            st.metric("Drugs Found", len(entities.get("drugs", [])))
            st.write(entities.get("drugs", []))
        with e_col2:
            st.metric("Diseases/Symptoms", len(entities.get("diseases", [])))
            st.write(entities.get("diseases", []))
        with e_col3:
            st.metric("Dosages", len(entities.get("dosages", [])))
            st.write(entities.get("dosages", []))

        st.divider()

        # Interaction Alerts Card Section
        st.markdown("### ⚠️ Drug-Drug Interaction Alerts")
        alerts = res.get("safety_alerts", [])
        
        if alerts:
            for alert in alerts:
                severity = alert.get("severity", "Moderate")
                box_type = st.error if severity == "Major" else st.warning
                
                with box_type(f"**Conflict:** {alert.get('drug_1')} ↔ {alert.get('drug_2')} ({severity} Risk)"):
                    st.write(f"**Clinical Effect:** {alert.get('effect')}")
                    st.write(f"**Recommended Action:** {alert.get('action')}")
        else:
            st.info("No active drug conflicts found with current medication history.")

        # Updated Active Meds List
        st.session_state["med_history"] = res.get("active_medications", [])
    else:
        st.info("Upload a prescription on the left to display safety results.")