import requests
import json
import os

def test_file_upload():
    """Test the complete file upload workflow"""
    
    print("🧪 Testing GEHE MCP File Upload Workflow")
    print("=" * 50)
    
    # Test data
    dicom_files = [
        "uploads/P1001_valid.dcm",
        "uploads/P1002_valid.dcm"
    ]
    
    hl7_files = [
        "uploads/P1001_report.hl7",
        "uploads/P1002_report.hl7"
    ]
    
    # Check if files exist
    print("📁 Checking test files:")
    for file_path in dicom_files + hl7_files:
        if os.path.exists(file_path):
            print(f"   ✅ {file_path}")
        else:
            print(f"   ❌ {file_path} - FILE MISSING")
            return
    
    print("\n🌐 Testing Flask app upload endpoint:")
    
    try:
        # Prepare files for upload
        files = []
        
        # Add DICOM files
        for dicom_file in dicom_files:
            with open(dicom_file, 'rb') as f:
                files.append(('dicoms', (os.path.basename(dicom_file), f.read(), 'application/dicom')))
        
        # Add HL7 files
        for hl7_file in hl7_files:
            with open(hl7_file, 'rb') as f:
                files.append(('hl7data', (os.path.basename(hl7_file), f.read(), 'text/plain')))
        
        # Make the request to Flask app (assuming it's running on port 5000)
        response = requests.post(
            'http://localhost:5000/',
            files=files,
            timeout=30
        )
        
        print(f"   Status Code: {response.status_code}")
        
        if response.status_code == 200:
            print("   ✅ Upload request successful")
            print("   📄 Response content preview:")
            content = response.text[:500]
            print(f"   {content}...")
        else:
            print(f"   ❌ Upload failed: {response.text}")
            
    except requests.exceptions.ConnectionError:
        print("   ⚠️  Flask app not running. Start it with: python app.py")
    except Exception as e:
        print(f"   ❌ Error: {e}")

if __name__ == "__main__":
    test_file_upload()
