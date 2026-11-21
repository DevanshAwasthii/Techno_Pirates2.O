# NexData — Personal Data Footprint Auditor

A local Windows desktop application that inspects supported data sources and explains their privacy implications with evidence and suggested actions.

**The app starts with a real PC scan. Bundled `samples/persona_*` files and `mock/findings.json` are synthetic test fixtures, not information about the person running the app. The normal GUI does not load those fixtures.**

## Setup and run

The current desktop build targets Windows and Python 3.12. The checkout can live in any folder; application paths follow the package location. Run commands below from your checkout root. PDF reports default to your Documents folder (or the checkout root if Documents is absent), and the GUI shows the saved path.

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
& .\.venv\Scripts\python.exe -m app.ui.main
```

After the first setup, run only the last command from your checkout root.

## What the current version scans

- Laptop app-folder sizes, file counts and modification timestamps under AppData.
- Bounded `.log`/`.txt` scans that retain email, IPv4 and Indian-phone pattern counts, not matched values.
- Available Chrome/Edge profiles: history metadata, cookie names/domains, saved-login domains and site permissions. Password and cookie values are not selected.
- User-selected Instagram, WhatsApp, Gmail, Spotify and supported browser exports.
- User-selected recordings/screenshots for supported friend-activity and status-viewer OCR patterns.
- Imported Android device scans and iPhone App Privacy Report NDJSON.

The GUI includes Footprint, Scan coverage, What they know, Inner circle, Findings, Fix first, evidence windows and local PDF export. The footprint map groups canonical services into up to eight categories; click a group for its services, findings and source records. Company names and common domain variants count once. Gmail Spam/Trash messages are ignored with a count in Scan coverage. Browser cookies for a service with account evidence are excluded from tracker totals; saved logins establish this relationship only within their browser profile.

## Browser locks

Closing a browser window may leave background processes holding its databases. NexData identifies verified Chrome/Edge file owners and offers **Close browsers and rescan**. This requires confirmation. It tries normal shutdown first; with explicit consent, it can stop verified background processes if normal shutdown fails. Visible browser windows must be closed first. This can interrupt browser background apps or downloads.

The scanner does not bypass database locks. It briefly copies each browser database and any matching SQLite WAL, shared-memory or rollback-journal files into the ignored local cache, queries supported metadata read-only, then removes the copies on success or failure. Cookie values, usernames and passwords are never selected into scan records.

## Coverage and interpretation

Open **Scan coverage** to see each supported browser database, storage/log check and imported report labelled Scanned, Partial, Unavailable, Not provided or Not assessed. A finished run is not a claim that the entire device was audited. Partial status remains visible even when there are no read errors.

Choose **Quick (20s)** or **Extended (120s)** before scanning. Extended mode gives folder measurement more time; it keeps the same folder-selection and log limits. A `+` after a storage or tracker figure identifies an incomplete subtotal/lower bound. Missing chat imports are shown as **Not provided**, not as zero sensitive data. PDFs include the same coverage information.

- The laptop scan uses the selected 20- or 120-second budget and reports up to 30 app folders. Folder, log, access-error and size-limit counters explain what was excluded; incomplete sizes are lower bounds.
- Log checks are capped at 300 files and 2 MB per file.
- Unavailable sources remain explicit errors; they are not replaced with invented records.
- Cookie indicators do not prove that recording or cross-site tracking actually occurred.
- Friends, personal interests and chat findings require genuine account exports. A PC scan cannot infer all of these automatically.
- Phone scanning and mobile packaging are not equivalent to unrestricted access to other apps' private data.

## Standalone device scanner

```powershell
New-Item -ItemType Directory -Force .\.cache | Out-Null
& .\.venv\Scripts\python.exe -m scanner.scan --output .\.cache\device_scan.json
```

Add `--seconds 120` for an extended laptop scan. Add `--android` for a connected, authorised ADB device. Install Android platform-tools, enable USB debugging and approve the device prompt first.

## Tests and synthetic fixtures

```powershell
& .\.venv\Scripts\python.exe -m pytest -q tests
```

Latest verified suite: **107 tests passed in 32.82 seconds**. Tests include real OCR on synthetic recordings, parser/rule checks, scanner limits, read-only browser queries and browser-lock shutdown safeguards. Real PC verification also confirmed that the previously blocked Chrome databases became readable after approved background-process shutdown.

Fixture generators:

```powershell
& .\.venv\Scripts\python.exe -m samples.make_persona
& .\.venv\Scripts\python.exe -m samples.make_recordings
& .\.venv\Scripts\python.exe -m samples.make_device
```

Real Android hardware and an actual iPhone privacy export have not been verified in this workspace.

## Local data and publishing

Keep real exports outside `samples/`. Runtime scan results and diagnostics stay in `.cache/`, which is ignored by Git. The repository also ignores `.venv/`, `real-data/`, Python/test caches and generated PDFs. Never add personal exports or scan reports to a public repository.
