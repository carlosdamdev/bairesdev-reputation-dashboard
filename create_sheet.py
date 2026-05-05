import os
import pickle
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

FOLDER_ID = "1olX4FhBP-OfSXRFaU8NhnJZDhtN4xQYp"  # IA Upgrade


def get_credentials():
    creds = None
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.pickle", "wb") as f:
            pickle.dump(creds, f)
    return creds


def create_sheet_and_write(title: str, cell: str, value: str, folder_id: str = FOLDER_ID):
    creds = get_credentials()
    drive = build("drive", "v3", credentials=creds)
    sheets = build("sheets", "v4", credentials=creds)

    # Create the Google Sheet inside the folder
    file_metadata = {
        "name": title,
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "parents": [folder_id],
    }
    file = drive.files().create(body=file_metadata, fields="id,name,webViewLink").execute()
    sheet_id = file["id"]
    print(f"Created: {file['name']} -> {file['webViewLink']}")

    # Write value to the specified cell
    sheets.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"Sheet1!{cell}",
        valueInputOption="RAW",
        body={"values": [[value]]},
    ).execute()
    print(f"Written '{value}' to cell {cell}")

    return sheet_id


if __name__ == "__main__":
    create_sheet_and_write(
        title="test conexion",
        cell="A1",
        value="HI its working",
    )
