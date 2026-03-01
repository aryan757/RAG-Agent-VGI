import requests

url = "https://api.elevenlabs.io/v1/convai/knowledge-base?page_size=50"

headers = {
  'xi-api-key': 'sk_6dd232cd750990a82f85392f4bd653a8b408b5221d6b1d13'
}

response = requests.get(url, headers=headers)

print(response.text)
