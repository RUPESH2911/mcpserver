import pydicom
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import generate_uid
import os
from datetime import datetime

def create_sample_dicom(patient_id, filename):
    """Create a minimal valid DICOM file for testing"""
    
    # Create file meta information
    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = '1.2.840.10008.5.1.4.1.1.2'  # CT Image Storage
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.ImplementationClassUID = '1.2.3.4'
    file_meta.TransferSyntaxUID = '1.2.840.10008.1.2.1'  # Explicit VR Little Endian
    
    # Create the main dataset
    ds = FileDataset(filename, {}, file_meta=file_meta, preamble=b"\0" * 128)
    
    # Add required DICOM elements
    ds.PatientID = patient_id
    ds.PatientName = f"Test^Patient^{patient_id}"
    ds.PatientBirthDate = "19900101"
    ds.PatientSex = "M"
    
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    
    ds.Modality = "CT"
    ds.StudyDate = datetime.now().strftime("%Y%m%d")
    ds.StudyTime = datetime.now().strftime("%H%M%S")
    ds.SeriesNumber = "1"
    ds.InstanceNumber = "1"
    
    # Add minimal image data
    ds.Rows = 512
    ds.Columns = 512
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    
    # Create minimal pixel data (just zeros)
    import numpy as np
    pixel_data = np.zeros((512, 512), dtype=np.uint16)
    ds.PixelData = pixel_data.tobytes()
    
    # Save the file
    ds.save_as(filename, write_like_original=False)
    print(f"✅ Created DICOM file: {filename} (Patient: {patient_id})")

# Create sample DICOM files
create_sample_dicom("P1001", "uploads/P1001_valid.dcm")
create_sample_dicom("P1002", "uploads/P1002_valid.dcm")
create_sample_dicom("98.12.21", "uploads/98.12.21_sample.dcm")

print("\n📁 Sample DICOM files created successfully!")
print("You can now test uploading these files through the web interface.")
