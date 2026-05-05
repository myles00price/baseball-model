import gspread
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle
import os

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def get_google_client():
    creds = None
    token_path = 'token.pickle'
    
    if os.path.exists(token_path):
        with open(token_path, 'rb') as token:
            creds = pickle.load(token)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, 'wb') as token:
            pickle.dump(creds, token)
    
    return gspread.authorize(creds)

def export_to_sheets(picks, date_str):
    print("\nConnecting to Google Sheets...")
    client = get_google_client()
    
    # Create or open spreadsheet
    try:
        sheet = client.open("MLB Model Picks")
        print("Found existing spreadsheet!")
    except:
        sheet = client.create("MLB Model Picks")
        print("Created new spreadsheet!")
    
    # Add new worksheet for this date
    try:
        ws = sheet.add_worksheet(title=date_str, rows=30, cols=20)
    except:
        ws = sheet.worksheet(date_str)
        ws.clear()
    
    # Headers
    headers = [
        "Date", "Away", "Home",
        "Model Away%", "Model Home%",
        "DK Away Odds", "DK Home Odds",
        "MGM Away Odds", "MGM Home Odds",
        "DK Edge Away", "MGM Edge Away",
        "DK Edge Home", "MGM Edge Home",
        "Away SP", "Home SP", "Flag"
    ]
    
    # Write headers and data
    ws.append_row(headers)
    for pick in picks:
        ws.append_row([str(p) for p in pick])
    
    # Share it
    sheet.share(None, perm_type='anyone', role='reader')
    url = f"https://docs.google.com/spreadsheets/d/{sheet.id}"
    print(f"\n✅ Exported to Google Sheets!")
    print(f"🔗 URL: {url}")
    print(f"\nShare this link with your dad and family friend!")
    return url