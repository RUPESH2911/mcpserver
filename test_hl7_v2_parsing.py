import sys
sys.path.append('.')
from app import parse_hl7_message

# Test the updated HL7 parsing with existing HL7 files
test_files = [
    'uploads/98.12.21_report.hl7',
    'uploads/P1001_report.hl7',
    'uploads/P1002_report.hl7',
    'uploads/hl7_dataset_patient_98.12.21_enriched.hl7'
]

print("🧪 Testing Updated HL7 v2.x Parsing")
print("=" * 45)

for file_path in test_files:
    try:
        print(f"\n📄 Testing: {file_path}")
        pid, report = parse_hl7_message(file_path)
        if pid:
            print(f"   ✅ Patient ID: {pid}")
            print(f"   📋 Report Preview: {report[:150]}...")
        else:
            print(f"   ❌ Failed: {report}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

print("\n🎯 HL7 parsing test complete!")
