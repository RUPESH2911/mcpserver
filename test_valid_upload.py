import requests
import pydicom

# Test uploading a valid DICOM file
valid_file = "uploads/98.12.21.dcm"

try:
    print(f"Testing upload of valid DICOM file: {valid_file}")
    
    # First verify the file
    ds = pydicom.dcmread(valid_file, stop_before_pixels=True)
    print(f"✅ File verification:")
    print(f"   Patient ID: {ds.get('PatientID')}")
    print(f"   Study UID: {ds.get('StudyInstanceUID')}")
    print(f"   Modality: {ds.get('Modality')}")
    
    # Upload to Orthanc
    with open(valid_file, "rb") as f:
        response = requests.post(
            "http://localhost:8042/instances",
            auth=("orthanc", "orthanc"),
            headers={"Content-Type": "application/dicom"},
            data=f.read(),
            timeout=30
        )
    
    print(f"\n📤 Upload result:")
    print(f"   Status: {response.status_code}")
    
    if response.status_code in (200, 201):
        print("✅ Upload successful!")
        result = response.json()
        print(f"   Instance ID: {result.get('ID', 'N/A')}")
    else:
        print(f"❌ Upload failed: {response.text}")
        
except Exception as e:
    print(f"❌ Error: {e}")
