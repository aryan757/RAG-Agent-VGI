import requests
import mimetypes

url = "https://api.elevenlabs.io/v1/convai/knowledge-base"
api_key = "sk_6dd232cd750990a82f85392f4bd653a8b408b5221d6b1d13"
headers = {"xi-api-key": api_key}

original_filename = "PN803 Equipment Document.pdf"
local_path = "test.txt"

with open(local_path, "w") as f:
    f.write("test content")

mime_type, _ = mimetypes.guess_type(original_filename)
if mime_type is None:
    mime_type = "application/octet-stream"

with open(local_path, "rb") as f:
    files = {"file": (original_filename, f, mime_type)}
    data = {"name": original_filename}
    response = requests.post(url, headers=headers, data=data, files=files)
    print("Status:", response.status_code)
    print("Response:", response.text)
