
import requests
import pandas as pd
import json
import os
import time
from datetime import datetime, timezone

# ==================================================
# CONFIGURATION
# ==================================================

API_URL = "https://waterlevel.ie/geojson/latest/"

CSV_FILE = "water_level_data.csv"

# Minimum time between API requests
CACHE_DURATION = 15 * 60  # 15 minutes

# Number of records to display
PREVIEW_ROWS = 5

HEADERS = {
    "User-Agent": "FloodDetector/1.0"
}


# ==================================================
# CHECK LOCAL CACHE
# ==================================================

def cache_is_valid():

    if not os.path.exists(CSV_FILE):
        return False

    file_age = time.time() - os.path.getmtime(CSV_FILE)

    if file_age < CACHE_DURATION:
        print("Using existing local CSV file.")
        print(f"Cache age: {file_age / 60:.1f} minutes")
        return True

    print("Local CSV is older than 15 minutes.")
    return False


# ==================================================
# LOAD DATA FROM CSV
# ==================================================

def load_local_data():

    try:
        df = pd.read_csv(
            CSV_FILE,
            dtype={"station_reference": "string"}
        )

        print("Successfully loaded saved data.")

        return df

    except (OSError, pd.errors.ParserError, ValueError) as error:

        print(f"Could not read local CSV: {error}")

        return None


# ==================================================
# FETCH DATA FROM WATERLEVEL.IE
# ==================================================

def fetch_api_data():

    print("\nConnecting to WaterLevel.ie API...")

    try:

        response = requests.get(
            API_URL,
            headers=HEADERS,
            timeout=30
        )

        response.raise_for_status()

        data = response.json()

        print("Successfully retrieved API data.")

        return data

    except requests.exceptions.RequestException as error:

        print(f"API request failed: {error}")

        return None

    except ValueError:

        print("API returned invalid JSON.")

        return None


# ==================================================
# EXTRACT GEOJSON FEATURES
# ==================================================

def extract_features(data):

    if isinstance(data, dict):

        if data.get("type") == "Feature":
            return [data]

        return data.get("features", [])

    if isinstance(data, list):
        return data

    return []


# ==================================================
# CLEAN AND PROCESS DATA
# ==================================================

def clean_api_data(data):

    features = extract_features(data)

    if not features:
        print("No station records found in API response.")
        return None

    records = []

    retrieval_time = datetime.now(
        timezone.utc
    ).isoformat()

    for feature in features:

        properties = feature.get("properties", {}) or {}

        geometry = feature.get("geometry", {}) or {}

        # Preserve all station properties
        record = {}

        for key, value in properties.items():

            column_name = str(key).strip().lower()

            # Make column names consistent
            column_name = column_name.replace(" ", "_")
            column_name = column_name.replace("-", "_")

            if isinstance(value, (dict, list)):
                value = json.dumps(value)

            record[column_name] = value

        # Extract coordinates
        coordinates = geometry.get("coordinates", [])

        if (
            isinstance(coordinates, (list, tuple))
            and len(coordinates) >= 2
        ):

            record["longitude"] = coordinates[0]
            record["latitude"] = coordinates[1]

        else:

            record["longitude"] = None
            record["latitude"] = None

        record["retrieved_at_utc"] = retrieval_time

        records.append(record)

    df = pd.DataFrame(records)

    # Remove exact duplicate records
    df = df.drop_duplicates()

    # Standardise common column names where available
    aliases = {
        "station_name": [
            "station_name", "name", "station"
        ],
        "station_reference": [
            "station_ref", "station_reference",
            "ref", "station_number"
        ],
        "water_level": [
            "water_level", "waterlevel",
            "level", "value"
        ]
    }

    for standard_name, possible_names in aliases.items():

        if standard_name not in df.columns:

            for column in possible_names:

                if column in df.columns:

                    df[standard_name] = df[column]
                    break

    # Convert numeric fields
    for column in [
        "latitude",
        "longitude",
        "water_level"
    ]:

        if column in df.columns:

            df[column] = pd.to_numeric(
                df[column],
                errors="coerce"
            )

    # Remove records without valid coordinates
    df = df.dropna(
        subset=["latitude", "longitude"]
    )

    return df


# ==================================================
# SAVE ALL DATA TO CSV
# ==================================================

def save_data(df):

    if df is None or df.empty:

        print("No valid data to save.")
        return False

    temporary_file = CSV_FILE + ".tmp"

    try:

        df.to_csv(
            temporary_file,
            index=False,
            encoding="utf-8"
        )

        # Replace old snapshot only after successful write
        os.replace(temporary_file, CSV_FILE)

        print(f"\nAll {len(df)} records saved to {CSV_FILE}")

        return True

    except OSError as error:

        print(f"Error saving CSV: {error}")

        if os.path.exists(temporary_file):
            os.remove(temporary_file)

        return False


# ==================================================
# DISPLAY A SMALL DATA PREVIEW
# ==================================================

def display_preview(df):

    if df is None or df.empty:

        print("No data available to display.")
        return

    print("\n==========================================")
    print("       WATERLEVEL.IE DATA PREVIEW")
    print("==========================================")

    print(f"Total records stored: {len(df)}")

    print(f"\nDisplaying first {PREVIEW_ROWS} records:\n")

    # Display useful columns where available
    preferred_columns = [
        "station_name",
        "station_reference",
        "water_level",
        "latitude",
        "longitude"
    ]

    available_columns = [
        column for column in preferred_columns
        if column in df.columns
    ]

    if available_columns:

        print(
            df[available_columns]
            .head(PREVIEW_ROWS)
            .to_string(index=False)
        )

    else:

        print(df.head(PREVIEW_ROWS).to_string(index=False))

    print("\n==========================================")


# ==================================================
# MAIN PROGRAM
# ==================================================

def main():

    print("\nStarting Flood Detector Water Level Data Collector")

    # 1. Check whether cached data can be used
    if cache_is_valid():

        df = load_local_data()

        if df is not None and not df.empty:

            display_preview(df)
            return

        print("Cache could not be used. Attempting API request.")

    # 2. Retrieve new API data
    raw_data = fetch_api_data()

    # 3. Handle API failure
    if raw_data is None:

        # Use an older local copy if available
        if os.path.exists(CSV_FILE):

            print("Using existing saved data as fallback.")

            df = load_local_data()

            if df is not None:
                display_preview(df)
                return

        print("No data available.")
        return

    # 4. Clean the data
    df = clean_api_data(raw_data)

    if df is None or df.empty:

        print("Data processing failed.")
        return

    # 5. Save all records
    saved = save_data(df)

    # 6. Display only a few records
    if saved:
        display_preview(df)


# ==================================================
# RUN PROGRAM
# ==================================================

if __name__ == "__main__":
    main()