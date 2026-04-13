# 🎯 Job Search Agent — Complete Setup Guide (Windows 11)

## 💰 COST: $0 forever

| Component | Cost | Why free |
|-----------|------|----------|
| Python | $0 | Open source |
| pip libraries | $0 | Open source (requests, beautifulsoup4) |
| Gmail SMTP | $0 | You use 1 of 500 free daily emails |
| GitHub repo | $0 | Private repos are free |
| GitHub Actions | $0 | Uses ~2 min/day of 2,000 free min/month |
| All 30 job boards | $0 | Public scraping, no API keys |
| **TOTAL** | **$0/month** | **$0/year, forever** |

---

## STEP 1 — Install Python (5 minutes)

1. Press **Windows key**, type `cmd`, press **Enter**
2. Type this and press Enter:
   ```
   python --version
   ```
3. If you see `Python 3.x.x` → skip to Step 2
4. If you see an error or Microsoft Store opens:
   - Go to: https://www.python.org/downloads/
   - Click the big yellow **"Download Python 3.x.x"** button
   - Run the installer
   - ⚠️ **CRITICAL: Check the box "Add Python to PATH"** at the bottom of the installer
   - Click "Install Now"
   - When done, close and reopen cmd, try `python --version` again

---

## STEP 2 — Create Project Folder (1 minute)

1. Open **File Explorer**
2. Go to your **Documents** folder
3. Create a new folder called `job_search_agent`
4. Download all the files I gave you and put them inside this folder:
   - `job_search_agent_v2.py`
   - `requirements.txt`
   - `.env.template`
   - `QUICK_REFERENCE.txt`
   - `.gitignore`
   - Create subfolder: `.github\workflows\` and put `daily_search_v2.yml` inside

Your folder should look like:
```
Documents\job_search_agent\
├── job_search_agent_v2.py
├── requirements.txt
├── .env.template
├── .gitignore
├── QUICK_REFERENCE.txt
└── .github\
    └── workflows\
        └── daily_search_v2.yml
```

---

## STEP 3 — Install Dependencies (1 minute)

1. Open **cmd** (Windows key → type `cmd` → Enter)
2. Navigate to your folder:
   ```
   cd Documents\job_search_agent
   ```
3. Install the two libraries:
   ```
   pip install -r requirements.txt
   ```
   You should see "Successfully installed requests beautifulsoup4"

If `pip` doesn't work, try:
```
python -m pip install -r requirements.txt
```

---

## STEP 4 — Create Gmail App Password (3 minutes)

⚠️ This is the only "tricky" step. You need a special password because Gmail blocks scripts from using your regular password.

1. Open Chrome and go to: https://myaccount.google.com/security

2. Scroll down to **"2-Step Verification"**
   - If it says **OFF**: Click it, follow Google's steps to turn it ON (they'll text you a code)
   - If it says **ON**: Good, move to step 3

3. Now go to: https://myaccount.google.com/apppasswords
   - You might need to enter your Google password
   - In the **"App name"** field, type: `Job Search Agent`
   - Click **Create**
   - Google shows you a **16-character password** (looks like: `abcd efgh ijkl mnop`)
   - **COPY IT NOW** — write it down or paste it somewhere, you won't see it again
   - Remove the spaces so it looks like: `abcdefghijklmnop`

---

## STEP 5 — Create Your .env File (2 minutes)

1. In your `job_search_agent` folder, find the file `.env.template`
2. Make a copy of it and rename the copy to `.env`
   - If Windows won't let you create a file starting with a dot:
     - Open **cmd**
     - Run: `cd Documents\job_search_agent`
     - Run: `copy .env.template .env`
3. Open `.env` with **Notepad** (right-click → Open with → Notepad)
4. Replace the placeholder with your real app password:
   ```
   set EMAIL_ADDRESS=eugeniogdelatorre@gmail.com
   set EMAIL_PASSWORD=abcdefghijklmnop
   set RECIPIENT_EMAIL=eugeniogdelatorre@gmail.com
   ```
   ⚠️ Note: On Windows use `set` instead of `export`
5. Save and close

---

## STEP 6 — Test Dry Run (2 minutes)

This tests the scraping without sending an email.

1. Open **cmd**
2. Navigate to folder:
   ```
   cd Documents\job_search_agent
   ```
3. Load your credentials:
   ```
   .env
   ```
   (Yes, just type `.env` and press Enter — Windows will run it as a batch file with the `set` commands)
4. Run the dry test:
   ```
   python job_search_agent_v2.py --dry-run --verbose
   ```
5. Wait 2-5 minutes (it's hitting 30 websites)
6. When done, you'll see a summary in the terminal
7. A file called `job_digest_preview.html` appears in your folder
8. Double-click it to open in your browser — this is what your daily email will look like

---

## STEP 7 — Test Real Email (1 minute)

1. In the same cmd window (credentials still loaded):
   ```
   python job_search_agent_v2.py
   ```
2. Check your Gmail inbox within 30 seconds
3. Also check your **Spam** folder (first email might land there)
4. If it's in spam: Open it → Click "Not spam" → future emails will go to inbox

### Troubleshooting email issues:
- **"Authentication failed"**: Double-check your app password in `.env` (no spaces, no quotes around the password)
- **"Connection refused"**: Your firewall might block port 465. Try running on a different network
- **No email at all**: Check the terminal output for error messages

---

## STEP 8 — Push to GitHub (10 minutes)

This is the most important step — it lets the job search run automatically in the cloud every day, even when your computer is off.

### 8a. Install Git (if needed)

1. Open cmd, type:
   ```
   git --version
   ```
2. If you see a version number → skip to 8b
3. If not installed:
   - Go to: https://git-scm.com/download/win
   - Download and run the installer
   - Accept all defaults, click Next through everything
   - Close and reopen cmd

### 8b. Create the GitHub Repository

1. Go to: https://github.com/new
2. Fill in:
   - **Repository name**: `job-search-agent`
   - **Description**: `Daily automated job search - 30 sources`
   - **Visibility**: Select **Private** (keeps your setup private)
   - ⚠️ Do NOT check "Add a README file"
   - ⚠️ Do NOT select a .gitignore template (we already have one)
3. Click **"Create repository"**
4. You'll see a page with setup instructions — leave this page open

### 8c. Push Your Files

1. Open **cmd**
2. Run these commands ONE BY ONE:
   ```
   cd Documents\job_search_agent

   git init

   git add .

   git commit -m "Job search agent v2 - 30 sources"

   git branch -M main

   git remote add origin https://github.com/YOUR_GITHUB_USERNAME/job-search-agent.git

   git push -u origin main
   ```
   ⚠️ Replace `YOUR_GITHUB_USERNAME` with your actual GitHub username

3. Git may ask you to log in — follow the prompts
   - If it opens a browser window, sign in to GitHub
   - If it asks for username/password in terminal: use your GitHub username and a **Personal Access Token** (not your password)
     - Get a token at: https://github.com/settings/tokens → "Generate new token (classic)" → check "repo" → Generate → Copy the token

### 8d. Add Secrets to GitHub

This is how GitHub Actions gets your email password without it being in the code.

1. Go to your repo: `https://github.com/YOUR_USERNAME/job-search-agent`
2. Click **Settings** tab (top bar, far right)
3. In the left sidebar, click **Secrets and variables** → **Actions**
4. Click **"New repository secret"**
5. Add THREE secrets (one at a time):

   **Secret 1:**
   - Name: `EMAIL_ADDRESS`
   - Value: `eugeniogdelatorre@gmail.com`
   - Click "Add secret"

   **Secret 2:**
   - Name: `EMAIL_PASSWORD`
   - Value: `abcdefghijklmnop` (your 16-char app password)
   - Click "Add secret"

   **Secret 3:**
   - Name: `RECIPIENT_EMAIL`
   - Value: `eugeniogdelatorre@gmail.com`
   - Click "Add secret"

---

## STEP 9 — Test GitHub Actions (2 minutes)

1. Go to your repo on GitHub
2. Click the **"Actions"** tab
3. You should see **"Daily Job Search v2"** on the left
4. Click on it
5. Click the **"Run workflow"** dropdown button (right side)
6. Click the green **"Run workflow"** button
7. Wait 2-5 minutes — you'll see a yellow dot (running) then green check (success)
8. Check your email — you should get the digest!

If it shows a red X (failed):
- Click on the failed run
- Click on the "search" job
- Read the error logs
- Most common issue: secrets not set correctly (check step 8d)

---

## ✅ YOU'RE DONE!

The agent now runs automatically every day at **8:00 AM Buenos Aires time**.

You will receive an email every morning with all matching jobs from the last 24 hours, with direct links to every listing.

---

## What Happens Next

- **Every morning at 8 AM**: GitHub runs your script in the cloud
- **You receive an email**: With scored, filtered jobs + direct links
- **Deduplication**: You won't see the same job twice (cache tracks seen jobs)
- **Zero maintenance**: It just works, indefinitely

---

## Optional: Fine-Tuning (anytime)

### Too many irrelevant jobs?
Edit `job_search_agent_v2.py`, find `MIN_RELEVANCE_SCORE = 35`, change to `50` or `60`

### Too few results?
Change `MIN_RELEVANCE_SCORE` to `25` or `20`

### Want emails twice a day?
Edit `.github/workflows/daily_search_v2.yml`, change the cron line to:
```yaml
- cron: '0 11,21 * * *'
```
(This runs at 8 AM and 6 PM Buenos Aires time)

### Want to add a new exclusion?
Find the `EXCLUSIONS` list in the script, add your term:
```python
EXCLUSIONS = [
    "Intern", "Internship", "Junior",
    "Your New Exclusion Here",  # ← add like this
]
```

### Reset and see all jobs again?
Delete `jobs_cache.json` from the repo or locally

### After any edit:
Push changes to GitHub:
```
cd Documents\job_search_agent
git add .
git commit -m "Updated filters"
git push
```

---

## Quick Command Reference (Windows)

```
cd Documents\job_search_agent        # Go to folder
.env                                  # Load credentials
python job_search_agent_v2.py         # Run + send email
python job_search_agent_v2.py --dry-run     # Preview only
python job_search_agent_v2.py --verbose     # Show scoring
git add . && git commit -m "update" && git push  # Push changes
```
