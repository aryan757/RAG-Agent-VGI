import requests

url = "https://api.elevenlabs.io/v1/convai/knowledge-base"
headers = {"xi-api-key": "sk_6dd232cd750990a82f85392f4bd653a8b408b5221d6b1d13"}
data = {"name": "test_upload_file"}

with open("test.txt", "w") as f:
    f.write("test content")

with open("test.txt", "rb") as f:
    files = {"file": ("test.txt", f, "text/plain")}
    response = requests.post(url, headers=headers, data=data, files=files)
    print(response.status_code)
    print(response.text)
