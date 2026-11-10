
import requests
import pandas as pd
import os
import time
from io import StringIO
from datetime import datetime, timezone

# ==================================================
# CONFIGURATION
# ==================================================

API_URL = (
    "https://erddap.marine.ie/erddap/tabledap/"
    "IrishNationalTideGaugeNetwork.csv0"
)

CSV_FILE = "tide_gauge_data.csv"

CACHE_DURATION = 15 * 60  # 15 minutes
PREVIEW_ROWS = 5

HEADERS = {
    "User-Agent": "FloodDetector/1.0"
}

FIELDS = [
    "time",
    "altitude",
    "latitude",
    "longitude",
    "station_id",
    "datasourceid",
    "Water_Level_LAT",
    "Water_Level_OD_Malin",
    "QC_Flag"
]


# ==================================================
# CHECK LOCAL CACHE
# ==================================================

def cache_is_valid():

    if not os.path.exists(CSV_FILE):
        return False

    age = time.time() - os.path.getmtime(CSV_FILE)

    if age < CACHE_DURATION:
        print(f"Using cached data ({age / 60:.1f} minutes old).")
        return True

    print("Cache expired. Retrieving updated data.")
    return False


# ==================================================
# LOAD SAVED DATA
# ==================================================

def load_local_data():

    try:
        df = pd.read_csv(CSV_FILE)

        print("Saved data loaded successfully.")
        return df

    except (OSError, pd.errors.ParserError, ValueError) as error:
        print(f"Error loading saved data: {error}")
        return None


# ==================================================
# FETCH API DATA
# ==================================================

def fetch_api_data():

    print("\nConnecting to Marine Institute ERDDAP API...")

    query = ",".join(FIELDS) + "&time>=now-6hours"

    try:

        response = requests.get(
            API_URL,
            params=query,
            headers=HEADERS,
            timeout=60
        )

        response.raise_for_status()

        if not response.text.strip():
            print("API returned an empty response.")
            return None

        print("Successfully retrieved tide gauge data.")

        return response.text

    except requests.exceptions.RequestException as error:

        print(f"API request failed: {error}")
        return None


# ==================================================
# CLEAN API DATA
# ==================================================

def clean_api_data(raw_data):

    try:

        # Skip the second row containing units
        df = pd.read_csv(
            StringIO(raw_data),
            header=None,
            names=FIELDS,
            skiprows=0
        )

        # Clean column headers
        df.columns = df.columns.str.strip()

        # Verify expected columns
        missing_columns = [
            col for col in FIELDS
            if col not in df.columns
        ]

        if missing_columns:

            print("Missing expected columns:", missing_columns)
            print("Received columns:", df.columns.tolist())

            return None

        if df.empty:
            print("No observations returned.")
            return None

        # Convert timestamp to UTC datetime
        df["time"] = pd.to_datetime(
            df["time"],
            utc=True,
            errors="coerce"
        )

        # Convert numerical fields
        numeric_columns = [
            "altitude",
            "latitude",
            "longitude",
            "datasourceid",
            "Water_Level_LAT",
            "Water_Level_OD_Malin",
            "QC_Flag"
        ]

        for col in numeric_columns:

            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

        # Replace missing measurement indicators
        missing_values = [-9999, -99999, 99999]

        for col in [
            "Water_Level_LAT",
            "Water_Level_OD_Malin"
        ]:

            df[col] = df[col].replace(
                missing_values,
                float("nan")
            )

        # Remove invalid timestamps
        df = df.dropna(subset=["time"])

        # Remove invalid coordinates
        df = df.dropna(
            subset=["latitude", "longitude"]
        )

        df = df[
            df["latitude"].between(-90, 90)
            & df["longitude"].between(-180, 180)
        ]

        # Remove duplicate observations
        df = df.drop_duplicates(
            subset=["station_id", "time", "datasourceid"]
        )

        # Add retrieval timestamp
        df["retrieved_at_utc"] = datetime.now(
            timezone.utc
        ).isoformat()

        # Interpret quality flags
        quality_mapping = {
            0: "Unknown",
            1: "Good",
            9: "Missing value"
        }

        df["quality_description"] = (
            df["QC_Flag"]
            .map(quality_mapping)
            .fillna("Unrecognised flag")
        )

        print(f"Successfully cleaned {len(df)} observations.")

        return df

    except Exception as error:

        print(f"Data processing error: {error}")
        print("\nResponse preview:")
        print(raw_data[:1000])

        return None


# ==================================================
# SAVE DATA
# ==================================================

def save_data(df):

    if df is None or df.empty:
        return False

    temporary_file = CSV_FILE + ".tmp"

    try:

        df.to_csv(
            temporary_file,
            index=False,
            encoding="utf-8"
        )

        os.replace(temporary_file, CSV_FILE)

        print(f"Saved {len(df)} observations to {CSV_FILE}")

        return True

    except OSError as error:

        print(f"Error saving data: {error}")

        if os.path.exists(temporary_file):
            os.remove(temporary_file)

        return False


# ==================================================
# DISPLAY PREVIEW
# ==================================================

def display_preview(df):

    if df is None or df.empty:
        print("No data available.")
        return

    print("\n==========================================")
    print("       MARINE INSTITUTE TIDE DATA")
    print("==========================================")

    print(f"Total observations: {len(df)}")
    print("Unique stations:", df["station_id"].nunique())

    display_columns = [
        "time",
        "station_id",
        "latitude",
        "longitude",
        "Water_Level_LAT",
        "Water_Level_OD_Malin",
        "QC_Flag"
    ]

    print(f"\nFirst {PREVIEW_ROWS} records:\n")

    print(
        df[display_columns]
        .head(PREVIEW_ROWS)
        .to_string(index=False)
    )

    print("\n==========================================")


# ==================================================
# MAIN PROGRAM
# ==================================================

def main():

    print("\nStarting Marine Institute Tide Data Collector")

    # Check local cache
    if cache_is_valid():

        df = load_local_data()

        if df is not None and not df.empty:
            display_preview(df)
            return

    # Fetch new API data
    raw_data = fetch_api_data()

    if raw_data is None:

        print("API unavailable.")

        if os.path.exists(CSV_FILE):

            print("Loading previously saved data.")

            df = load_local_data()

            if df is not None:
                display_preview(df)
                return

        print("No data available.")
        return

    # Clean API response
    df = clean_api_data(raw_data)

    if df is None or df.empty:

        print("Invalid data. Existing CSV preserved.")

        if os.path.exists(CSV_FILE):

            old_df = load_local_data()

            if old_df is not None:
                display_preview(old_df)

        return

    # Save and display
    if save_data(df):
        display_preview(df)


# ==================================================
# RUN PROGRAM
# ==================================================

if __name__ == "__main__":
    main()