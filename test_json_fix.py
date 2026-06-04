import sys
sys.path.append('.')
from app import parse_patient_data_file

# Test the FHIR JSON files
test_files = [
    'uploads/P1001.json', 
    'uploads/P1002.json',
    'uploads/P1001_patient_data.json',
    'uploads/P1002_patient_data.json'
]

print("🧪 Testing JSON File Parsing")
print("=" * 40)

for file_path in test_files:
    try:
        pid, report = parse_patient_data_file(file_path)
        if pid:
            print(f"✅ {file_path}")
            print(f"   Patient ID: {pid}")
            print(f"   Report: {report[:100]}...")
        else:
            print(f"❌ {file_path}: {report}")
    except Exception as e:
        print(f"❌ {file_path}: Error - {e}")
    print()
