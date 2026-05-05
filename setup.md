# Setup

## 1. Install dependencies
```
pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
```

## 2. Get Google credentials
1. Go to https://console.cloud.google.com/
2. Create a project (or select existing)
3. Enable **Google Drive API** and **Google Sheets API**
4. Go to **APIs & Services > Credentials**
5. Create **OAuth 2.0 Client ID** (Desktop app)
6. Download the JSON and rename it to `credentials.json` in this folder

## 3. Run
```
"C:\Users\damia\AppData\Local\Programs\Python\Python313\python.exe" create_sheet.py
```
A browser window will open once to authorize — after that it's fully automatic.

## Customize
Edit the bottom of `create_sheet.py` to change the title, cell, or value:
```python
create_sheet_and_write(
    title="my sheet name",
    cell="A1",
    value="whatever you want",
)
```
