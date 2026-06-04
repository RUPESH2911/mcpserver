import pydicom
import os

# Check all DICOM files in uploads directory
upload_dir = "uploads"
dicom_files = [f for f in os.listdir(upload_dir) if f.endswith('.dcm')]

print(f"Found {len(dicom_files)} DICOM files:")

for filename in dicom_files:
    filepath = os.path.join(upload_dir, filename)
    try:
        print(f"\n📁 Checking: {filename}")
        ds = pydicom.dcmread(filepath, stop_before_pixels=True)
        print(f"✅ File is readable")
        print(f"   Patient ID: {ds.get('PatientID', 'MISSING')}")
        print(f"   Study UID: {ds.get('StudyInstanceUID', 'MISSING')}")
        print(f"   Modality: {ds.get('Modality', 'MISSING')}")
        print(f"   Transfer Syntax: {ds.file_meta.get('TransferSyntaxUID', 'MISSING')}")
        
    except Exception as e:
        print(f"❌ Error reading {filename}: {e}")
        # Try to read just the file header
        try:
            with open(filepath, 'rb') as f:
                header = f.read(200)
                print(f"   First 200 bytes: {header}")
        except:
            print("   Cannot read file at all")
