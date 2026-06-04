import os
import re
import json
import uuid
import time
import logging
import requests
import pydicom
from flask import Flask, request, render_template, redirect, url_for, flash, jsonify, Response, send_file
from werkzeug.utils import secure_filename
from dicomweb_client.api import DICOMwebClient
from requests.auth import HTTPBasicAuth
from requests import Session
from datetime import datetime
from dotenv import load_dotenv
import markdown
import subprocess
import shutil

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default image placeholder (optional)
NO_IMAGE_PATH = os.path.join(os.path.dirname(__file__), "static", "no-image.png")

# ─── CONFIG ──────────────────────────────────────────────────────────────────
class Config:
    ORTHANC_URL = "http://localhost:8042"
    ORTHANC_AUTH = ("orthanc", "orthanc")
    FHIR_URL = "http://localhost:8080/fhir"
    FHIR_HDR = {"Content-Type": "application/fhir+json"}

    UPLOAD_FOLDER = "uploads"
    ALLOWED_DCM = {"dcm", "DCM"}
    ALLOWED_PATIENT_DATA = {"json", "hl7", "txt"}

    AI_DATA_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "ai_data"))

# Load environment variables from .env file
load_dotenv()

# ─── APP SETUP ────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = "replace-this-with-a-secure-random-key"

# Ensure upload and AI data folders exist
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["AI_DATA_PATH"], exist_ok=True)

# ─── DICOMWEB CLIENT ─────────────────────────────────────────────────────────
session = Session()
session.auth = HTTPBasicAuth(*app.config["ORTHANC_AUTH"])
dicom_client = DICOMwebClient(
    url=f"{app.config['ORTHANC_URL']}/dicom-web",
    session=session
)

# Global variable to track conversion status
conversion_status = {}

# ─── IMPROVED FHIR FUNCTIONS ────────────────────────────────────────────────
def validate_fhir_resource(resource):
    """Validate FHIR resource structure"""
    required_fields = {
        'Patient': ['resourceType', 'id'],
        'Observation': ['resourceType', 'status', 'code', 'subject'],
        'DiagnosticReport': ['resourceType', 'status', 'code', 'subject'],
        'ImagingStudy': ['resourceType', 'id', 'status', 'subject'] 
    }
    
    resource_type = resource.get('resourceType')
    if not resource_type:
        return False, "Missing resourceType"
    
    if resource_type in required_fields:
        for field in required_fields[resource_type]:
            if field not in resource:
                return False, f"Missing required field: {field}"
    
    return True, "Valid"

def upload_fhir_resource_with_retry(resource, resource_type, max_retries=3):
    """Upload a single FHIR resource with deduplication: update if exists, else create new."""
    # Validate resource first
    is_valid, validation_msg = validate_fhir_resource(resource)
    if not is_valid:
        logger.error(f"Invalid {resource_type} resource: {validation_msg}")
        return False, f"Validation failed: {validation_msg}"
    logger.info(f"Validated {resource_type} resource successfully")
    resource_json = json.dumps(resource, indent=2)
    logger.info(f"Uploading {resource_type} JSON:\n{resource_json}")
    for attempt in range(max_retries):
        try:
            # For DiagnosticReport and Observation, check if one exists for this patient and code
            if resource_type in ("DiagnosticReport", "Observation"):
                patient_ref = resource["subject"]["reference"]
                code_text = resource["code"].get("text", "")
                search_url = f"{Config.FHIR_URL}/{resource_type}?subject={patient_ref}"
                if code_text:
                    search_url += f"&code={code_text}"
                logger.info(f"Searching for existing {resource_type}: {search_url}")
                search_resp = requests.get(search_url, headers=Config.FHIR_HDR, timeout=15)
                existing_id = None
                if search_resp.status_code == 200:
                    data = search_resp.json()
                    if data.get('entry'):
                        existing_id = data['entry'][0]['resource']['id']
                if existing_id:
                    # Update existing resource
                    url = f"{Config.FHIR_URL}/{resource_type}/{existing_id}"
                    method = "PUT"
                    logger.info(f"Updating existing {resource_type} {existing_id} via PUT {url}")
                    response = requests.put(url, headers=Config.FHIR_HDR, json=resource, timeout=30)
                else:
                    # Create new resource
                    url = f"{Config.FHIR_URL}/{resource_type}"
                    method = "POST"
                    logger.info(f"POSTing {resource_type} to {url}")
                    response = requests.post(url, headers=Config.FHIR_HDR, json=resource, timeout=30)
            elif resource_type == "Patient" or resource_type == "ImagingStudy":
                resource_id = resource['id']
                url = f"{Config.FHIR_URL}/{resource_type}/{resource_id}"
                method = "PUT"
                logger.info(f"PUTting {resource_type} to {url}")
                response = requests.put(url, headers=Config.FHIR_HDR, json=resource, timeout=30)

            logger.info(f"FHIR {resource_type} {method} attempt {attempt + 1}: HTTP {response.status_code}")
            logger.info(f"Response headers: {dict(response.headers)}")
            logger.info(f"Response body: {response.text}")

            if response.status_code in (200, 201):
                logger.info(f"Successfully uploaded {resource_type}")
                # For DiagnosticReport, log the assigned id
                if resource_type == "DiagnosticReport":
                    try:
                        dr_id = response.json().get('id')
                        logger.info(f"DiagnosticReport assigned id: {dr_id}")
                    except Exception:
                        pass
                return True, "Success"
            elif response.status_code == 400:
                # Bad request - parse the error for more details
                try:
                    error_response = response.json()
                    if 'issue' in error_response:
                        issues = error_response['issue']
                        error_details = []
                        for issue in issues:
                            diagnostics = issue.get('diagnostics', '')
                            severity = issue.get('severity', 'error')
                            error_details.append(f"{severity}: {diagnostics}")
                        error_detail = '; '.join(error_details)
                    else:
                        error_detail = response.text
                except:
                    error_detail = response.text if response.text else "Bad Request"

                logger.error(f"Bad request for {resource_type}: {error_detail}")
                return False, f"Bad request: {error_detail}"
            elif response.status_code == 422:
                # Unprocessable entity - validation error
                try:
                    error_response = response.json()
                    if 'issue' in error_response:
                        issues = error_response['issue']
                        error_details = []
                        for issue in issues:
                            diagnostics = issue.get('diagnostics', '')
                            error_details.append(diagnostics)
                        error_detail = '; '.join(error_details)
                    else:
                        error_detail = response.text
                except:
                    error_detail = response.text if response.text else "Validation Error"

                logger.error(f"Validation error for {resource_type}: {error_detail}")
                return False, f"Validation error: {error_detail}"
            else:
                # Other errors - retry
                error_detail = response.text if response.text else f"HTTP {response.status_code}"
                logger.warning(f"Upload failed for {resource_type} (attempt {attempt + 1}): {error_detail}")

                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    return False, f"Upload failed after {max_retries} attempts: {error_detail}"

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error for {resource_type} (attempt {attempt + 1}): {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                return False, f"Connection failed after {max_retries} attempts"
        except requests.exceptions.Timeout as e:
            logger.error(f"Timeout error for {resource_type} (attempt {attempt + 1}): {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                return False, f"Timeout after {max_retries} attempts"
        except Exception as e:
            logger.error(f"Unexpected error for {resource_type}: {str(e)}")
            return False, f"Unexpected error: {str(e)}"

    return False, "Maximum retries exceeded"

def test_fhir_server_connection():
    """Test if FHIR server is accessible"""
    try:
        response = requests.get(f"{Config.FHIR_URL}/metadata", timeout=10)
        return response.status_code == 200
    except:
        return False

# ─── HL7 TO FHIR CONVERSION ─────────────────────────────────────────────────
def convert_hl7_to_fhir(hl7_file_path, patient_id, clinical_text, diagnostic_content=None):
    """Convert HL7 data to FHIR resources including Procedures, Medications, and ImagingStudy if present"""
    try:
        # Use the HL7 Patient ID directly for identifier/reference, but sanitize for FHIR id
        orig_patient_id = (patient_id or "").strip()
        # Sanitize for FHIR id (replace dots and other non-alphanum with dash)
        safe_patient_id = re.sub(r'[^A-Za-z0-9\-]', '-', orig_patient_id)[:64] or f"patient-{abs(hash(orig_patient_id)) % 100000}"

        # Create stable, deterministic IDs
        observation_id = f"obs-{abs(hash(f'{orig_patient_id}-observation')) % 100000}"
        diagnostic_report_id = f"dr-{abs(hash(f'{orig_patient_id}-diagnostic-report')) % 100000}"

        # Use proper ISO 8601 datetime format
        current_time = datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')

        logger.info(f"Creating FHIR resources for patient {patient_id}")
        logger.info(f"Patient FHIR ID: {safe_patient_id}")
        logger.info(f"DiagnosticReport ID: {diagnostic_report_id}")
        logger.info(f"DateTime: {current_time}")

        # Create Patient resource
        patient_resource = {
            "resourceType": "Patient",
            "id": safe_patient_id,
            "identifier": [
                {
                    "use": "usual",
                    "system": "http://hospital.org/patients",
                    "value": orig_patient_id
                }
            ],
            "name": [
                {
                    "use": "official",
                    "family": "Patient",
                    "given": [orig_patient_id]
                }
            ],
            "gender": "unknown",
            "active": True
        }

        # Create Observation resource (simplified)
        observation_resource = {
            "resourceType": "Observation",
            "id": f"obs-{abs(hash(f'{orig_patient_id}-observation')) % 100000}",
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                            "code": "survey",
                            "display": "Survey"
                        }
                    ]
                }
            ],
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "72133-2",
                        "display": "Clinical note"
                    }
                ]
            },
            "subject": {
                "reference": f"Patient/{safe_patient_id}"
            },
            "effectiveDateTime": current_time,
            "valueString": clinical_text[:1000] if clinical_text else "No clinical text provided"
        }

        # Build conclusion content from HL7 OBX segments
        conclusion_parts = []

        # Add diagnostic content if available
        if diagnostic_content:
            # Add discharge summary first if available (highest priority)
            if diagnostic_content.get('discharge_summary'):
                conclusion_parts.append("=== DISCHARGE SUMMARY ===")
                conclusion_parts.extend(diagnostic_content['discharge_summary'])
                conclusion_parts.append("")

            # Add findings from OBX segments
            if diagnostic_content.get('findings'):
                conclusion_parts.append("FINDINGS:")
                conclusion_parts.extend([f"- {finding}" for finding in diagnostic_content['findings']])
                conclusion_parts.append("")

            # Add impressions/conclusions
            if diagnostic_content.get('impressions'):
                conclusion_parts.append("IMPRESSION:")
                conclusion_parts.extend([f"- {impression}" for impression in diagnostic_content['impressions']])
                conclusion_parts.append("")

            # Add recommendations
            if diagnostic_content.get('recommendations'):
                conclusion_parts.append("RECOMMENDATIONS:")
                conclusion_parts.extend([f"- {rec}" for rec in diagnostic_content['recommendations']])
                conclusion_parts.append("")

            # Add diagnosis codes
            if diagnostic_content.get('diagnosis_codes'):
                conclusion_parts.append("DIAGNOSES:")
                for diag in diagnostic_content['diagnosis_codes']:
                    conclusion_parts.append(f"- {diag['code']}: {diag['description']}")
                conclusion_parts.append("")

            # Add procedure codes
            if diagnostic_content.get('procedure_codes'):
                conclusion_parts.append("PROCEDURES:")
                for proc in diagnostic_content['procedure_codes']:
                    conclusion_parts.append(f"- {proc['code']}: {proc['description']}")
                conclusion_parts.append("")

            # Add general report text
            if diagnostic_content.get('report_text'):
                conclusion_parts.append("ADDITIONAL NOTES:")
                conclusion_parts.extend([f"- {text}" for text in diagnostic_content['report_text']])

        # Ensure we always have conclusion content
        conclusion_text = '\n'.join(conclusion_parts).strip()
        if not conclusion_text:
            conclusion_text = clinical_text if clinical_text else "No clinical content available from HL7 OBX segments"

        # Create FHIR-compliant DiagnosticReport resource
        diagnostic_report = {
            "resourceType": "DiagnosticReport",
            # REMOVE "id" to let FHIR server assign one (use POST, not PUT)
            "status": "final",
            "code": {
                "text": "Report"
            },
            "subject": {
                "reference": f"Patient/{safe_patient_id}"
            },
            "effectiveDateTime": current_time,
            "issued": current_time,
            "conclusion": conclusion_text
        }        
        
        # ─── ImagingStudy Resource (if image UIDs exist in diagnostic_content) ───
        image_uids = []
        if diagnostic_content and diagnostic_content.get("image_uids"):
            image_uids = list(set(diagnostic_content["image_uids"]))  # deduplicate

        imaging_study_resource = None
        imaging_study_id = None
        if image_uids:
            imaging_study_id = f"imgstudy-{abs(hash(orig_patient_id)) % 100000}"
            imaging_study_resource = {
                "resourceType": "ImagingStudy",
                "id": imaging_study_id,
                "status": "available",
                "subject": {
                    "reference": f"Patient/{safe_patient_id}"
                },
                "started": current_time,
                "series": [
                    {
                        "uid": uid,
                        "instance": [
                            {
                                "uid": uid,
                                "sopClass": {
                                    "system": "urn:ietf:rfc:3986",
                                    "code": "1.2.840.10008.5.1.4.1.1.2",
                                    "display": "CT Image Storage"
                                }
                            }
                        ]
                    }
                    for uid in image_uids
                ]
            }

            # Reference ImagingStudy in DiagnosticReport
            diagnostic_report["imagingStudy"] = [
                {"reference": f"ImagingStudy/{imaging_study_id}"}
            ]

        # Add category based on content type
        is_discharge = diagnostic_content and diagnostic_content.get('discharge_summary')
        if is_discharge:
            diagnostic_report["category"] = [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                            "code": "DS",
                            "display": "Discharge Summary"
                        }
                    ]
                }
            ]
            diagnostic_report["code"] = {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "18842-5",
                        "display": "Discharge summary"
                    }
                ],
                "text": "Discharge Summary Report"
            }
        else:
            diagnostic_report["category"] = [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                            "code": "LAB",
                            "display": "Laboratory"
                        }
                    ]
                }
            ]
            diagnostic_report["code"] = {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "11502-2",
                        "display": "Laboratory report"
                    }
                ],
                "text": "Clinical Report"
            }

        logger.info(f"DiagnosticReport conclusion length: {len(conclusion_text)}")
        logger.info(f"DiagnosticReport JSON structure complete")

        # Build Procedure resources from PR1
        procedure_resources = []
        if diagnostic_content and diagnostic_content.get('procedure_codes'):
            for pr in diagnostic_content['procedure_codes']:
                code_text = f"{pr.get('code','')} {pr.get('description','')}".strip()
                pr_id = f"proc-{abs(hash(code_text + safe_patient_id)) % 100000}"
                procedure_resources.append({
                    "resourceType": "Procedure",
                    "id": pr_id,
                    "status": "completed",
                    "code": {"text": code_text},
                    "subject": {"reference": f"Patient/{safe_patient_id}"},
                    "performedDateTime": current_time
                })

        # Build MedicationRequest resources from RXO/RXE
        medreq_resources = []
        if diagnostic_content and diagnostic_content.get('medication_requests'):
            for mr in diagnostic_content['medication_requests']:
                text = (mr.get('text') or '').strip()
                instr = (mr.get('instruction') or '').strip()
                if not text:
                    continue
                mr_id = f"medreq-{abs(hash(text + instr + safe_patient_id)) % 100000}"
                medreq_resources.append({
                    "resourceType": "MedicationRequest",
                    "id": mr_id,
                    "status": "active",
                    "intent": "order",
                    "medicationCodeableConcept": {"text": text},
                    "subject": {"reference": f"Patient/{safe_patient_id}"},
                    "authoredOn": current_time,
                    "dosageInstruction": [{"text": instr or text}]
                })

        # Build MedicationStatement resources from RXA
        medstmt_resources = []
        if diagnostic_content and diagnostic_content.get('medication_statements'):
            for ms in diagnostic_content['medication_statements']:
                text = (ms.get('text') or '').strip()
                instr = (ms.get('instruction') or '').strip()
                if not text:
                    continue
                ms_id = f"medstmt-{abs(hash(text + instr + safe_patient_id)) % 100000}"
                medstmt_resources.append({
                    "resourceType": "MedicationStatement",
                    "id": ms_id,
                    "status": "active",
                    "medicationCodeableConcept": {"text": text},
                    "subject": {"reference": f"Patient/{safe_patient_id}"},
                    "effectiveDateTime": current_time,
                    "dateAsserted": current_time,
                    "dosage": [{"text": instr or text}]
                })

        logger.info(f"Converted HL7 data to FHIR resources for patient {patient_id}")

        return {
            "patient": patient_resource,
            "observation": observation_resource,
            "diagnostic_report": diagnostic_report,
            "imaging_study": imaging_study_resource,
            "procedures": procedure_resources,
            "medication_requests": medreq_resources,
            "medication_statements": medstmt_resources,
        }
    except Exception as e:
        logger.error(f"HL7 to FHIR conversion error: {str(e)}")
        raise Exception(f"HL7 to FHIR conversion failed: {str(e)}")

def upload_fhir_resources(fhir_resources, patient_id):
    """Upload FHIR resources including Procedures, MedicationRequest, MedicationStatement"""
    try:
        # Test server connection first
        if not test_fhir_server_connection():
            logger.error("FHIR server connection test failed")
            return {
                'patient': False,
                'observation': False,
                'diagnostic_report': False,
                'error': 'FHIR server is not accessible'
            }
        
        logger.info("FHIR server connection successful")
        results = {}
        detailed_errors = []
        
        # Upload Patient first
        logger.info(f"Uploading Patient resource for {patient_id}")
        success, message = upload_fhir_resource_with_retry(
            fhir_resources['patient'], 'Patient'
        )
        results['patient'] = success
        if not success:
            detailed_errors.append(f"Patient: {message}")
            logger.error(f"Patient upload failed: {message}")
        else:
            logger.info(f"Patient upload successful for {patient_id}")

        # Upload ImagingStudy (if available)
        if results['patient'] and fhir_resources.get('imaging_study'):
            logger.info(f"Uploading ImagingStudy for {patient_id}")
            success, message = upload_fhir_resource_with_retry(
                fhir_resources['imaging_study'], 'ImagingStudy'
            )
            results['imaging_study'] = success
            if not success:
                detailed_errors.append(f"ImagingStudy: {message}")
                logger.error(f"ImagingStudy upload failed: {message}")
            else:
                logger.info(f"ImagingStudy upload successful for {patient_id}")
        else:
            results['imaging_study'] = False
            if fhir_resources.get('imaging_study'):
                detailed_errors.append("ImagingStudy: Skipped due to Patient upload failure")

        
        # Upload DiagnosticReport - this is the priority resource
        if results['patient']:
            logger.info(f"Uploading DiagnosticReport for {patient_id}")
            
            success, message = upload_fhir_resource_with_retry(
                fhir_resources['diagnostic_report'], 'DiagnosticReport'
            )
            results['diagnostic_report'] = success
            if not success:
                detailed_errors.append(f"DiagnosticReport: {message}")
                logger.error(f"DiagnosticReport upload failed: {message}")
            else:
                logger.info(f"DiagnosticReport upload successful for {patient_id}")
                
                # Additional verification: Query the FHIR server to confirm DiagnosticReport exists
                try:
                    dr_id = fhir_resources['diagnostic_report']['id']
                    verify_url = f"{Config.FHIR_URL}/DiagnosticReport/{dr_id}"
                    verify_response = requests.get(verify_url, headers=Config.FHIR_HDR, timeout=30)
                    
                    if verify_response.status_code == 200:
                        logger.info(f"✅ DiagnosticReport {dr_id} confirmed in FHIR server")
                        
                        # Also check total count
                        count_url = f"{Config.FHIR_URL}/DiagnosticReport"
                        count_response = requests.get(count_url, headers=Config.FHIR_HDR, timeout=30)
                        if count_response.status_code == 200:
                            count_data = count_response.json()
                            total = count_data.get('total', 0)
                            logger.info(f"Total DiagnosticReports in server: {total}")
                    else:
                        logger.warning(f"⚠ Could not verify DiagnosticReport {dr_id} after upload")
                except Exception as ve:
                    logger.error(f"Error verifying DiagnosticReport: {str(ve)}")
        else:
            results['diagnostic_report'] = False
            detailed_errors.append("DiagnosticReport: Skipped due to Patient upload failure")
            logger.warning("DiagnosticReport skipped - Patient upload failed")
        
        # Upload Observation (lower priority)
        if results['patient']:
            logger.info(f"Uploading Observation for {patient_id}")
            success, message = upload_fhir_resource_with_retry(
                fhir_resources['observation'], 'Observation'
            )
            results['observation'] = success
            if not success:
                detailed_errors.append(f"Observation: {message}")
                logger.error(f"Observation upload failed: {message}")
            else:
                logger.info(f"Observation upload successful for {patient_id}")
        else:
            results['observation'] = False
            detailed_errors.append("Observation: Skipped due to Patient upload failure")
        
        # Upload Procedures
        if results.get('patient') and fhir_resources.get('procedures'):
            proc_ok = True
            for pr in fhir_resources['procedures']:
                ok, msg = upload_fhir_resource_with_retry(pr, 'Procedure')
                proc_ok = proc_ok and ok
                if not ok:
                    detailed_errors.append(f"Procedure: {msg}")
            results['procedures'] = proc_ok
        else:
            results['procedures'] = False
        # MedicationRequest
        if results.get('patient') and fhir_resources.get('medication_requests'):
            mr_ok = True
            for mr in fhir_resources['medication_requests']:
                ok, msg = upload_fhir_resource_with_retry(mr, 'MedicationRequest')
                mr_ok = mr_ok and ok
                if not ok:
                    detailed_errors.append(f"MedicationRequest: {msg}")
            results['medication_requests'] = mr_ok
        else:
            results['medication_requests'] = False
        # MedicationStatement
        if results.get('patient') and fhir_resources.get('medication_statements'):
            ms_ok = True
            for ms in fhir_resources['medication_statements']:
                ok, msg = upload_fhir_resource_with_retry(ms, 'MedicationStatement')
                ms_ok = ms_ok and ok
                if not ok:
                    detailed_errors.append(f"MedicationStatement: {msg}")
            results['medication_statements'] = ms_ok
        else:
            results['medication_statements'] = False

        if detailed_errors:
            results['error'] = '; '.join(detailed_errors)
        
        logger.info(f"Final upload results for {patient_id}: {results}")
        return results
        
    except Exception as e:
        logger.error(f"FHIR upload error for {patient_id}: {str(e)}")
        return {
            'patient': False,
            'observation': False,
            'diagnostic_report': False,
            'error': f"Upload process failed: {str(e)}"
        }

# ─── HELPERS ─────────────────────────────────────────────────────────────────
def allowed_file(filename, allowed_exts):
    return "." in filename and filename.rsplit(".", 1)[1] in allowed_exts

def parse_hl7_message(file_path):
    """Parse HL7 message and extract PatientID, clinical text, and diagnostic report content including discharge summary, procedures, meds, and image UIDs"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            hl7_text = f.read()
        hl7_text = hl7_text.replace('\r\n', '\n').replace('\r', '\n')
        patient_id = None
        clinical_text = []
        diagnostic_report_content = {
            'findings': [],
            'impressions': [],
            'recommendations': [],
            'procedure_codes': [],
            'diagnosis_codes': [],
            'report_text': [],
            'discharge_summary': [],
            'image_uids': [],
            'medication_requests': [],
            'medication_statements': []
        }
        # simple helpers for meds
        def _mk_med(dc, route=None, dose=None, units=None, freq=None):
            parts = []
            if dose and units:
                parts.append(f"{dose} {units}")
            if route:
                parts.append(route)
            if freq:
                parts.append(freq)
            return dc, ", ".join([p for p in parts if p])

        lines = hl7_text.strip().split('\n')
        for line in lines:
            if not line.strip():
                continue
            fields = line.split('|')
            if len(fields) < 2:
                continue
            seg = fields[0].strip().upper()

            if seg == 'PID' and len(fields) > 3:
                raw_pid = fields[3].strip()
                patient_id = raw_pid.split('^')[0] if '^' in raw_pid else raw_pid

            elif seg == 'OBX' and len(fields) > 5:
                obs_value = fields[5].strip()
                if obs_value:
                    clinical_text.append(obs_value)
                    # extract Series UIDs if present in OBX text
                    for m in re.findall(r"Series:([0-9.]+)", obs_value):
                        diagnostic_report_content['image_uids'].append(m)
                if len(fields) > 3:
                    obs_id = fields[3].strip().upper()
                    if any(k in obs_id for k in ['DISCHARGE', 'DSCH', 'SUMMARY']):
                        diagnostic_report_content['discharge_summary'].append(obs_value)
                    elif 'FINDING' in obs_id or 'RESULT' in obs_id:
                        diagnostic_report_content['findings'].append(obs_value)
                    elif 'IMPRESSION' in obs_id or 'CONCLUSION' in obs_id:
                        diagnostic_report_content['impressions'].append(obs_value)
                    elif 'RECOMMENDATION' in obs_id or 'SUGGEST' in obs_id:
                        diagnostic_report_content['recommendations'].append(obs_value)
                    else:
                        diagnostic_report_content['report_text'].append(obs_value)

            elif seg == 'NTE' and len(fields) > 3:
                note_text = fields[3].strip()
                if note_text:
                    clinical_text.append(note_text)
                    # extract Series UIDs in NTE too
                    for m in re.findall(r"Series:([0-9.]+)", note_text):
                        diagnostic_report_content['image_uids'].append(m)
                    note_upper = note_text.upper()
                    if any(keyword in note_upper for keyword in ['DISCHARGE SUMMARY', 'DISCHARGE:', 'SUMMARY:']):
                        diagnostic_report_content['discharge_summary'].append(note_text)
                    else:
                        diagnostic_report_content['report_text'].append(note_text)

            elif seg == 'DG1' and len(fields) > 3:
                diag_code = fields[3].strip()
                diag_desc = fields[4].strip() if len(fields) > 4 else ''
                if diag_code:
                    diagnostic_report_content['diagnosis_codes'].append({'code': diag_code, 'description': diag_desc})
                    clinical_text.append(f"Diagnosis: {diag_code} - {diag_desc}")

            elif seg == 'PR1' and len(fields) > 3:
                proc_code = fields[3].strip()
                proc_desc = fields[4].strip() if len(fields) > 4 else ''
                if proc_code:
                    diagnostic_report_content['procedure_codes'].append({'code': proc_code, 'description': proc_desc})
                    clinical_text.append(f"Procedure: {proc_code} - {proc_desc}")

            # Medication order (MedicationRequest) via RXO/RXE
            elif seg in ('RXO', 'RXE'):
                med_text = ''
                code_field = fields[2].strip() if len(fields) > 2 else ''  # common spot for med
                if code_field:
                    med_text = code_field.split('^')[1] if '^' in code_field else code_field
                dose = fields[3].strip() if len(fields) > 3 else ''
                units = fields[4].split('^')[1].strip() if len(fields) > 4 and '^' in fields[4] else (fields[4].strip() if len(fields) > 4 else '')
                route = fields[6].split('^')[1].strip() if len(fields) > 6 and '^' in fields[6] else (fields[6].strip() if len(fields) > 6 else '')
                freq = fields[7].strip() if len(fields) > 7 else ''
                name, instr = _mk_med(med_text or code_field, route, dose, units, freq)
                if name:
                    diagnostic_report_content['medication_requests'].append({
                        'text': name,
                        'instruction': instr
                    })

            # Medication administration (MedicationStatement) via RXA
            elif seg == 'RXA':
                med_text = fields[5].split('^')[1].strip() if len(fields) > 5 and '^' in fields[5] else (fields[5].strip() if len(fields) > 5 else '')
                dose = fields[6].strip() if len(fields) > 6 else ''
                units = fields[7].split('^')[1].strip() if len(fields) > 7 and '^' in fields[7] else (fields[7].strip() if len(fields) > 7 else '')
                route = fields[8].split('^')[1].strip() if len(fields) > 8 and '^' in fields[8] else (fields[8].strip() if len(fields) > 8 else '')
                name, instr = _mk_med(med_text, route, dose, units, None)
                if name:
                    diagnostic_report_content['medication_statements'].append({
                        'text': name,
                        'instruction': instr
                    })
        # dedupe image_uids
        diagnostic_report_content['image_uids'] = list(dict.fromkeys(diagnostic_report_content['image_uids']))
        report_text = '\n'.join(clinical_text) if clinical_text else "HL7 message processed"
        return patient_id, report_text, diagnostic_report_content
    except Exception as e:
        return None, f"Error parsing HL7: {str(e)}", None

def parse_json_patient_data(file_path):
    """Parse JSON file with patient data and extract PatientID and clinical text"""
    try:
        import json
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Handle FHIR Patient resource format
        if data.get("resourceType") == "Patient":
            patient_id = data.get("id")
            name_parts = []
            if "name" in data and len(data["name"]) > 0:
                name_obj = data["name"][0]
                if "given" in name_obj:
                    name_parts.extend(name_obj["given"])
                if "family" in name_obj:
                    name_parts.append(name_obj["family"])
            
            patient_name = " ".join(name_parts) if name_parts else "Unknown"
            report_text = f"FHIR Patient Resource - Name: {patient_name}, Gender: {data.get('gender', 'Unknown')}, Birth Date: {data.get('birthDate', 'Unknown')}"
            
            return patient_id, report_text
        
        # Handle custom patient data format
        patient_id = data.get("patientId") or data.get("PatientID") or data.get("patient_id") or data.get("id")
        
        # Get clinical text from various possible fields
        clinical_text = []
        
        if "clinicalText" in data:
            clinical_text.append(data["clinicalText"])
        if "clinical_text" in data:
            clinical_text.append(data["clinical_text"])
        if "diagnosis" in data:
            clinical_text.append(f"Diagnosis: {data['diagnosis']}")
        if "findings" in data:
            if isinstance(data["findings"], list):
                clinical_text.extend([f"Finding: {finding}" for finding in data["findings"]])
            else:
                clinical_text.append(f"Findings: {data['findings']}")
        if "reports" in data and isinstance(data["reports"], list):
            clinical_text.extend(data["reports"])
        if "conclusion" in data:
            clinical_text.append(f"Conclusion: {data['conclusion']}")
        if "recommendations" in data:
            clinical_text.append(f"Recommendations: {data['recommendations']}")
            
        report_text = '\n'.join(clinical_text) if clinical_text else "JSON patient data processed"
        
        return patient_id, report_text
        
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON format: {str(e)}"
    except Exception as e:
        return None, f"Error parsing JSON: {str(e)}"

def parse_patient_data_file(file_path):
    """Parse patient data file (JSON, HL7, or TXT) and extract PatientID, clinical text, and diagnostic content"""
    file_ext = file_path.split('.')[-1].lower()
    
    if file_ext == 'json':
        pid, report = parse_json_patient_data(file_path)
        return pid, report, None  # JSON doesn't have structured diagnostic content yet
    elif file_ext in ['hl7', 'txt']:
        # Try HL7 first, fallback to simple text format
        try:
            return parse_hl7_message(file_path)
        except:
            # Fallback to simple text format (first line = PatientID)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = f.read().splitlines()
                if lines:
                    patient_id = lines[0].strip()
                    report = '\n'.join(lines[1:]).strip() if len(lines) > 1 else "Text data processed"
                    return patient_id, report, None
                return None, "Empty file", None
            except Exception as e:
                return None, f"Error reading text file: {str(e)}", None
    else:
        return None, f"Unsupported file format: {file_ext}", None

# ─── ROUTES ──────────────────────────────────────────────────────────────────
@app.route("/", methods=["GET", "POST"])
def index():
    upload_success_message = None
    if request.method == "POST":
        # Test FHIR server connection at start
        if not test_fhir_server_connection():
            flash("FHIR server is not accessible. Please check the server status.", "error")
            return render_template("index.html")
        
        dicom_files = request.files.getlist("dicoms")
        hl7_files = request.files.getlist("hl7data")

        # 1) Process DICOM uploads and index by PatientID
        dicom_index = {}  # pid -> list of SOP Instance UIDs
        for f in dicom_files:
            if f and allowed_file(f.filename, Config.ALLOWED_DCM):
                fname = secure_filename(f.filename)
                path = os.path.join(Config.UPLOAD_FOLDER, fname)
                f.save(path)

                # upload to Orthanc
                try:
                    with open(path, "rb") as fp:
                        res = requests.post(
                            f"{Config.ORTHANC_URL}/instances",
                            auth=Config.ORTHANC_AUTH,
                            headers={"Content-Type": "application/dicom"},
                            data=fp.read(),
                            timeout=30
                        )
                    if res.status_code not in (200, 201):
                        flash(f"Failed to upload {fname} ({res.status_code}): {res.text[:100]}", "error")
                        continue
                except requests.exceptions.RequestException as e:
                    flash(f"Network error uploading {fname}: {str(e)}", "error")
                    continue

                # read header to get IDs
                try:
                    ds = pydicom.dcmread(path, stop_before_pixels=True)
                    pid = ds.get("PatientID", None)
                    study_uid = ds.get("StudyInstanceUID", None)
                    series_uid = ds.get("SeriesInstanceUID", None)
                    sop_uid = ds.get("SOPInstanceUID", None)
                    
                    # Validate required DICOM fields
                    if not pid:
                        flash(f"DICOM file {fname} missing PatientID", "warning")
                        continue
                    if not sop_uid:
                        flash(f"DICOM file {fname} missing SOPInstanceUID", "warning")
                        continue

                    # For now, just use the SOP Instance UID from the file directly
                    # instead of querying DICOMweb (which might be causing issues)
                    dicom_index.setdefault(pid, []).append(sop_uid)
                        
                except Exception as e:
                    flash(f"Error reading DICOM file {fname}: {str(e)}", "error")
                    continue

        # 2) Process Patient Data uploads with improved HL7 to FHIR conversion
        patient_data_index = {}
        conversion_results = []
        any_success = False
        for f in hl7_files:
            if f and allowed_file(f.filename, Config.ALLOWED_PATIENT_DATA):
                fname = secure_filename(f.filename)
                path = os.path.join(Config.UPLOAD_FOLDER, fname)
                f.save(path)

                # Parse patient data file to extract PatientID, clinical text, and diagnostic content
                result = parse_patient_data_file(path)
                if len(result) == 3:
                    pid, report, diagnostic_content = result
                else:
                    pid, report = result
                    diagnostic_content = None
                
                if not pid:
                    flash(f"Could not extract PatientID from file: {fname} - {report}", "warning")
                    continue
                
                patient_data_index[pid] = report
                
                # Create conversion ID for tracking
                conversion_id = str(uuid.uuid4())
                conversion_status[conversion_id] = {
                    "status": "processing",
                    "patient_id": pid,
                    "filename": fname,
                    "message": "Converting HL7 to FHIR..."
                }
                
                try:
                    # Convert HL7 to FHIR with diagnostic content
                    conversion_status[conversion_id]["message"] = "Creating FHIR resources with diagnostic content..."
                    fhir_resources = convert_hl7_to_fhir(path, pid, report, diagnostic_content)
                    
                    # Upload to FHIR server
                    conversion_status[conversion_id]["message"] = "Uploading to FHIR server..."
                    upload_results = upload_fhir_resources(fhir_resources, pid)
                    
                    # Check results and provide detailed feedback
                    successful_uploads = [k for k, v in upload_results.items() if k != 'error' and v]
                    failed_uploads = [k for k, v in upload_results.items() if k != 'error' and not v]
                    
                    # Consider success if Patient and DiagnosticReport are uploaded (prioritize these)
                    critical_success = upload_results.get('patient', False) and upload_results.get('diagnostic_report', False)
                    
                    if critical_success and len(failed_uploads) == 0:  # All succeeded
                        any_success = True
                        conversion_status[conversion_id] = {
                            "status": "success",
                            "patient_id": pid,
                            "filename": fname,
                            "message": f"Successfully converted and uploaded all FHIR resources with diagnostic summary for Patient {pid}"
                        }
                        flash(f"✅ Complete HL7 to FHIR conversion with diagnostic summary successful for Patient {pid}", "success")
                    elif critical_success:  # Patient and DiagnosticReport succeeded (most important)
                        any_success = True
                        conversion_status[conversion_id] = {
                            "status": "success",
                            "patient_id": pid,
                            "filename": fname,
                            "message": f"Successfully uploaded Patient and DiagnosticReport with summary for Patient {pid}. Some optional resources failed: {', '.join(failed_uploads)}"
                        }
                        flash(f"✅ HL7 to FHIR conversion with diagnostic summary successful for Patient {pid}. Diagnostic report uploaded successfully!", "success")
                    elif len(successful_uploads) > 0:  # Partial success
                        # ...existing code...
                        pass
                    else:  # All failed
                        # ...existing code...
                        pass
                except Exception as e:
                    # ...existing code...
                    pass
        # ...existing code...
        if conversion_results:
            resources = get_fhir_resources()
            if any_success:
                upload_success_message = "your files have been sucessfully uploaded and converted"
            return render_template("index.html", conversion_results=conversion_results, resources=resources, upload_success_message=upload_success_message)
        return redirect(url_for("index"))
    # For GET
    resources = get_fhir_resources()
    return render_template("index.html", resources=resources, upload_success_message=None)

# Helper to fetch FHIR resources from server

def get_fhir_resources():
    try:
        if not test_fhir_server_connection():
            return None
        patients_response = requests.get(f"{Config.FHIR_URL}/Patient", timeout=30)
        patients = []
        if patients_response.status_code == 200:
            patients_data = patients_response.json()
            if 'entry' in patients_data:
                patients = [entry['resource'] for entry in patients_data['entry']]
        observations_response = requests.get(f"{Config.FHIR_URL}/Observation", timeout=30)
        observations = []
        if observations_response.status_code == 200:
            observations_data = observations_response.json()
            if 'entry' in observations_data:
                observations = [entry['resource'] for entry in observations_data['entry']]
        reports_response = requests.get(f"{Config.FHIR_URL}/DiagnosticReport", timeout=30)
        reports = []
        if reports_response.status_code == 200:
            reports_data = reports_response.json()
            if 'entry' in reports_data:
                reports = [entry['resource'] for entry in reports_data['entry']]
        imaging_response = requests.get(f"{Config.FHIR_URL}/ImagingStudy", timeout=30)
        imaging_studies = []
        if imaging_response.status_code == 200:
            imaging_data = imaging_response.json()
            if 'entry' in imaging_data:
                imaging_studies = [entry['resource'] for entry in imaging_data['entry']]
        procedures_response = requests.get(f"{Config.FHIR_URL}/Procedure", timeout=30)
        procedures = []
        if procedures_response.status_code == 200:
            procedures_data = procedures_response.json()
            if 'entry' in procedures_data:
                procedures = [entry['resource'] for entry in procedures_data['entry']]
        medreq_response = requests.get(f"{Config.FHIR_URL}/MedicationRequest", timeout=30)
        medication_requests = []
        if medreq_response.status_code == 200:
            medreq_data = medreq_response.json()
            if 'entry' in medreq_data:
                medication_requests = [entry['resource'] for entry in medreq_data['entry']]
        medstmt_response = requests.get(f"{Config.FHIR_URL}/MedicationStatement", timeout=30)
        medication_statements = []
        if medstmt_response.status_code == 200:
            medstmt_data = medstmt_response.json()
            if 'entry' in medstmt_data:
                medication_statements = [entry['resource'] for entry in medstmt_data['entry']]
        resources = {
            'patients': patients,
            'observations': observations,
            'diagnostic_reports': reports,
            'imaging_studies': imaging_studies,
            'procedures': procedures,
            'medication_requests': medication_requests,
            'medication_statements': medication_statements,
        }
        return resources
    except Exception as e:
        logger.error(f"Error fetching FHIR resources: {str(e)}")
        return None

def fetch_fhir_resources(patient_id, max_per_type=6):
    resource_types = [
        "ImagingStudy", "DiagnosticReport", "Observation", "Procedure", "MedicationRequest", "MedicationStatement"
    ]
    resources = {}
    for rt in resource_types:
        try:
            r = requests.get(f"{Config.FHIR_URL}/{rt}", params={"subject": f"Patient/{patient_id}"}, timeout=10)
            entries = r.json().get("entry", []) if r.ok else []
            # Log count
            app.logger.info(f"Fetched {len(entries)} {rt} for {patient_id}")
            if rt == "DiagnosticReport":
                seen = set()
                deduped = []
                for entry in entries:
                    res = entry["resource"]
                    key = (res.get("id"), (res.get("conclusion") or "").strip())
                    if key in seen:
                        continue
                    seen.add(key)
                    deduped.append(entry)
                entries = deduped
            # Build simplified dicts
            res_list = []
            for entry in entries[:max_per_type]:
                res = entry["resource"]
                d = {
                    "id": res.get("id"),
                    "status": res.get("status"),
                    "code_text": res.get("code",{}).get("text") or (res.get("code",{}).get("coding",[{}])[0].get("display")),
                    "patient_ref": res.get("subject",{}).get("reference"),
                    "date": res.get("effectiveDateTime") or res.get("issued"),
                    "summary": (res.get("conclusion") or res.get("text",{}).get("div") or "")[:350],
                    "raw": res
                }
                # ImagingStudy: add series previews
                if rt == "ImagingStudy" and res.get("series"):
                    d["series_previews"] = []
                    for s in res["series"]:
                        series_uid = s.get("uid")
                        if series_uid:
                            d["series_previews"].append({
                                "series_uid": series_uid,
                                "preview_url": url_for('orthanc_preview', series_uid=series_uid)
                            })
                res_list.append(d)
            resources[rt] = res_list
        except Exception as e:
            app.logger.error(f"Error fetching {rt} for {patient_id}: {e}")
            resources[rt] = []
    return resources

@app.route('/fhir-view/<patient_id>')
def fhir_view(patient_id):
    resources = fetch_fhir_resources(patient_id)
    return render_template('fhir_view.html', patient_id=patient_id, resources=resources)

# ─── NEW ROUTE FOR CONVERSION STATUS ───────────────────────────────────────
@app.route("/conversion-status/<conversion_id>")
def get_conversion_status(conversion_id):
    """Get the status of a conversion process"""
    status = conversion_status.get(conversion_id, {"status": "not_found"})
    return jsonify(status)

@app.route("/sync-to-ai", methods=["POST"])
def sync_to_ai():
    import sys
    # Check HAPI and Orthanc
    try:
        hapi_ok = test_fhir_server_connection()
        orthanc_ok = False
        try:
            r = requests.get(f"{Config.ORTHANC_URL}/system", auth=Config.ORTHANC_AUTH, timeout=10)
            orthanc_ok = r.status_code == 200
        except Exception:
            orthanc_ok = False
        if not hapi_ok or not orthanc_ok:
            return jsonify({"ok": False, "error": "HAPI or Orthanc not reachable"}), 503
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    # Run integration/run_sync.py
    integration_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "integration"))
    run_sync_path = os.path.join(integration_dir, "run_sync.py")
    out_dir = os.path.join(integration_dir, "out")
    fhir_json = os.path.join(out_dir, "fhir_records.json")
    last_sync_json = os.path.join(out_dir, "last_sync.json")
    ai_data_path = Config.AI_DATA_PATH

    proc = subprocess.Popen(
        [sys.executable, run_sync_path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=integration_dir
    )
    out, err = proc.communicate()
    logs = out.decode() + "\n" + err.decode()

    # Copy fhir_records.json to AI app data
    try:
        shutil.copy2(fhir_json, os.path.join(ai_data_path, "fhir_records.json"))
    except Exception as e:
        return jsonify({"ok": False, "error": f"Copy failed: {e}"}), 500

    # Read last_sync.json for summary
    try:
        with open(last_sync_json, "r") as f:
            summary = json.load(f)
    except Exception as e:
        summary = {"ok": False, "error": f"Could not read last_sync.json: {e}"}

    summary["logs"] = logs
    return jsonify(summary)

@app.route("/sync-status", methods=["GET"])
def sync_status():
    integration_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "integration"))
    last_sync_json = os.path.join(integration_dir, "out", "last_sync.json")
    try:
        with open(last_sync_json, "r") as f:
            summary = json.load(f)
        return jsonify(summary)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Could not read last_sync.json: {e}"}), 404

# ─── NEW ROUTES FOR VIEWING CONVERTED FHIR RESOURCES ──────────────────────
@app.route("/fhir-resources")
def view_fhir_resources():
    """View all FHIR resources in the server"""
    try:
        if not test_fhir_server_connection():
            flash("FHIR server is not accessible", "error")
            return render_template("fhir_resources.html", resources=None)
        # Patients
        patients_response = requests.get(f"{Config.FHIR_URL}/Patient", timeout=30)
        patients = []
        if patients_response.status_code == 200:
            patients_data = patients_response.json()
            if 'entry' in patients_data:
                patients = [entry['resource'] for entry in patients_data['entry']]
        # Observations
        observations_response = requests.get(f"{Config.FHIR_URL}/Observation", timeout=30)
        observations = []
        if observations_response.status_code == 200:
            observations_data = observations_response.json()
            if 'entry' in observations_data:
                observations = [entry['resource'] for entry in observations_data['entry']]
        # DiagnosticReports
        reports_response = requests.get(f"{Config.FHIR_URL}/DiagnosticReport", timeout=30)
        reports = []
        if reports_response.status_code == 200:
            reports_data = reports_response.json()
            if 'entry' in reports_data:
                reports = [entry['resource'] for entry in reports_data['entry']]
        # ImagingStudies
        imaging_response = requests.get(f"{Config.FHIR_URL}/ImagingStudy", timeout=30)
        imaging_studies = []
        if imaging_response.status_code == 200:
            imaging_data = imaging_response.json()
            if 'entry' in imaging_data:
                imaging_studies = [entry['resource'] for entry in imaging_data['entry']]
        # Procedures
        procedures_response = requests.get(f"{Config.FHIR_URL}/Procedure", timeout=30)
        procedures = []
        if procedures_response.status_code == 200:
            procedures_data = procedures_response.json()
            if 'entry' in procedures_data:
                procedures = [entry['resource'] for entry in procedures_data['entry']]
        # MedicationRequest
        medreq_response = requests.get(f"{Config.FHIR_URL}/MedicationRequest", timeout=30)
        medication_requests = []
        if medreq_response.status_code == 200:
            medreq_data = medreq_response.json()
            if 'entry' in medreq_data:
                medication_requests = [entry['resource'] for entry in medreq_data['entry']]
        # MedicationStatement
        medstmt_response = requests.get(f"{Config.FHIR_URL}/MedicationStatement", timeout=30)
        medication_statements = []
        if medstmt_response.status_code == 200:
            medstmt_data = medstmt_response.json()
            if 'entry' in medstmt_data:
                medication_statements = [entry['resource'] for entry in medstmt_data['entry']]
        resources = {
            'patients': patients,
            'observations': observations,
            'diagnostic_reports': reports,
            'imaging_studies': imaging_studies,
            'procedures': procedures,
            'medication_requests': medication_requests,
            'medication_statements': medication_statements,
        }
        return render_template("fhir_resources.html", resources=resources)
    except Exception as e:
        logger.error(f"Error fetching FHIR resources: {str(e)}")
        flash(f"Error fetching FHIR resources: {str(e)}", "error")
        return render_template("fhir_resources.html", resources=None)

@app.route("/fhir-resource/<resource_type>/<resource_id>")
def view_single_fhir_resource(resource_type, resource_id):
    """View a single FHIR resource"""
    try:
        if not test_fhir_server_connection():
            flash("FHIR server is not accessible", "error")
            return redirect(url_for("view_fhir_resources"))
        
        response = requests.get(f"{Config.FHIR_URL}/{resource_type}/{resource_id}", timeout=30)
        
        if response.status_code == 200:
            resource = response.json()
            return render_template("single_fhir_resource.html", 
                                 resource=resource, 
                                 resource_type=resource_type,
                                 resource_id=resource_id)
        else:
            flash(f"Resource not found: {resource_type}/{resource_id}", "error")
            return redirect(url_for("view_fhir_resources"))
            
    except Exception as e:
        logger.error(f"Error fetching FHIR resource: {str(e)}")
        flash(f"Error fetching FHIR resource: {str(e)}", "error")
        return redirect(url_for("view_fhir_resources"))

@app.route("/conversion-history")
def conversion_history():
    """View conversion history"""
    return render_template("conversion_history.html", conversions=conversion_status)

@app.route("/ai-search", methods=["POST"])
def ai_search():
    data = request.get_json()
    query = data.get("query", "")
    if not query.strip():
        return jsonify({"ok": False, "error": "Empty query."}), 400
    api_key = os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        return jsonify({"ok": False, "error": "PERPLEXITY_API_KEY not set in environment"}), 500
    # Fetch live FHIR data from HAPI server
    try:
        fhir_url = app.config["FHIR_URL"]
        patients = requests.get(f"{fhir_url}/Patient?_count=3", timeout=20).json()
        reports = requests.get(f"{fhir_url}/DiagnosticReport?_count=3", timeout=20).json()
        observations = requests.get(f"{fhir_url}/Observation?_count=3", timeout=20).json()
        fhir_summary = []
        if 'entry' in patients:
            for p in patients['entry']:
                fhir_summary.append(f"Patient: {p['resource'].get('id', '')}, Name: {p['resource'].get('name', [{}])[0].get('family', '')}")
        if 'entry' in reports:
            for r in reports['entry']:
                fhir_summary.append(f"Report: {r['resource'].get('id', '')}, Conclusion: {r['resource'].get('conclusion', '')}")
        if 'entry' in observations:
            for o in observations['entry']:
                fhir_summary.append(f"Observation: {o['resource'].get('id', '')}, Value: {o['resource'].get('valueString', '')}")
        fhir_text = '\n'.join(fhir_summary)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Could not fetch FHIR data: {e}"}), 500
    # Fetch DICOM images from Orthanc and summarize
    try:
        orthanc_url = app.config["ORTHANC_URL"]
        studies = requests.get(f"{orthanc_url}/studies", auth=app.config["ORTHANC_AUTH"], timeout=20).json()
        dicom_summaries = []
        dicom_instance_ids = []
        for study_id in studies[:3]:
            series = requests.get(f"{orthanc_url}/studies/{study_id}/series", auth=app.config["ORTHANC_AUTH"], timeout=20).json()
            for series_id in series[:1]:
                instances = requests.get(f"{orthanc_url}/series/{series_id}/instances", auth=app.config["ORTHANC_AUTH"], timeout=20).json()
                for instance_id in instances[:1]:
                    dicom_instance_ids.append(instance_id)
                    meta = requests.get(f"{orthanc_url}/instances/{instance_id}/tags", auth=app.config["ORTHANC_AUTH"], timeout=20).json()
                    dicom_summaries.append(f"DICOM Instance: {instance_id}, PatientID: {meta.get('0010,0020', {}).get('Value', [''])[0]}")
    except Exception as e:
        dicom_summaries = [f"Could not fetch DICOM data: {e}"]
        dicom_instance_ids = []
    # Build prompt for Perplexity
    prompt = f"User question: {query}\n\nFHIR data from server:\n{fhir_text}\n\nDICOM image summaries from server: {', '.join(dicom_summaries)}\n\nBased on the above, answer the user's question as a medical AI assistant. For every image you refer to, include its instance ID in your answer (e.g., 'Referenced image')."
    # Call Perplexity API
    try:
        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "sonar-pro",
                "messages": [
                    {"role": "system", "content": "You are a helpful medical AI assistant."},
                    {"role": "user", "content": prompt}
                ]
            },
            timeout=60
        )
        if resp.status_code == 200:
            answer = resp.json()["choices"][0]["message"]["content"]
            ai_html = markdown.markdown(answer)
            import re
            series_uids = re.findall(r"Series:([0-9.]+)", answer)
            series_previews = []
            for uid in series_uids:
                # Defensive: try the helper, fall back to proxy string if helper missing or returns None
                try:
                    url = None
                    if 'get_preview_url_for_series' in globals():
                        url = get_preview_url_for_series(uid)
                except Exception as e:
                    logger.warning(f"get_preview_url_for_series raised for {uid}: {e}")
                    url = None
                # final fallback to constructed proxy path
                if not url:
                    url = f"/orthanc/preview/{uid}"
                series_previews.append({"uid": uid, "url": url})
            return jsonify({"ok": True, "answer": answer, "ai_html": ai_html, "series_previews": series_previews})
        else:
            return jsonify({"ok": False, "error": f"AI app error: {resp.text}"}), 502
    except Exception as e:
        return jsonify({"ok": False, "error": f"AI request failed: {e}"}), 500

@app.route('/orthanc/preview/<path:series_uid>')
def orthanc_preview(series_uid):
    # Only allow digits and dots for series_uid
    if not re.fullmatch(r'[0-9.]+', series_uid):
        app.logger.warning(f"Invalid series_uid: {series_uid}")
        return send_file(NO_IMAGE_PATH, mimetype='image/png')
    try:
        base = app.config['ORTHANC_URL']
        auth = app.config['ORTHANC_AUTH']
        r = requests.get(f"{base}/series", params={"DicomSeriesUID": series_uid}, auth=auth, timeout=10)
        if r.status_code == 200 and r.json():
            orthanc_series_id = r.json()[0]
            r2 = requests.get(f"{base}/series/{orthanc_series_id}/instances", auth=auth, timeout=10)
            if r2.status_code == 200 and r2.json():
                instances = r2.json()
                index = len(instances) // 2
                instance_id = instances[index]
                preview_resp = requests.get(f"{base}/instances/{instance_id}/preview", auth=auth, stream=True, timeout=10)
                if preview_resp.ok:
                    return Response(preview_resp.content, mimetype="image/png")
                else:
                    app.logger.warning(f"Preview not ok for {series_uid}, status {preview_resp.status_code}")
            else:
                app.logger.warning(f"No instances for {series_uid}, status {r2.status_code}")
        else:
            app.logger.warning(f"No series for {series_uid}, status {r.status_code}")
    except Exception as e:
        app.logger.error(f"Error in orthanc_preview for {series_uid}: {e}")
    if os.path.exists(NO_IMAGE_PATH):
        return send_file(NO_IMAGE_PATH, mimetype='image/png')
    return Response(b'\x89PNG\r\n\x1a\n' + b'\x00'*100, mimetype='image/png')

# ---------- helper: return proxy URL for series ----------
from flask import url_for  # ensure url_for is imported at top of file

def get_preview_url_for_series(series_uid: str):
    """
    Return the server-side proxy URL for a given DICOM SeriesInstanceUID.
    Safe: validates the UID and uses url_for to build the proxy path.
    """
    if not series_uid:
        return None
    # Basic validation (digits and dots)
    if not re.fullmatch(r"[0-9.]+", series_uid):
        logger.warning(f"get_preview_url_for_series rejected invalid UID: {series_uid}")
        return None
    try:
        # url_for requires a request/application context (we are inside a Flask request here)
        return url_for("orthanc_preview", series_uid=series_uid)
    except Exception as e:
        logger.warning(f"get_preview_url_for_series url_for failed, falling back to string for {series_uid}: {e}")
        return f"/orthanc/preview/{series_uid}"

def fetch_fhir_resources(patient_id, max_per_type=6):
    resource_types = ["ImagingStudy", "DiagnosticReport", "Observation", "Procedure", "MedicationRequest", "MedicationStatement"]
    resources = {}
    for rt in resource_types:
        try:
            r = requests.get(f"{Config.FHIR_URL}/{rt}", params={"subject": f"Patient/{patient_id}"}, timeout=10)
            entries = r.json().get("entry", []) if r.ok else []
            app.logger.info(f"Fetched {len(entries)} {rt} for {patient_id}")
            if rt == "DiagnosticReport":
                seen = set()
                deduped = []
                for entry in entries:
                    res = entry["resource"]
                    key = (res.get("id"), (res.get("conclusion") or "").strip())
                    if key in seen:
                        continue
                    seen.add(key)
                    deduped.append(entry)
                entries = deduped
            res_list = []
            for entry in entries[:max_per_type]:
                res = entry["resource"]
                d = {
                    "id": res.get("id"),
                    "status": res.get("status"),
                    "code_text": res.get("code",{}).get("text") or (res.get("code",{}).get("coding",[{}])[0].get("display")),
                    "patient_ref": res.get("subject",{}).get("reference"),
                    "date": res.get("effectiveDateTime") or res.get("issued"),
                    "summary": (res.get("conclusion") or res.get("text",{}).get("div") or "")[:350],
                    "raw": res
                }
                # ImagingStudy: add series previews
                if rt == "ImagingStudy" and res.get("series"):
                    d["series_previews"] = []
                    for s in res["series"]:
                        series_uid = s.get("uid")
                        if series_uid:
                            d["series_previews"].append({
                                "series_uid": series_uid,
                                "preview_url": url_for('orthanc_preview', series_uid=series_uid)
                            })
                resources.setdefault(rt, []).append(d)
        except Exception as e:
            app.logger.error(f"Error fetching {rt} for {patient_id}: {e}")
            resources[rt] = []
    return resources

# ─── RUN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True)