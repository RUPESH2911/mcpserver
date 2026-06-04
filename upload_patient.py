import requests

patient = {
  "resourceType": "Patient",
  "id": "example",
  "name": [{
    "use": "official",
    "family": "Doe",
    "given": ["John"]
  }],
  "gender": "male",
  "birthDate": "1970-01-01"
}

res = requests.post(
  "http://localhost:8080/fhir/Patient",
  headers={"Content-Type": "application/fhir+json"},
  json=patient
)

print("Status:", res.status_code)
print("Response:", res.json())
