##primary key: 163d0e36181c44d4ac04d07addb8a4a4
##secondary key: b09d309bfb6640a28684819cff6758ed

import requests

API_KEY = "163d0e36181c44d4ac04d07addb8a4a4"  # better: os.environ["NTA_API_KEY"]

def realtimeBusQuery():
    ## returns realtime routes and stops
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

def BusVehicleQuery():
    ## returns vehicle positions and associated route information
    api_url = "https://api.nationaltransport.ie/gtfsr/v2/Vehicles"
    headers = {"x-api-key": API_KEY}
    params = {"format": "json"}  # "json" is easiest to read; omit for raw protobuf

    try:
        response = requests.get(api_url, headers=headers, params=params)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return None

def BusAlertsQuery():
    ## returns route diversions and affected routes
    api_url = "https://api.nationaltransport.ie/gtfsr/v2/alerts"
    headers = {"x-api-key": API_KEY}
    params = {"format": "json"}  # "json" is easiest to read; omit for raw protobuf

    try:
        response = requests.get(api_url, headers=headers, params=params)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return None

def BusTripUpdatesQuery():
    ## returns realtime trip updates (delays, cancellations) as JSON text
    api_url = "https://api.nationaltransport.ie/gtfsr/v2/TripUpdates"
    headers = {"x-api-key": API_KEY}
    params = {"format": "json"}

    try:
        response = requests.get(api_url, headers=headers, params=params)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return None

def DublinBusTimetableDownload(path):
    ## downloads the static Dublin Bus GTFS timetable (stops, routes, trips) zip to path
    api_url = "https://www.transportforireland.ie/transitData/Data/GTFS_Dublin_Bus.zip"

    try:
        with requests.get(api_url, stream=True, timeout=180) as response:
            response.raise_for_status()
            with open(path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        return path
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return None
