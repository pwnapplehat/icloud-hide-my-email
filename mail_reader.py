"""
iCloud Mail IMAP Reader Module

Reads incoming emails from iCloud Mail via IMAP to extract OTP codes
and verification messages.

Connection Details (from Apple's official documentation):
  Server: imap.mail.me.com
  Port:   993 (SSL)
  Auth:   Username (without @icloud.com) + App-Specific Password

App-Specific Password Setup:
  1. Go to https://account.apple.com
  2. Sign-In and Security -> App-Specific Passwords
  3. Generate a new password for "Mail Automation"
  4. Use that password in config.json as imap_app_password

The Hide My Email addresses forward to your primary iCloud inbox,
so we read from the main inbox and filter by the X-Apple-Forward-To
header or the To field to match specific HME addresses.
"""

import email
import imaplib
import json
import os
import re
import time
import socket
from email.header import decode_header
from typing import Dict, List, Optional, Tuple


# iCloud IMAP settings
IMAP_HOST = "imap.mail.me.com"
IMAP_PORT = 993

class ProxiedIMAP4_SSL(imaplib.IMAP4_SSL):
    """Subclass of IMAP4_SSL to route connection through a SOCKS5 proxy."""
    
    def __init__(self, host, port, proxy_host, proxy_port, proxy_user=None, proxy_pass=None, **kwargs):
        self.proxy_host = proxy_host
        self.proxy_port = int(proxy_port)
        self.proxy_user = proxy_user
        self.proxy_pass = proxy_pass
        super().__init__(host, port, **kwargs)

    def _create_socket(self, timeout):
        try:
            import socks
        except ImportError:
            raise ImportError("PySocks is required for IMAP proxy support. Install with: pip install PySocks")
            
        sock = socks.socksocket()
        if timeout is not None:
            sock.settimeout(timeout)
        sock.set_proxy(socks.SOCKS5, self.proxy_host, self.proxy_port, True, self.proxy_user, self.proxy_pass)
        sock.connect((self.host, self.port))
        
        # We MUST wrap the socket in SSL context because IMAP4_SSL expects the socket returned
        # by _create_socket to already be an SSL socket
        import ssl
        ssl_context = ssl.create_default_context()
        return ssl_context.wrap_socket(sock, server_hostname=self.host)


class iCloudMailReader:
    """Reads emails from iCloud Mail via IMAP for OTP extraction."""

    def __init__(self, username: str = "", app_password: str = "", config_path: str = "config.json", proxy_url: Optional[str] = None):
        """Initialize the mail reader.

        Args:
            username: iCloud email prefix (without @icloud.com).
            app_password: App-specific password from account.apple.com.
            config_path: Path to config.json file.
            proxy_url: Optional SOCKS5 proxy URL (e.g., socks5://user:pass@host:port)
        """
        self.username = username
        self.app_password = app_password
        self.config_path = config_path
        self.proxy_url = proxy_url
        self.imap: Optional[imaplib.IMAP4_SSL] = None

        if not username or not app_password:
            self._load_from_config()

    def _load_from_config(self):
        """Load IMAP credentials from config.json."""
        if not os.path.exists(self.config_path):
            return

        with open(self.config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        self.username = config.get("imap_username", self.username)
        self.app_password = config.get("imap_app_password", self.app_password)

    def connect(self) -> Tuple[bool, str]:
        """Connect to iCloud IMAP server and authenticate.

        Returns:
            Tuple of (success, message).
        """
        if not self.username or not self.app_password:
            return False, (
                "IMAP credentials not configured. Set imap_username and "
                "imap_app_password in config.json"
            )

        try:
            if self.proxy_url and self.proxy_url.startswith("socks5://"):
                from urllib.parse import urlparse
                parsed = urlparse(self.proxy_url)
                proxy_host = parsed.hostname
                proxy_port = parsed.port or 1080
                proxy_user = parsed.username
                proxy_pass = parsed.password
                
                print(f"[iCloud IMAP] Using SOCKS5 proxy: {proxy_host}:{proxy_port}")
                self.imap = ProxiedIMAP4_SSL(
                    IMAP_HOST, IMAP_PORT,
                    proxy_host=proxy_host,
                    proxy_port=proxy_port,
                    proxy_user=proxy_user,
                    proxy_pass=proxy_pass
                )
            else:
                self.imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
                
            status, data = self.imap.login(self.username, self.app_password)
            if status == "OK":
                return True, f"Connected to iCloud Mail as {self.username}"
            return False, f"Login failed: {data}"
        except imaplib.IMAP4.error as e:
            return False, f"IMAP authentication error: {e}"
        except Exception as e:
            return False, f"Connection error: {e}"

    def disconnect(self):
        """Close IMAP connection."""
        if self.imap:
            try:
                self.imap.close()
            except Exception:
                pass
            try:
                self.imap.logout()
            except Exception:
                pass
            self.imap = None

    def select_inbox(self) -> bool:
        """Select the INBOX folder.

        Returns:
            True if inbox selected successfully.
        """
        if not self.imap:
            return False
        status, _ = self.imap.select("INBOX")
        return status == "OK"

    def search_emails(
        self,
        from_address: str = "",
        to_address: str = "",
        subject_contains: str = "",
        since_hours: int = 1,
        unseen_only: bool = True,
    ) -> List[str]:
        """Search for emails matching criteria.

        Args:
            from_address: Filter by sender address.
            to_address: Filter by recipient (the HME address).
            subject_contains: Filter by subject text.
            since_hours: Only look at emails from the last N hours.
            unseen_only: Only return unread emails.

        Returns:
            List of email message IDs matching the criteria.
        """
        if not self.imap:
            return []

        criteria_parts = []

        if unseen_only:
            criteria_parts.append("UNSEEN")

        if from_address:
            criteria_parts.append(f'FROM "{from_address}"')

        if to_address:
            criteria_parts.append(f'TO "{to_address}"')

        if subject_contains:
            criteria_parts.append(f'SUBJECT "{subject_contains}"')

        if since_hours > 0:
            import datetime
            since_date = datetime.datetime.now() - datetime.timedelta(hours=since_hours)
            date_str = since_date.strftime("%d-%b-%Y")
            criteria_parts.append(f'SINCE {date_str}')

        if not criteria_parts:
            criteria_parts.append("ALL")

        search_str = " ".join(criteria_parts)

        try:
            status, data = self.imap.search(None, f"({search_str})")
            if status == "OK" and data[0]:
                return data[0].split()
            return []
        except Exception:
            return []

    def fetch_email(self, msg_id: bytes) -> Optional[Dict]:
        """Fetch and parse a single email by ID.

        Args:
            msg_id: IMAP message ID.

        Returns:
            Dict with parsed email fields:
            - from: sender address
            - to: recipient address(es)
            - subject: email subject
            - date: email date
            - body_text: plain text body
            - body_html: HTML body
        """
        if not self.imap:
            return None

        try:
            # iCloud IMAP does not support RFC822 fetch - use BODY.PEEK[] instead
            # BODY.PEEK[] fetches the full message without marking it as read
            status, data = self.imap.fetch(msg_id, "(BODY.PEEK[])")
            if status != "OK":
                return None

            # Find the tuple item in the response containing the message bytes
            raw_email = None
            for item in data:
                if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
                    raw_email = item[1]
                    break

            if raw_email is None:
                return None
            msg = email.message_from_bytes(raw_email)

            result = {
                "from": self._decode_header(msg.get("From", "")),
                "to": self._decode_header(msg.get("To", "")),
                "subject": self._decode_header(msg.get("Subject", "")),
                "date": msg.get("Date", ""),
                "body_text": "",
                "body_html": "",
            }

            # Extract body
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition", ""))

                    if "attachment" in content_disposition:
                        continue

                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        try:
                            text = payload.decode(charset, errors="replace")
                        except (LookupError, UnicodeDecodeError):
                            text = payload.decode("utf-8", errors="replace")

                        if content_type == "text/plain":
                            result["body_text"] = text
                        elif content_type == "text/html":
                            result["body_html"] = text
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    try:
                        text = payload.decode(charset, errors="replace")
                    except (LookupError, UnicodeDecodeError):
                        text = payload.decode("utf-8", errors="replace")

                    if msg.get_content_type() == "text/html":
                        result["body_html"] = text
                    else:
                        result["body_text"] = text

            return result
        except Exception:
            return None

    def _decode_header(self, header_value: str) -> str:
        """Decode an email header value that may be encoded.

        Args:
            header_value: Raw header string.

        Returns:
            Decoded string.
        """
        if not header_value:
            return ""

        decoded_parts = decode_header(header_value)
        result = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                result.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                result.append(part)
        return " ".join(result)

    # ------------------------------------------------------------------
    # OTP Extraction
    # ------------------------------------------------------------------

    def extract_otp_from_text(self, text: str) -> Optional[str]:
        """Extract an OTP/verification code from email text.

        Looks for common OTP patterns:
        - 4-8 digit codes
        - "your code is XXXXXX"
        - "verification code: XXXXXX"
        - Generic verification / OTP patterns

        Args:
            text: Email body text.

        Returns:
            The extracted OTP code or None.
        """
        if not text:
            return None

        # Service-specific patterns (most specific first)
        patterns = [
            # "XXXXXX is your Instagram code"
            r"(\d{6})\s+is\s+your\s+Instagram\s+code",
            # "your Instagram code is XXXXXX"
            r"your\s+Instagram\s+code\s+is\s+(\d{6})",
            # "Use XXXXXX to verify"
            r"[Uu]se\s+(\d{6})\s+to\s+verify",
            # "verification code is XXXXXX"
            r"verification\s+code\s+(?:is\s+)?[:\s]*(\d{4,8})",
            # "your code is XXXXXX"
            r"your\s+code\s+(?:is\s+)?[:\s]*(\d{4,8})",
            # "code: XXXXXX"
            r"code[:\s]+(\d{4,8})",
            # "PIN: XXXXXX"
            r"PIN[:\s]+(\d{4,8})",
            # Generic: standalone 6-digit number (common for OTPs)
            r"(?<!\d)(\d{6})(?!\d)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    def extract_otp_from_html(self, html: str) -> Optional[str]:
        """Extract OTP from HTML email body.

        Strips HTML tags first, then applies OTP extraction.

        Args:
            html: HTML email body.

        Returns:
            The extracted OTP code or None.
        """
        if not html:
            return None

        # Strip HTML tags
        clean = re.sub(r"<[^>]+>", " ", html)
        # Normalize whitespace
        clean = re.sub(r"\s+", " ", clean).strip()
        return self.extract_otp_from_text(clean)

    # ------------------------------------------------------------------
    # High-Level Operations
    # ------------------------------------------------------------------

    def wait_for_otp(
        self,
        hme_address: str = "",
        from_address: str = "",
        subject_hint: str = "",
        timeout_seconds: int = 120,
        poll_interval: int = 5,
        unseen_only: bool = False,  # Changed default to False to catch all recent emails
    ) -> Tuple[bool, str, str]:
        """Wait for an OTP email to arrive and extract the code.

        Polls the inbox at regular intervals looking for a matching email.

        Args:
            hme_address: The HME email address to look for (in To field).
            from_address: Expected sender (e.g., "security@mail.instagram.com").
            subject_hint: Text expected in subject line.
            timeout_seconds: Max seconds to wait before giving up.
            poll_interval: Seconds between each inbox check.

        Returns:
            Tuple of (found, otp_code, error_message).
        """
        if not self.imap:
            ok, msg = self.connect()
            if not ok:
                return False, "", msg

        if not self.select_inbox():
            return False, "", "Failed to select INBOX"

        start_time = time.time()

        while time.time() - start_time < timeout_seconds:
            # Search for matching emails
            # NOTE: since_hours=24 because IMAP SINCE is date-only and exclusive
            # (emails from "today" require SINCE "yesterday")
            msg_ids = self.search_emails(
                from_address=from_address,
                to_address=hme_address,
                subject_contains=subject_hint,
                since_hours=24,  # Changed from 1 - IMAP SINCE uses date granularity only
                unseen_only=unseen_only,
            )

            if msg_ids:
                # Check the most recent email first (last in list)
                for msg_id in reversed(msg_ids):
                    email_data = self.fetch_email(msg_id)
                    if not email_data:
                        continue

                    subject_lower = email_data.get("subject", "").lower()
                    body_text_lower = email_data.get("body_text", "").lower()
                    body_html_lower = email_data.get("body_html", "").lower()

                    if subject_hint and subject_hint.lower() not in subject_lower:
                        continue

                    # Try extracting OTP from text body first, then HTML
                    otp = self.extract_otp_from_text(email_data["body_text"])
                    if not otp:
                        otp = self.extract_otp_from_html(email_data["body_html"])

                    if otp:
                        return True, otp, ""

            # Re-select inbox to refresh (required by some IMAP servers)
            self.select_inbox()
            time.sleep(poll_interval)

        return False, "", f"Timed out after {timeout_seconds}s waiting for OTP"

    def get_latest_emails(self, count: int = 10) -> List[Dict]:
        """Get the latest N emails from inbox.

        Args:
            count: Number of recent emails to fetch.

        Returns:
            List of parsed email dicts.
        """
        if not self.imap:
            ok, msg = self.connect()
            if not ok:
                return []

        if not self.select_inbox():
            return []

        try:
            status, data = self.imap.search(None, "ALL")
            if status != "OK" or not data[0]:
                return []

            msg_ids = data[0].split()
            # Take the last N (newest by sequence number) and reverse for newest-first
            recent_ids = list(reversed(msg_ids[-count:]))

            emails = []
            for msg_id in recent_ids:
                email_data = self.fetch_email(msg_id)
                if email_data:
                    emails.append(email_data)

            return emails
        except Exception:
            return []
