import sys
sys.path.append('.')
import hl7

# Test basic HL7 parsing
file_path = 'uploads/98.12.21_report.hl7'

print("🔍 Simple HL7 Debug")
print("=" * 30)

try:
    with open(file_path, 'r', encoding='utf-8') as f:
        hl7_text = f.read()
    
    print("Original text:")
    print(repr(hl7_text[:100]))
    
    # Try with \r\n conversion
    hl7_text_fixed = hl7_text.replace('\n', '\r\n')
    print("\nAfter \\r\\n conversion:")
    print(repr(hl7_text_fixed[:100]))
    
    # Parse and show segments
    msg = hl7.parse(hl7_text_fixed)
    print(f"\nParsed message segments: {len(msg)}")
    
    for i, segment in enumerate(msg):
        if len(segment) > 0:
            print(f"  Segment {i}: {segment[0]} with {len(segment)} fields")
            
            if str(segment[0]) == 'PID':
                print(f"    PID field 3: {segment[3] if len(segment) > 3 else 'MISSING'}")
            elif str(segment[0]) == 'OBX':
                print(f"    OBX field 5: {segment[5] if len(segment) > 5 else 'MISSING'}")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
