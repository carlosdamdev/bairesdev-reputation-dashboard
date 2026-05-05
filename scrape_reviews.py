import time
import pickle
import os
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

FOLDER_ID = "1olX4FhBP-OfSXRFaU8NhnJZDhtN4xQYp"  # IA Upgrade
BASE_URL = "https://clutch.co/profile/bairesdev"


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


def clean(el):
    if not el:
        return ""
    return " ".join(el.get_text(strip=True).split())


def get_section_text(review, title):
    for h4 in review.select("h4.profile-review__extra-title"):
        if title.lower() in h4.get_text(strip=True).lower():
            section = h4.find_parent("div", class_="profile-review__extra-section")
            if section:
                h4.extract()
                return " ".join(section.get_text(separator=" ", strip=True).split())
    return ""


def get_metric(review, metric_name):
    for item in review.select("li.profile-review__extra-detailed-metrics-item"):
        title_el = item.select_one("p.profile-review__extra-detailed-metrics-title")
        score_el = item.select_one("span.profile-review__extra-detailed-metrics-score")
        if title_el and score_el and metric_name.lower() in title_el.get_text(strip=True).lower():
            return clean(score_el)
    return ""


def parse_review(article):
    data = {}

    # Title / heading
    header = article.select_one("div.profile-review__header")
    title_text = clean(header).replace("Featured Review", "").replace("Share", "").strip() if header else ""
    data["Title"] = title_text

    # Service categories
    services = article.select("span.profile-review__data-item")
    data["Services"] = ", ".join(clean(s) for s in services)

    # Data items: cost and duration are li.data--item (not service list)
    data_items = article.select("ul.data--list > li.data--item")
    data["Project Cost"] = clean(data_items[1]) if len(data_items) > 1 else ""
    data["Duration"] = clean(data_items[2]) if len(data_items) > 2 else ""

    # Overall rating
    overall = article.select_one("div.profile-review__rating span.sg-rating__number")
    data["Overall Rating"] = clean(overall)

    # Sub-ratings from detailed metrics
    data["Quality"] = get_metric(article, "Quality")
    data["Schedule"] = get_metric(article, "Schedule")
    data["Cost Rating"] = get_metric(article, "Cost")
    data["Willing to Refer"] = get_metric(article, "Willing to Refer")

    # Quote
    quote = article.select_one("div.profile-review__quote")
    data["Quote"] = clean(quote)

    # Date
    date = article.select_one("div.profile-review__date")
    data["Date"] = clean(date)

    # Reviewer name
    name = article.select_one("div.reviewer_card--name")
    data["Reviewer Name"] = clean(name)

    # Reviewer title + company (e.g. "Co-Founder & CTO, Freeplay")
    position = article.select_one("div.reviewer_position")
    data["Title & Company"] = clean(position)

    # Reviewer list items: industry, location, size, source
    reviewer_items = article.select("ul.reviewer_list > li.reviewer_list--item span.reviewer_list__details-title")
    labels = [clean(i) for i in reviewer_items]
    data["Industry"] = labels[0] if len(labels) > 0 else ""
    data["Location"] = labels[1] if len(labels) > 1 else ""
    data["Company Size"] = labels[2] if len(labels) > 2 else ""
    data["Review Source"] = labels[3] if len(labels) > 3 else ""

    # Verified
    verified = article.select_one("span.profile-review__reviewer-verification-badge-title")
    data["Verified"] = clean(verified) if verified else ""

    # Summary & feedback (short text blocks)
    summary = article.select_one("div.profile-review__summary")
    data["Summary"] = clean(summary)

    feedback = article.select_one("div.profile-review__feedback")
    data["Feedback"] = clean(feedback)

    # Full detailed sections
    data["Background"] = get_section_text(article, "BACKGROUND")
    data["Opportunity / Challenge"] = get_section_text(article, "OPPORTUNITY")
    data["Solution"] = get_section_text(article, "SOLUTION")
    data["Results & Feedback"] = get_section_text(article, "RESULTS")

    return data


def scrape_all_reviews():
    all_reviews = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        pw_page = ctx.new_page()
        page_num = 0
        while True:
            url = BASE_URL if page_num == 0 else f"{BASE_URL}?page={page_num}"
            print(f"Fetching page {page_num + 1}: {url}")

            # Fresh context per page avoids Cloudflare session-based blocks
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
            )
            pw_page = ctx.new_page()
            pw_page.goto(url, wait_until="load", timeout=60000)
            pw_page.wait_for_selector("article.profile-review", timeout=15000)
            pw_page.wait_for_timeout(1000)

            html = pw_page.content()
            ctx.close()

            soup = BeautifulSoup(html, "lxml")
            reviews = soup.select("article.profile-review")

            if not reviews:
                print("  No reviews found, stopping.")
                break

            print(f"  Parsed {len(reviews)} reviews")
            for r in reviews:
                all_reviews.append(parse_review(r))

            next_btn = soup.select_one("a.sg-pagination-v2-next")
            if not next_btn or "sg-pagination-v2-disabled" in next_btn.get("class", []):
                print("Last page reached.")
                break

            page_num += 1
            time.sleep(3)

        browser.close()

    return all_reviews


def write_to_sheet(reviews):
    if not reviews:
        print("No reviews to write.")
        return

    creds = get_credentials()
    drive = build("drive", "v3", credentials=creds)
    sheets = build("sheets", "v4", credentials=creds)

    file_metadata = {
        "name": "BairesDev Clutch Reviews",
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "parents": [FOLDER_ID],
    }
    file = drive.files().create(body=file_metadata, fields="id,name,webViewLink").execute()
    sheet_id = file["id"]
    print(f"\nCreated: {file['name']}\nURL: {file['webViewLink']}")

    headers = list(reviews[0].keys())
    rows = [headers] + [[r.get(h, "") for h in headers] for r in reviews]

    sheets.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range="Sheet1!A1",
        valueInputOption="RAW",
        body={"values": rows},
    ).execute()

    # Bold + freeze header row
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={
            "requests": [
                {
                    "repeatCell": {
                        "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat.textFormat.bold",
                    }
                },
                {
                    "updateSheetProperties": {
                        "properties": {"sheetId": 0, "gridProperties": {"frozenRowCount": 1}},
                        "fields": "gridProperties.frozenRowCount",
                    }
                },
            ]
        },
    ).execute()

    print(f"Done! {len(reviews)} reviews written.")


if __name__ == "__main__":
    reviews = scrape_all_reviews()
    write_to_sheet(reviews)
