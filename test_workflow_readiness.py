import os

def test_file_availability():
    """Test if all required files exist for the workflow"""
    
    print("🧪 Testing File Availability for Complete Workflow")
    print("=" * 55)
    
    # Test DICOM files
    dicom_files = [
        "uploads/P1001_valid.dcm",
        "uploads/P1002_valid.dcm",
        "uploads/98.12.21_sample.dcm"
    ]
    
    # Test JSON patient data files
    json_files = [
        "uploads/P1001_patient_data.json",
        "uploads/P1002_patient_data.json",
        "uploads/98.12.21_patient_data.json"
    ]
    
    print("📁 DICOM Files:")
    dicom_available = 0
    for file_path in dicom_files:
        if os.path.exists(file_path):
            size = os.path.getsize(file_path)
            print(f"   ✅ {file_path} ({size:,} bytes)")
            dicom_available += 1
        else:
            print(f"   ❌ {file_path} - MISSING")
    
    print(f"\n📄 JSON Patient Data Files:")
    json_available = 0
    for file_path in json_files:
        if os.path.exists(file_path):
            size = os.path.getsize(file_path)
            print(f"   ✅ {file_path} ({size:,} bytes)")
            json_available += 1
        else:
            print(f"   ❌ {file_path} - MISSING")
    
    print(f"\n📊 Summary:")
    print(f"   DICOM files available: {dicom_available}/3")
    print(f"   JSON files available: {json_available}/3")
    
    if dicom_available == 3 and json_available == 3:
        print("   🎉 All files ready for testing!")
        print("\n🚀 Next Steps:")
        print("   1. Start Flask app: python app.py")
        print("   2. Open browser: http://localhost:5000")
        print("   3. Upload DICOM and JSON files")
        print("   4. Expected result: 3 successful patient matches")
    else:
        print("   ⚠️  Some files are missing. Please create them first.")
    
    return dicom_available == 3 and json_available == 3

if __name__ == "__main__":
    test_file_availability()
