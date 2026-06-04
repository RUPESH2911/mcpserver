import sys
sys.path.append('.')
import hl7

# Test HL7 parsing step by step
file_path = 'uploads/98.12.21_report.hl7'

print("🔍 Debugging HL7 Parsing Step by Step")
print("=" * 45)

try:
    with open(file_path, 'r', encoding='utf-8') as f:
        hl7_text = f.read()
    
    print(f"📄 File content preview:")
    print(hl7_text[:200] + "...")
    
    # Parse HL7 message
    msg = hl7.parse(hl7_text)
    print(f"\n✅ HL7 message parsed successfully")
    print(f"📊 Number of segments: {len(msg)}")
    
    # Debug each segment
    for i, segment in enumerate(msg):
        seg_type = str(segment[0][0]) if len(segment) > 0 and len(segment[0]) > 0 else "UNKNOWN"
        print(f"   Segment {i}: {seg_type} (length: {len(segment)})")
        
        if seg_type == 'PID':
            print(f"      PID segment details:")
            for j, field in enumerate(segment):
                if j <= 5:  # Show first few fields
                    print(f"         Field {j}: {field}")
            
            # Try to extract patient ID
            if len(segment) > 3 and len(segment[3]) > 0:
                patient_id = str(segment[3][0])
                print(f"      ✅ Extracted Patient ID: '{patient_id}'")
            else:
                print(f"      ❌ Could not extract Patient ID")
        
        elif seg_type == 'OBX':
            print(f"      OBX segment - observation data")
            if len(segment) > 5 and len(segment[5]) > 0:
                obs_value = str(segment[5][0])
                print(f"         Observation: {obs_value[:50]}...")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
