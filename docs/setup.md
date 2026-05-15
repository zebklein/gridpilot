# Setup Guide

## Prerequisites

- Python 3.8+
- A Google account
- `pip install -r requirements.txt`

---

## Step 1: Install dependencies

```bash
pip install -r requirements.txt
```

---

## Step 2: Create a Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click the project dropdown at the top → **New Project**
3. Name it anything (e.g. "gridpilot") → **Create**

---

## Step 3: Enable the APIs

1. In your new project, go to **APIs & Services → Library**
2. Search for **Google Sheets API** → click it → **Enable**
3. Search for **Google Drive API** → click it → **Enable**

---

## Step 4: Configure OAuth

1. Go to **APIs & Services → OAuth consent screen**
   - If redirected, look for **Google Auth Platform** in the left nav
2. Select **External** → **Create**
3. Fill in App name (anything), User support email (your email), Developer contact (your email)
4. Click through to **Save and Continue** on each step (Scopes and Test users can be skipped for now)
5. Go to **Audience** (or **Test users** tab) → **Add Users** → enter your Google account email → **Save**

---

## Step 5: Create OAuth credentials

1. Go to **APIs & Services → Credentials**
2. Click **+ Create Credentials → OAuth 2.0 Client ID**
3. Application type: **Desktop App**
4. Name: anything (e.g. "gridpilot desktop")
5. Click **Create**
6. Click **Download JSON** on the popup (or click the download icon next to your new credential)
7. Rename the downloaded file to `credentials.json`
8. Place it in the `credentials/` folder in your gridpilot directory

---

## Step 6: First run (browser authorization)

The first time any script runs, a browser window will open asking you to authorize the app.

1. Sign in with the Google account you added as a test user
2. Click **Continue** through any "unverified app" warnings (this is expected for apps in testing mode)
3. Grant access to Google Sheets and Google Drive
4. The browser will show "Authentication successful" — you can close it

The authorization token is saved to `credentials/token.json`. Future runs skip the browser step until the token expires (roughly every few weeks).

**Browser doesn't open automatically?** The script will print a URL — copy and paste it into your browser manually.

---

## Step 7: Create your first project

```bash
python scripts/init_sheet.py --project myproject --template new-construction
```

This will:
1. Open a browser for authorization (first time only)
2. Create a Google Sheet in your Google Drive
3. Build all tabs and write initial data
4. Print the sheet URL

---

## Troubleshooting

**`credentials.json not found`**
Place the file in the `credentials/` directory at the root of the gridpilot repo.

**`access_denied` during OAuth**
Your Google account isn't added as a test user. Go to Google Auth Platform → Audience → Test Users → add your email.

**`spreadsheet_id not set`**
Run `init_sheet.py` or `connect.py` first for the project.

**`row_map.json not found` or `input_map.json not found`**
Run `init_sheet.py --project <name>` or `connect.py --project <name> --spreadsheet-id <id>`.

**`ERROR: Project directory not found`**
Either use `--template` with `init_sheet.py` to create from a template, or manually create the directory and copy a template into `projects/<name>/`.

**Push overwrites something I edited in the sheet**
Always pull before editing. To recover: check the sheet's version history (File → Version history in Google Sheets).
