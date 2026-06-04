# GE Healthcare MCP Project

## Team Members
- Seralathan C A
- Rupesh
- Tarun

## Overview
This project sets up a basic Medical Control Platform (MCP) with:
- HL7 v2 to FHIR R4 transformation
- DICOM handling via Orthanc
- Docker-based server setup
- FHIR-ready data for downstream AI agents

## Folder Structure
- `hl7/`: HL7 samples and parsers
- `dicom/`: DICOM upload and metadata handling
- `scripts/`: Linking DICOM metadata to FHIR ImagingStudy
- `docker/`: Docker Compose setup for Orthanc & HAPI FHIR

## How to Run
1. Start Docker: `docker compose up -d`
2. Upload HL7 message: `python hl7/parse_hl7.py`
3. Upload DICOM image: `python dicom/upload_dicom.py`
