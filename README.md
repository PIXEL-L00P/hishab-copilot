# HishabAI — Agentic SME Finance Copilot

**2026 Shenzhen International FinTech Competition (FinTechathon), International Track — Topic E: SME Finance Copilot**
Theme: *AI as a Financial Participant* · **Team NexFin** (University of Liberal Arts Bangladesh & University of Dhaka)

HishabAI ("hishab" means *accounts* in Bangla) is an AI agent for small shops in Bangladesh. It watches the
business's cash, **warns weeks before money runs short**, and then **acts**: it drafts a payment plan, asks
suppliers for more time, chases overdue customers and finds financing the shop can actually afford. Every action
that leaves the system waits for the owner's approval. Anything that moves money is blocked by design.

![Architecture](docs/figures/architecture.png)

## What it does

| Capability | How |
|---|---|
| **Cash-flow alerts** | Our own forecasting model (gradient-boosted trees, Eid-aware) predicts 8 weeks of sales with a calibrated 80% band. A deterministic engine turns that into a week-by-week cash projection and raises *healthy / warning / critical* alerts. |
| **Payment planner** | Moves flexible supplier bills by at most 4 weeks to push the first shortfall later. It never touches salaries, rent, tax or loan instalments. It also reminds overdue customers and sizes any remaining financing need. |
| **Financing matching** | Checks each financing option against explicit eligibility rules, computes the instalment and debt-service coverage (DSCR ≥ 1.25), checks whether money can arrive before the shortfall, and ranks the options with reasons. |
| **Business analysis** | Margin, break-even, runway, DSCR, overdue dues, plus what-if scenarios ("Can I afford a second shop?"). |
| **Peer benchmarking** | Compares the shop with anonymised similar shops on margin, growth, cost ratio, overdue dues, cash buffer and DSCR, and gives a taka-quantified tip where it lags (e.g. "bringing overdue dues to the peer level would free about ৳40,299"). Results are released only for groups of at least 5 peers, and only medians and percentiles are shown. |
| **Acts with permission tiers** | Tier 0 analyse → Tier 1 draft → **Tier 2 waits for owner approval** → **Tier 3 (move money, submit applications) always blocked**. Enforced in code for both the offline agent and the optional LLM. |
| **Bangla + English** | Ask in Bangla and the agent answers in Bangla. Customer reminders are available in both languages. |
| **Security** | Roles (owner, accountant, lender), PBKDF2 passwords, hashed session tokens, lockout, append-only records, a tamper-evident hash-chained audit log, CSP headers, and prompt-injection-safe tool design. |

### Forecast accuracy (synthetic data, strict hold-out)

Tested on **10 shops the model never saw**, over a full year (Oct 2025 – Oct 2026) that includes Eid-ul-Fitr and Eid-ul-Adha:

| Method | WAPE (lower is better) | WAPE in the 5 weeks before Eid |
|---|---|---|
| **HishabAI model** | **12.5%** | **12.0%** |
| Baseline: 4-week mean | 20.9% | 36.3% |
| Baseline: last week | 23.4% | 36.0% |
| Baseline: seasonal naive | 24.3% | 35.3% |

The 80% uncertainty band covers 87.9% of actual outcomes after conformal calibration (71.6% before). Full results are in `models/metrics.json`.

## Quick start (5 minutes)

Requirements: **Python 3.10+**. The only dependencies are numpy, pandas, scikit-learn and joblib (matplotlib is needed only to redraw figures).

```bash
git clone https://github.com/PIXEL-L00P/hishab-copilot.git
cd hishab-copilot
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

python scripts/seed_db.py          # create data/hishab.db from the synthetic data
python -m app.server               # open http://127.0.0.1:8000
```

The trained model (`models/forecast_model.joblib`) and the synthetic data are already included, so the
server works immediately. To rebuild everything from scratch:

```bash
python data/generate_synthetic.py  # regenerate synthetic shops (fixed random seed)
python ml/train_forecast.py        # retrain + evaluate the model (~20 s on a laptop CPU)
python scripts/seed_db.py
```

### Demo accounts (synthetic data only)

| Username | Password | Role |
|---|---|---|
| `farhana` | `StyleCorner#2026` | Owner of *Style Corner* (the demo shop): sees everything, approves actions |
| `rakib` | `Accounts#2026` | Accountant: can analyse and add records, **cannot** approve actions |
| `lender_demo` | `LenderDesk#2026` | Lender: sees **only** reports the owner approved to share |
| `owner2` | `SecondShop#2026` | Owner of a different shop (used to test business isolation) |

### Demo walkthrough

1. Sign in as **farhana**. The banner shows *Cash shortfall ahead*: cash goes negative in the week of 2 Nov 2026.
2. Click **Run cash check**. The agent drafts a plan: two supplier extensions and two customer reminders. It finds a
   remaining ৳2.1 lakh gap and matches a concessional loan with DSCR 1.61. Nothing is sent yet; 4 actions wait for approval.
3. **Approve** or **Reject** each action. Approved messages appear in *Sandbox outbox*.
4. Scroll to **How you compare with similar shops**: strong margin (better than 85% of peers), but overdue dues need attention.
5. Ask: *"Can I afford to open a second shop?"*, *"Am I more profitable than similar shops?"*, *"নতুন দোকান খুললে কী হবে?"*, or *"Transfer 50000 to Nur Fabrics now"* (blocked).
6. Ask *"share the report with the lender"*, approve it, then sign in as **lender_demo** to see it.
7. Open *Audit trail*: the hash chain verifies that no log entry was altered.

## Tests and execution evidence

```bash
python -W ignore -m unittest discover -s tests -t . -v   # 67 tests, about 7 seconds
python scripts/run_demo.py                               # 22 end-to-end checks on the live server
```

* `evidence/EXECUTION_EVIDENCE.md`: results of the end-to-end sandbox run (22/22 pass)
* `evidence/execution_log.jsonl`: raw request/response operation log (secrets redacted)
* `evidence/test_results.txt`: unit and API test output

## Optional: LLM mode

By default the agent runs fully offline: a rule-based planner that understands English and Bangla. To let a large
language model plan the tool calls instead, set an API key before starting the server:

```bash
export ANTHROPIC_API_KEY=...                 # Windows PowerShell: $env:ANTHROPIC_API_KEY="..."
export HISHAB_LLM_MODEL=claude-sonnet-5-5    # optional
python -m app.server
```

The LLM can only *request* tools. The same permission gateway approves, queues or blocks every request, so a
confused or prompt-injected model still cannot send messages without approval or move money. If the API fails,
the agent falls back to offline mode automatically.

## Project structure

```
app/
  server.py          HTTP API + static UI (Python standard library)
  agent.py           tools, permission gateway, approvals, cash check, chat (rule-based / LLM)
  finance_engine.py  deterministic formulas: summary, cash projection, scenarios
  planner.py         payment-plan algorithm
  financing.py       financing matcher + loan-readiness report
  benchmark.py       anonymised peer benchmarking (k-anonymity, medians/percentiles only)
  forecast.py        serves the trained model
  features.py        feature engineering shared by training and serving
  calendar_bd.py     Eid / Pohela Boishakh calendar features
  security.py        passwords, sessions, lockout, role permissions
  audit.py           hash-chained audit log
  db.py              SQLite schema, financing catalogue, seeding
  static/            web UI (HTML/CSS/JS, no external libraries)
data/generate_synthetic.py   synthetic data generator (documented assumptions)
ml/train_forecast.py         training + evaluation vs baselines
models/                      trained model + metrics.json
scripts/                     seed_db.py, run_demo.py
tests/                       67 unit, security, agent, benchmarking and API tests
docs/                        technical documentation, security self-assessment, figures
evidence/                    execution evidence for the submission
```

## AI components

| Component | What it is |
|---|---|
| **Our own trained model** | Weekly sales forecaster (gradient-boosted trees + calibrated quantile band), trained and evaluated by the team in `ml/train_forecast.py` |
| **Pretrained foundation model (optional)** | A large language model (Claude, via API) that understands free-form questions and plans tool calls. It can only *request* tools; the permission gateway decides. Without an API key the agent runs offline. |

## Business model

Shops never pay per message. Core features (forecast, alerts, plans, financing match, benchmarking, offline chat) run on
our own model and engine at near-zero marginal cost; the LLM is used only for free-form conversation, with
smaller models and usage limits. Revenue comes from banks, NGOs and microfinance institutions that pay for
consented, structured loan-readiness reports (lower assessment cost and default risk), plus an optional premium
plan for unlimited AI conversation.

## Data and honesty notes

* **All data is synthetic.** It comes from `data/generate_synthetic.py`, which encodes Bangladeshi retail
  patterns (Eid peaks, credit sales, festival bonuses). Forecast accuracy on synthetic data does **not** prove
  real-world accuracy; a pilot with real shops is the next step.
* **Peer data is synthetic too.** In a real deployment, peers are other HishabAI shops that consent to share anonymised figures.
* **Financing terms are illustrative.** Product names are generic categories. Real terms must come from partner lenders.
* HishabAI supports decisions. It does not make credit decisions, give legal advice, or move money.

## Team NexFin

| Member | University | Programme | Role |
|---|---|---|---|
| **Sanika Heeya** (Leader) | University of Liberal Arts Bangladesh | BSc Computer Science and Engineering, Year 3 | Agent design, security and presentation |
| **Tasfia Tasneem Aastha** | University of Liberal Arts Bangladesh | BSc Computer Science and Engineering, Year 3 | Financial engine, payment planner, financing matcher and web app |
| **Abdullah Al Fayed** | University of Dhaka | MS Theoretical Physics, Year 2 | Forecasting model, uncertainty calibration and peer benchmarking |

## License

MIT. See `LICENSE`. Third-party components: numpy, pandas, scikit-learn, joblib (BSD-style licences);
matplotlib (PSF-style licence, figures only).
