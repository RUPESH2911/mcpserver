#!/usr/bin/env python3
"""Test different HL7 parsing approaches"""

# Try the basic python-hl7 approach
try:
    import hl7
    print("✅ hl7 imported successfully")
    
    # Test message
    test_hl7 = "MSH|^~\\&|SYSTEM|SENDER|RECEIVER|DESTINATION|20250808120000||ADT^A01|12345|P|2.5\rPID|||98.12.21||Doe^John||19800101|M|||123 Main St^Anytown^ST^12345"
    
    # Try parsing
    try:
        msg = hl7.parse(test_hl7)
        print(f"✅ Parsed HL7 message: {type(msg)}")
        
        # Extract PID
        for segment in msg:
            if segment[0] == 'PID':
                patient_id = str(segment[3])
                print(f"✅ Found Patient ID: {patient_id}")
                break
                
    except Exception as e:
        print(f"❌ HL7 parsing failed: {e}")
        
        # Try alternative method
        try:
            # Split by segments manually
            segments = test_hl7.split('\r')
            for segment in segments:
                if segment.startswith('PID'):
                    fields = segment.split('|')
                    if len(fields) > 3:
                        patient_id = fields[3]
                        print(f"✅ Manual parsing found Patient ID: {patient_id}")
                        break
        except Exception as e2:
            print(f"❌ Manual parsing also failed: {e2}")
            
except ImportError as e:
    print(f"❌ Failed to import hl7: {e}")
    
# Fallback: Manual HL7 parsing
print("\n--- Testing manual HL7 parsing ---")
test_hl7_content = """MSH|^~\\&|SYSTEM|SENDER|RECEIVER|DESTINATION|20250808120000||ADT^A01|12345|P|2.5
PID|||98.12.21||Doe^John||19800101|M|||123 Main St^Anytown^ST^12345
OBX|1|TX|DIAG||Patient has chest pain and shortness of breath
NTE|1||Additional notes: Patient requires follow-up care"""

def manual_hl7_parse(hl7_text):
    """Manual HL7 parsing as fallback"""
    try:
        # Normalize line endings
        hl7_text = hl7_text.replace('\r\n', '\n').replace('\r', '\n')
        
        patient_id = None
        clinical_text = []
        
        lines = hl7_text.strip().split('\n')
        for line in lines:
            if not line.strip():
                continue
                
            fields = line.split('|')
            if len(fields) < 2:
                continue
                
            segment_type = fields[0].strip()
            
            if segment_type == 'PID' and len(fields) > 3:
                # PID segment - field 3 is patient ID
                patient_id = fields[3].strip()
                
            elif segment_type == 'OBX' and len(fields) > 5:
                # Observation segment - field 5 is observation value
                obs_value = fields[5].strip()
                if obs_value:
                    clinical_text.append(obs_value)
                    
            elif segment_type == 'NTE' and len(fields) > 3:
                # Notes segment - field 3 is comment
                note_text = fields[3].strip()
                if note_text:
                    clinical_text.append(note_text)
        
        report_text = '\n'.join(clinical_text) if clinical_text else "HL7 message processed"
        return patient_id, report_text
        
    except Exception as e:
        return None, f"Manual HL7 parsing error: {str(e)}"

# Test manual parsing
patient_id, report = manual_hl7_parse(test_hl7_content)
print(f"Manual parsing result:")
print(f"  Patient ID: {patient_id}")
print(f"  Report: {report}")
