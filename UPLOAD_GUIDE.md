🎯 GEHE MCP Upload Instructions
==============================

📁 Files to Upload for Success:

✅ VALID DICOM FILES (these will work):
   - 98.12.21.dcm (Patient: 98.12.21)
   - P1001_valid.dcm (Patient: P1001)  
   - P1002_valid.dcm (Patient: P1002)

❌ CORRUPTED DICOM FILES (avoid these):
   - P1001_IMG1.dcm
   - P1001_IMG2.dcm
   - P1002_IMG1.dcm
   - P1002_IMG2.dcm

✅ PATIENT DATA FILES (these will work):
   JSON Format:
   - P1001.json (FHIR Patient format)
   - P1002.json (FHIR Patient format)
   - 98.12.21_patient_data.json (Clinical data format)
   
   HL7 Format:
   - 98.12.21_report.hl7
   - P1001_report.hl7
   - P1002_report.hl7

🚀 Expected Results:
   When you upload valid files, you should see:
   - ✅ "Successfully processed DICOM: filename (Patient: ID)"
   - ✅ "Successfully processed patient data: filename (Patient: ID)"  
   - ✅ "Queued AI for PID [ID] (N images)"

⚠️  Important:
   - Use only the valid DICOM files ending with "_valid.dcm" or "98.12.21.dcm"
   - The corrupted P1001_IMG*.dcm files will cause 400 errors

🔧 To Clean Up:
   You can delete the corrupted files:
   - P1001_IMG1.dcm, P1001_IMG2.dcm
   - P1002_IMG1.dcm, P1002_IMG2.dcm
