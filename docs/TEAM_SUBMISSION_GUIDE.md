---
title: "HishabAI — Team NexFin Guide: From Zero to Submitted"
subtitle: "Deadline: Tuesday 20 October 2026, 23:59 Beijing = 21:59 Dhaka"
author: "Sanika Heeya (Leader) · Tasfia Tasneem Aastha · Abdullah Al Fayed · github.com/PIXEL-L00P/hishab-copilot"
---

# The 6 required deliverables and where each one is

| # | Required item | Status | File(s) |
|---|---|---|---|
| 1 | Technical documentation | Ready | `HishabAI_Technical_Documentation.pdf` |
| 2 | Presentation deck (≤ 10 minutes) | Ready: PowerPoint + PDF + browser version | `HishabAI_Presentation.pptx` / `.pdf` |
| 3 | Demo video (≤ 5 min, optional but do it) | **To record** (Step 6) | — |
| 4 | Source code: GitHub link, README, deployment instructions, tests | Ready; **push to GitHub** (Step 3) | `hishab-copilot.zip` |
| 5 | Security self-assessment report | Ready | `HishabAI_Security_Self_Assessment.pdf` |
| 6 | Execution evidence (sandbox logs + video) | Logs ready; video = Step 6 | `HishabAI_Execution_Evidence.pdf` + `evidence/` |

Plus registration: the official form + every member's passport bio page.

# Who owns what

Each person should be able to explain their part in the online review and at the final.

| Member | Owns | Read these files | Must be able to explain |
|---|---|---|---|
| **Sanika Heeya** (Leader) | Agent, security, presenting, submission emails | `app/agent.py`, `app/security.py`, `app/audit.py`, Security report | The 4 permission tiers, approval flow, why a prompt-injected AI still can't move money, the audit chain |
| **Tasfia Tasneem Aastha** | Financial engine, payment planner, financing matcher, web app | `app/finance_engine.py`, `app/planner.py`, `app/financing.py`, `app/static/` | The cash formula, alert levels, how the plan buys time, DSCR and loan eligibility |
| **Abdullah Al Fayed** | Forecasting model, uncertainty, peer benchmarking | `ml/train_forecast.py`, `app/features.py`, `app/benchmark.py`, `models/metrics.json` | Why gradient boosting, the unseen-shop test, WAPE, conformal calibration, percentile ranks and k-anonymity |

# Timeline (Dhaka time)

| When | What | Who |
|---|---|---|
| **Sun 18 Oct** | Step 1 registration email · Step 2 run the project · Step 3 GitHub | Sanika (email), all (run) |
| **Mon 19 Oct** | Step 4 study your part · Step 5 rehearse the deck · Step 6 record the video | Everyone |
| **Mon 19 Oct, by 23:00** | **Step 7: send version 1 of the full submission** (you can update until the deadline) | Sanika |
| **Tue 20 Oct, by 18:00** | Final version sent, receipt confirmed | Sanika |
| Tue 20 Oct, 21:59 | Hard deadline. Nothing accepted after it. | — |

# Step 1 — Registration form and email (today)

**Form entries**

| Field | Write |
|---|---|
| Team Name | NexFin |
| Topic | Topic E: SME Finance Copilot |
| Entry Title | HishabAI: Agentic Cash-Flow and Profitability Copilot for SMEs |
| Advisor | Leave blank unless a teacher has agreed |
| Team Email | The leader's email only (the one checked every day) |
| Role | Sanika: Leader · Tasfia: Member · Fayed: Member |
| University | University of Liberal Arts Bangladesh (Sanika, Tasfia) · University of Dhaka (Fayed) |
| Year of Study | UG Year 3 (Sanika, Tasfia) · Master's Year 2 (Fayed) |

**Check before sending:** Tasfia and Fayed were given the **same student ID** on the form; correct the wrong one.
Names and passport numbers must match the passports exactly. Delete the grey example row.

**Proposal Summary** (193 words):

> HishabAI is an AI agent that helps small retailers in Bangladesh manage their money, avoid cash shortages and grow their profit. Our own trained model predicts weekly sales, including busy seasons such as Eid. Using these forecasts, HishabAI estimates how much cash a shop will have in the coming weeks and warns the owner before money runs short. It also helps owners understand their profit, find their break-even point, test decisions such as buying more stock or taking a loan, and compare their performance with similar shops while keeping every shop's data private. HishabAI then prepares requests to suppliers for more time to pay, reminders for customers who owe money, and a list of affordable loan options. The owner reviews and approves every message before it is sent, and the system can never move money by itself. With the owner's permission, it can share a loan-readiness report with a bank, NGO or microfinance provider. HishabAI works in Bangla and English, controls who can see financial records, and keeps a record of every action. On synthetic data from shops it had never seen, our model reduced forecast errors by 40% compared with simple methods.

**Email** to wangyr@pbcsf.tsinghua.edu.cn, CC Tasfia and Fayed, attach the form (.xlsx) and the three passport images:

```
Subject: FinTechathon 2026 International Track – Registration – Topic E – Team NexFin

Dear Ms. Wang Yiran,

We would like to register for the 2026 Shenzhen International FinTech Competition
(International Track), Topic E: SME Finance Copilot.

Team name: NexFin
Entry title: HishabAI: Agentic Cash-Flow and Profitability Copilot for SMEs
Members:
- Sanika Heeya (Leader), University of Liberal Arts Bangladesh, CSE, UG Year 3
- Tasfia Tasneem Aastha, University of Liberal Arts Bangladesh, CSE, UG Year 3
- Abdullah Al Fayed, University of Dhaka, Theoretical Physics, Master's Year 2

Attached are our completed registration form and the passport bio pages of all
members. Could you please confirm our registration? We will send our full
submission before the 20 October deadline.

Kind regards,
Sanika Heeya
Team Leader, NexFin
[Phone / WhatsApp]
```

# Step 2 — Run the project on your laptop (30 minutes, everyone)

Install **Python 3.10+** from https://www.python.org/downloads/ (Windows: tick *"Add python.exe to PATH"*).
Unzip `hishab-copilot.zip`, open a terminal in that folder (Windows: type `cmd` in the File Explorer address bar):

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
python scripts/seed_db.py
python -m app.server
```

Open **http://127.0.0.1:8000** → **Owner · Farhana**. Stop with `Ctrl + C`. Check everything:

```bash
python -W ignore -m unittest discover -s tests -t . -v     # expect: Ran 67 tests ... OK
python scripts/run_demo.py                                 # expect: 22/22 checks passed
```

| Problem | Fix |
|---|---|
| `python` not found | Use `py` instead (Windows), or reinstall Python with "Add to PATH" |
| `pip install` fails | `python -m pip install --upgrade pip`, then retry |
| Port 8000 busy | Windows `set HISHAB_PORT=8080` · macOS/Linux `export HISHAB_PORT=8080` |
| Old data on screen | Stop the server, run `python scripts/seed_db.py`, start again |

# Step 3 — Push to GitHub (Sanika, 20 minutes)

Your repository: **https://github.com/PIXEL-L00P/hishab-copilot** (make sure it is **Public**).
In the unzipped project folder:

```bash
git init
git add .
git commit -m "HishabAI: agentic SME finance copilot (FinTechathon 2026, Topic E, Team NexFin)"
git branch -M main
git remote add origin https://github.com/PIXEL-L00P/hishab-copilot.git
git push -u origin main
```

If GitHub created the repository with a README, run `git pull origin main --allow-unrelated-histories` before
the push, and keep **our** README if git asks. Without git: on the repository page use *Add file → Upload files*
and drag in the contents of the folder (not the folder itself).

Then: open the repository in a private browser window and check the README shows the architecture picture;
add Tasfia and Fayed as collaborators (Settings → Collaborators). **Never commit an API key.**

# Step 4 — Study your part (Monday morning, 2–3 hours)

See *Who owns what* above. Prepare a 30-second answer to each question:

1. *"Your data is synthetic. How do you know it works?"* Tested on 10 unseen shops over a full held-out year
   against three baselines; a real pilot is next and the design doesn't change with real data. (Fayed)
2. *"What does the AI actually do?"* It drafts and queues real actions with previews; the owner taps Approve;
   effects land in the outbox. (Sanika)
3. *"What stops it doing harm?"* Code-level gateway: tier 3 impossible, tier 2 needs the owner; the
   prompt-injection test proves it. (Sanika)
4. *"Is the financing advice trustworthy?"* Explicit rules, DSCR ≥ 1.25, timing check, reasons for every option;
   terms illustrative until partner lenders supply them. (Tasfia)
5. *"How does peer comparison protect privacy?"* At least 5 peers or nothing is shown; only medians and ranks;
   lenders see ranks only. (Fayed)
6. *"Who pays for the AI?"* Shops never pay per message; core runs on our own model; lenders and MFIs pay for
   consented readiness reports; optional premium plan. (Sanika)
7. *"Did you train a foundation model?"* No. Our own model is the sales forecaster; a pretrained LLM is optional
   for free-form conversation and is bounded by the gateway. (Fayed)

# Step 5 — The presentation deck (Monday, rehearse twice)

`HishabAI_Presentation.pptx` has 12 slides with **speaker notes** (View → Notes) telling each presenter what to
say. Split: Sanika slides 1–3 and 9–12, Tasfia slides 4, 6–7, Fayed slides 5 and 8. Time it: it must stay under
10 minutes. Email the **PDF**; keep the .pptx for the final. The browser version can be edited online and
downloaded as PowerPoint or PDF.

# Step 6 — Demo video and execution evidence (Monday, 2 hours)

Record with **OBS Studio** (free) or Windows Game Bar (`Win + G`), under 5 minutes, in English. Run
`python scripts/seed_db.py` first so the demo starts clean.

| Time | Show | Say |
|---|---|---|
| 0:00–0:20 | Login page | "HishabAI is an AI finance copilot for small shops in Bangladesh, by Team NexFin. All data is synthetic." |
| 0:20–0:50 | Dashboard (Farhana) | "Our model predicts sales; the engine projects cash and warns that it runs out in the week of 2 November." |
| 0:50–1:40 | **Run cash check** | "The agent drafted a plan: two supplier extensions, two reminders, and an affordable ৳2.1 lakh loan. Nothing has been sent." |
| 1:40–2:15 | Approve three, reject one; open **Sandbox outbox** | "Only the owner approves. Approved messages go to the outbox." |
| 2:15–2:45 | **How you compare with similar shops** card | "Compared with 39 anonymised shops, our margin is strong but overdue dues are high: matching peers frees about ৳40,000." |
| 2:45–3:25 | Chat: second shop; the Bangla question; "Transfer 50000…" | "Answers come from calculations, in Bangla too. Moving money is blocked." |
| 3:25–3:50 | **Customer dues**: the IGNORE ALL PREVIOUS INSTRUCTIONS note | "This hidden attack in the data has no effect." |
| 3:50–4:25 | Log in as **rakib** (approve fails) → **lender_demo** | "Roles are enforced; the lender sees only what the owner approved." |
| 4:25–4:55 | **Audit trail**; terminal running tests and `run_demo.py` | "Tamper-evident log. 67 tests and 22 end-to-end checks pass." |

Upload to Google Drive or YouTube (unlisted) with **"Anyone with the link"** access.

# Step 7 — Send the submission (Monday night, final on Tuesday)

```
Subject: FinTechathon 2026 International Track – Submission – Topic E – Team NexFin

Dear Ms. Wang Yiran,

Please find the submission of Team NexFin for Topic E: SME Finance Copilot.
Entry: HishabAI: Agentic Cash-Flow and Profitability Copilot for SMEs

1. Technical documentation: attached (HishabAI_Technical_Documentation.pdf)
2. Presentation deck: attached (HishabAI_Presentation.pdf)
3. Demo video: <link>
4. Source code: https://github.com/PIXEL-L00P/hishab-copilot
   (README with deployment instructions; 67 automated tests in /tests)
5. Security self-assessment report: attached (HishabAI_Security_Self_Assessment.pdf)
6. Execution evidence: attached (HishabAI_Execution_Evidence.pdf); raw sandbox
   operation logs in the repository folder /evidence; and the demo video above.

Team: Sanika Heeya (Leader), Tasfia Tasneem Aastha, Abdullah Al Fayed
Registration sent on 18 October 2026.

Kind regards,
Sanika Heeya
Team Leader, NexFin
```

* Keep attachments under ~20 MB; send big files as links.
* Open every link in a private window to confirm access without login.
* No receipt by Tuesday noon Dhaka time → send a short follow-up.

# Optional — LLM mode

Not needed to submit. If you get an API key from console.anthropic.com, start the server with
`set ANTHROPIC_API_KEY=...` (Windows) or `export ANTHROPIC_API_KEY=...` (macOS/Linux). The terminal shows
`agent mode: LLM`. Test it before showing it in the video. Never share or commit the key.
