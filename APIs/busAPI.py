##primary key: 163d0e36181c44d4ac04d07addb8a4a4
##secondary key: b09d309bfb6640a28684819cff6758ed

import requests

API_KEY = "163d0e36181c44d4ac04d07addb8a4a4"  # better: os.environ["NTA_API_KEY"]

def realtimeBusQuery():
    api_url = "https://api.nationaltransport.ie/gtfsr/v2/gtfsr"
    headers = {"x-api-key": API_KEY}
    params = {"format": "json"}  # "json" is easiest to read; omit for raw protobuf

    try:
        response = requests.get(api_url, headers=headers, params=params)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return None