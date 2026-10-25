# Bracketman 🚀🤼

A modern wrestling tournament manager, grouping engine, and printable bracket generator built in Python and Streamlit.

Bracketman reads multi-tab wrestling team rosters directly from Google Spreadsheets (or local `.xlsx` / `.csv` files), normalizes divisions (`Coed` and `Girls`), age groups (`4U`, `6U`, `8U`, `10U`, `12U`, `15U` with `14U` aliased into `15U`), and skill levels (`Beginner` / `Advanced`), and builds optimal **Madison weight groups** (target size: 4) using dynamic programming with progressive weight spread scaling, teammate separation, and unshaded printable mat table score sheets.

---

## Features

- **Interactive Streamlit Web Application (`bracketman ui`)**:
  - **Multi-Tournament Persistence**: Tournaments are stored automatically in `data/tournaments/<slug>/tournament.json` across crashes and reboots.
  - **Google Sheet Sync**: Connect a Google Spreadsheet link; sync with **Full Overwrite** or **Preserve Locked Brackets**.
  - **Live Walk-Ins & Scratches**:
    - Add unannounced walk-ins with intelligent bracket suitability scoring (weight spread %, teammate presence, and pod size).
    - Scratch no-show wrestlers from single brackets or dual-entry divisions with 1-click restore.
  - **Rethink & Re-Optimize Active Brackets**:
    - Re-run the Madison dynamic programming engine over all active (walk-ins included, scratches excluded) wrestlers across a specific division/age group or the entire tournament.
    - Targeted bracket regeneration by Bracket IDs (e.g., `COED-8U-BEG-01, COED-8U-BEG-02`) with optional rule overrides or cross-skill pooling.
  - **Manual Mat-side Tweaks**:
    - Move wrestlers between brackets or spin off new pods.
    - Swap wrestlers between brackets with one click.
    - Merge straggler brackets directly from built-in advisor prompts.
    - Edit scale check-in weights, wrestler names, or clubs on the fly.
    - Lock/unlock brackets.
  - **Printable Mat Table Score Sheets**:
    - Unshaded 3-period score sheets (`BOUT | WT | WRESTLERS NAME | 1ST PERIOD | PTS | 2ND PERIOD | PTS | 3RD PERIOD | PTS`).
    - Wrestler Win/Loss tally tables and explicit Round Robin tiebreaker criteria & activity points breakdown (DEC 1–7 pts vs MD 8–14 pts vs TF 15+ pts).
    - Multi-tab Excel workbooks (`.xlsx`), CSV files, and printable HTML.

---

## Linux Installation Guide

Follow these steps to install and run Bracketman on any Linux computer (Ubuntu, Debian, Fedora, RHEL, Arch, openSUSE).

### 1. Install System Prerequisites

Bracketman requires **Python 3.10+**, **Git**, and the Python `venv` module.

#### Ubuntu / Debian / Linux Mint / Pop!_OS
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git curl
```

#### Fedora / RHEL / Rocky Linux
```bash
sudo dnf install -y python3 python3-pip git curl
```

#### Arch Linux / Manjaro
```bash
sudo pacman -S --needed python python-pip git curl
```

#### openSUSE
```bash
sudo zypper install -y python3 python3-pip git curl
```

Verify your Python version (must be 3.10 or higher):
```bash
python3 --version
```

---

### 2. Clone the Repository

Clone the Bracketman repository into your personal code or applications folder:

```bash
cd ~
git clone https://github.com/sengelbert/bracketman.git
cd bracketman
```

*(If using SSH keys with GitHub: `git clone git@github.com:sengelbert/bracketman.git`)*

---

### 3. Create & Activate a Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

> [!TIP]
> Always make sure `.venv` is activated when running Bracketman. Your terminal prompt will display `(.venv)`.

---

### 4. Install Bracketman & Dependencies

Upgrade pip and install Bracketman in editable mode:

```bash
pip install --upgrade pip
pip install -e .
pip install pytest
```

---

### 5. Verify the Installation

Run the automated test suite to confirm everything is working properly:

```bash
pytest -v
```
*(All tests should pass in under a second.)*

Check the CLI tool:
```bash
bracketman --help
```

---

## Running Bracketman

### Option A: Launch the Streamlit Web UI

```bash
# Launch on default port 8503
bracketman ui

# Or specify a custom port:
bracketman ui --port 8503
```

Open your web browser and navigate to:
```
http://localhost:8503
```

### Option B: Access from Other Laptops or Tablets on LAN / Mat-side Wi-Fi

To allow table workers or coaches on other computers to access Bracketman on the local network, bind to `0.0.0.0`:

```bash
source .venv/bin/activate
streamlit run src/bracketman/web/app.py --server.port 8503 --server.address 0.0.0.0
```

If your Linux machine has an active firewall (such as `ufw` on Ubuntu):
```bash
sudo ufw allow 8503/tcp
```

Other computers on the same Wi-Fi or router can now open:
```
http://<LINUX-MACHINE-IP>:8503
```
*(Run `hostname -I` or `ip a` on the host machine to find its local IP address).*

---

### Option C: Run as a Background System Service (systemd)

For dedicated tournament laptops or mini-PCs running at the head table, you can configure Bracketman to run automatically on system boot.

Create a systemd unit file:
```bash
sudo nano /etc/systemd/system/bracketman.service
```

Paste the following configuration (replace `<username>` with your Linux username):
```ini
[Unit]
Description=Bracketman Wrestling Tournament Manager
After=network.target

[Service]
Type=simple
User=<username>
WorkingDirectory=/home/<username>/bracketman
ExecStart=/home/<username>/bracketman/.venv/bin/streamlit run src/bracketman/web/app.py --server.port 8503 --server.address 0.0.0.0 --server.headless true
Restart=on-failure
RestartSec=5s
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bracketman
```

Check service status:
```bash
sudo systemctl status bracketman
```

---

## Tournament Workflow: Scratches, Walk-Ins & Rethinking Brackets

When running a tournament, changes happen fast at the check-in table. Bracketman gives you three seamless ways to refresh and rethink brackets:

### 1. Live Mat-side Scratches & Walk-Ins (In-App)
1. Go to the **🛠️ Tweak & Regenerate by ID** tab.
2. **Scratches**: Under **❌ Scratch No-Show Wrestler**, select the wrestler and click **Confirm Scratch**. The wrestler is removed from their bracket, and bout schedules update immediately.
3. **Walk-Ins**: Under **➕ Add Walk-In Wrestler**, enter the wrestler's name, scale weight, and age/skill. Bracketman ranks the best existing brackets by weight spread and teammate balance, or lets you spin off a new bracket.

### 2. Rethinking & Re-Optimizing Brackets after Scratches
When multiple scratches or walk-ins leave some brackets with 2 or 3 wrestlers and unbalanced weights:
- **Scope-Wide Rethink**:
  1. In **🛠️ Tweak & Regenerate by ID**, navigate to **🔄 Refresh & Rethink Brackets**.
  2. Choose **"By Division / Age Group (or Whole Tournament)"**.
  3. Select your scope (e.g. `Coed - 8U` or `ALL`).
  4. Ensure **"Preserve Locked / Hand-Tweaked Brackets"** is checked (to protect brackets you already finalized).
  5. Click **⚡ Rethink & Re-Optimize Brackets**.
  6. The Madison DP engine pools all active wrestlers (excluding scratches, including walk-ins) and re-partitions them into clean 4-person brackets.
- **Targeted Rethink (by Bracket IDs)**:
  1. Switch to **"Targeted Selection by Specific Bracket ID(s)"**.
  2. Select only the affected bracket IDs (e.g. `COED-8U-BEG-01` and `COED-8U-BEG-02`).
  3. Click **⚡ Regenerate Selected Bracket(s)**.

### 3. Re-Syncing from Google Sheets
If coaches or table staff update the master Google Sheet directly during check-ins:
1. Go to the **📥 Sheet Import & Sync** tab.
2. Select **"Sync with Sheet (Preserve Locked/Tweaked Brackets)"** to pull new weights and entries while protecting brackets you locked.
3. Or select **"Full Overwrite"** to re-import and rebuild the entire tournament from the raw sheet.

---

## Updating Bracketman

To pull the latest updates and bug fixes from GitHub:

```bash
cd ~/bracketman
git pull origin main
source .venv/bin/activate
pip install -e .
pytest -v
```

---

## License

MIT License. Designed for youth wrestling leagues and tournament directors.
