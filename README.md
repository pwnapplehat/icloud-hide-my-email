# icloud-hide-my-email

CLI tool to create and manage **iCloud Hide My Email** addresses and pull verification codes from your inbox over IMAP.

Apple exposes Hide My Email through the icloud.com web app. This project calls the same internal APIs using session cookies from your browser, plus optional IMAP for OTP capture.

## Features

- Generate, list, deactivate, and delete Hide My Email addresses
- Wait for incoming mail and extract OTP / verification codes
- Pipeline mode: create an address and poll for a code in one command
- Cookie-based auth (no Apple API key required for HME)

## Requirements

- Python 3.10+
- Active **iCloud+** subscription (Hide My Email)
- Browser session on [icloud.com](https://www.icloud.com) to export cookies
- App-specific password for IMAP (only if you use `otp` / `pipeline` / `test-imap`)

## Quick start

```shell
git clone https://github.com/YOUR_USERNAME/icloud-hide-my-email.git iCloudMailReverse
cd iCloudMailReverse/icloud-hide-my-email
pip install -r requirements.txt
copy config.example.json config.json
```

Edit `config.json` with your cookies and (optionally) IMAP credentials, then:

```shell
python main.py test-auth
python main.py generate
python main.py list
```

## Configuration

Copy `config.example.json` to `config.json` and fill in:

| Field | Description |
|-------|-------------|
| `icloud_cookie_string` | Full cookie header from icloud.com (see below) |
| `imap_username` | iCloud email prefix only (e.g. `jane` from `jane@icloud.com`) |
| `imap_app_password` | App-specific password from [account.apple.com](https://account.apple.com) |
| `mail_domain_ws_host` | Your HME API host (e.g. `p142-maildomainws.icloud.com`) |
| `client_build_number` | From Network tab query string on HME requests |
| `client_mastering_number` | Same URL, `clientMasteringNumber` parameter |
| `hme_label_prefix` | Label prefix for new addresses |
| `hme_note` | Note stored on new addresses |

**Never commit `config.json`** — it is listed in `.gitignore`.

### Getting cookies

1. Log in at [icloud.com/icloudplus](https://www.icloud.com/icloudplus/) and open **Hide My Email**.
2. Open DevTools → **Network**, trigger a HME action (e.g. add email).
3. Select a request to `maildomainws.icloud.com`.
4. Copy the full **Cookie** request header into `icloud_cookie_string`.
5. From the same request URL, copy `mail_domain_ws_host`, `clientBuildNumber`, and `clientMasteringNumber`.

Required cookies include `X-APPLE-WEBAUTH-USER` and `X-APPLE-WEBAUTH-TOKEN`. Copy the entire header, not individual cookies.

### App-specific password (IMAP)

1. [account.apple.com](https://account.apple.com) → Sign-In and Security → App-Specific Passwords.
2. Generate a password for this tool.
3. Set `imap_app_password` in `config.json`. Username is only the part before `@`.

## Commands

| Command | Description |
|---------|-------------|
| `test-auth` | Verify cookies and HME API access |
| `test-imap` | Verify IMAP login and show recent mail |
| `generate` | Create one or more HME addresses (`--count`, `--label`, `--delay`) |
| `list` | List addresses (`--active-only`, `--inactive-only`) |
| `otp` | Poll inbox for a code (`--email`, `--sender`, `--timeout`) |
| `cleanup` | Deactivate and delete (`--email` or `--all-inactive`) |
| `pipeline` | Generate address then wait for OTP (`--count`, `--skip-otp`) |

### Examples

```shell
python main.py generate --count 5 --label my-app
python main.py otp --email "words-here@icloud.com" --sender mail.example.com --timeout 300
python main.py pipeline --count 3 --sender mail.example.com
python main.py cleanup --all-inactive
```

Generated addresses are appended to `generated_emails.csv` (local only, gitignored).

## API reference (reverse-engineered)

| Action | Method | Endpoint |
|--------|--------|----------|
| Generate | POST | `https://p{N}-maildomainws.icloud.com/v1/hme/generate` |
| Reserve | POST | `https://p{N}-maildomainws.icloud.com/v1/hme/reserve` |
| List | GET | `https://p{N}-maildomainws.icloud.com/v2/hme/list` |
| Deactivate | POST | `https://p{N}-maildomainws.icloud.com/v1/hme/deactivate` |
| Delete | POST | `https://p{N}-maildomainws.icloud.com/v1/hme/delete` |

IMAP: `imap.mail.me.com:993` (SSL).

## Rate limits

- Roughly **5 new addresses per 30 minutes** per family member
- Account cap around **700** Hide My Email addresses
- Session cookies expire; refresh from the browser when auth fails

## Project layout

```
iCloudMailReverse/
└── icloud-hide-my-email/
    ├── main.py              # CLI entry point
    ├── icloud_auth.py       # Cookie loading and validation
    ├── hme_generator.py     # Hide My Email REST client
    ├── mail_reader.py       # IMAP reader and OTP extraction
    ├── config.example.json  # Config template
    ├── requirements.txt
    ├── .gitignore
    └── README.md
```

Local only (not in git): `config.json`, `cookie.txt`, `generated_emails.csv`.

## Troubleshooting

**Authentication failed (401/421)** — Cookies expired or incomplete. Re-export from DevTools.

**Generate failed** — Rate limit or wrong `mail_domain_ws_host`. Wait 30 minutes or fix host/build numbers from Network tab.

**IMAP failed** — Use app-specific password, not your Apple ID password. Username must not include `@icloud.com`.

## Security

- Treat `config.json` like a password file.
- Revoke app-specific passwords you no longer use at account.apple.com.
- HME forwards to your primary iCloud inbox; generated addresses are tied to your account.

## Disclaimer

This tool is not affiliated with Apple. It uses the same web APIs as icloud.com. Use responsibly and in line with Apple's terms of service.
