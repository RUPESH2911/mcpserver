#!/usr/bin/env python3
"""Test HL7 library API to find the correct parsing method"""

import hl7

# Check what methods are available in the hl7 module
print("Available hl7 methods:")
methods = [method for method in dir(hl7) if not method.startswith('_')]
for method in methods:
    print(f"  - {method}")

# Test with a simple HL7 message
test_hl7 = """MSH|^~\\&|SYSTEM|SENDER|RECEIVER|DESTINATION|20250808120000||ADT^A01|12345|P|2.5
PID|||98.12.21||Doe^John||19800101|M|||123 Main St^Anytown^ST^12345"""

print(f"\nTesting with sample HL7 message...")

# Try different parsing methods
try:
    if hasattr(hl7, 'parse'):
        print("Testing hl7.parse()...")
        msg = hl7.parse(test_hl7)
        print(f"✅ hl7.parse() works: {type(msg)}")
    else:
        print("❌ hl7.parse() not available")
except Exception as e:
    print(f"❌ hl7.parse() failed: {e}")

try:
    if hasattr(hl7, 'parse_message'):
        print("Testing hl7.parse_message()...")
        msg = hl7.parse_message(test_hl7)
        print(f"✅ hl7.parse_message() works: {type(msg)}")
    else:
        print("❌ hl7.parse_message() not available")
except Exception as e:
    print(f"❌ hl7.parse_message() failed: {e}")

# Try with proper line endings
test_hl7_proper = test_hl7.replace('\n', '\r\n')

try:
    if hasattr(hl7, 'parse'):
        print("Testing hl7.parse() with \\r\\n...")
        msg = hl7.parse(test_hl7_proper)
        print(f"✅ hl7.parse() with \\r\\n works: {type(msg)}")
        # Try to extract PID
        for segment in msg:
            if str(segment[0]).strip() == 'PID':
                patient_id = str(segment[3])
                print(f"✅ Found Patient ID: {patient_id}")
    else:
        print("❌ hl7.parse() not available")
except Exception as e:
    print(f"❌ hl7.parse() with \\r\\n failed: {e}")

print(f"\nHL7 library version info:")
print(f"hl7.__version__: {getattr(hl7, '__version__', 'Not available')}")
print(f"hl7.__file__: {getattr(hl7, '__file__', 'Not available')}")
