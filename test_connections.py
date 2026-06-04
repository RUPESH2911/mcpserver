import requests
import pydicom
import os

# Test Orthanc connection
try:
    response = requests.get(
        "http://localhost:8042/system",
        auth=("orthanc", "orthanc"),
        timeout=10
    )
    print(f"Orthanc system status: {response.status_code}")
    if response.status_code == 200:
        print("✅ Orthanc is accessible")
    else:
        print(f"❌ Orthanc returned status: {response.status_code}")
        print(f"Response: {response.text}")
        
except Exception as e:
    print(f"❌ Cannot connect to Orthanc: {e}")

# Test FHIR connection
try:
    response = requests.get(
        "http://localhost:8080/fhir/metadata",
        timeout=10
    )
    print(f"FHIR metadata status: {response.status_code}")
    if response.status_code == 200:
        print("✅ FHIR server is accessible")
    else:
        print(f"❌ FHIR returned status: {response.status_code}")
        
except Exception as e:
    print(f"❌ Cannot connect to FHIR: {e}")

# Test a sample DICOM file upload
try:
    dicom_file = "uploads/P1001_IMG1.dcm"
    if os.path.exists(dicom_file):
        print(f"\n📁 Testing DICOM file: {dicom_file}")
        
        # Read DICOM to check if it's valid
        ds = pydicom.dcmread(dicom_file, stop_before_pixels=True)
        print(f"✅ DICOM file is readable")
        print(f"Patient ID: {ds.get('PatientID', 'UNKNOWN')}")
        print(f"Study UID: {ds.get('StudyInstanceUID', 'UNKNOWN')}")
        
        # Try uploading to Orthanc
        with open(dicom_file, "rb") as f:
            response = requests.post(
                "http://localhost:8042/instances",
                auth=("orthanc", "orthanc"),
                headers={"Content-Type": "application/dicom"},
                data=f.read(),
                timeout=30
            )
        print(f"Upload status: {response.status_code}")
        if response.status_code in (200, 201):
            print("✅ DICOM upload successful")
        else:
            print(f"❌ Upload failed: {response.text}")
    else:
        print(f"❌ DICOM file not found: {dicom_file}")
        
except Exception as e:
    print(f"❌ Error testing DICOM upload: {e}")
