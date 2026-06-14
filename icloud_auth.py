"""
iCloud Authentication & Cookie Management Module

Handles loading, parsing, and validating iCloud session cookies
required for Hide My Email API access.

The iCloud web API does NOT use traditional API keys.
Instead, it uses session cookies from an authenticated icloud.com browser session.

Required cookies:
  - X-APPLE-WEBAUTH-USER    -> Contains the DSID (Directory Services ID)
  - X-APPLE-WEBAUTH-TOKEN   -> Auth token
  - X-APPLE-DS-WEB-SESSION-TOKEN -> Session token

These cookies can be extracted from your browser after logging into icloud.com.
"""

import json
import os
import re
from typing import Dict, Optional, Tuple


# Cookies that MUST be present for API access
REQUIRED_COOKIE_NAMES = [
    "X-APPLE-WEBAUTH-USER",
    "X-APPLE-WEBAUTH-TOKEN",
]

# Additional cookies that improve session stability
OPTIONAL_COOKIE_NAMES = [
    "X-APPLE-DS-WEB-SESSION-TOKEN",
    "X-APPLE-WEBAUTH-HSA-TRUST",
    "X-APPLE-WEBAUTH-HSA-TRUST-CDN",
    "X-APPLE-WEBAUTH-HSA-LOGIN",
]


class iCloudAuth:
    """Manages iCloud authentication via session cookies."""

    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.config: Dict = {}
        self.cookie_string: str = ""
        self.cookie_dict: Dict[str, str] = {}
        self.dsid: str = ""
        self.host: str = "p68-maildomainws.icloud.com"
        self.client_build_number: str = "2542Project45"
        self.client_mastering_number: str = "2542B32"

    def load_config(self) -> bool:
        """Load configuration from config.json file.

        Returns:
            True if config loaded successfully, False otherwise.
        """
        if not os.path.exists(self.config_path):
            return False

        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        self.cookie_string = self.config.get("icloud_cookie_string", "")
        self.host = self.config.get("mail_domain_ws_host", self.host)
        self.client_build_number = self.config.get(
            "client_build_number", self.client_build_number
        )
        self.client_mastering_number = self.config.get(
            "client_mastering_number", self.client_mastering_number
        )
        return True

    def load_cookie_file(self, cookie_file: str = "cookie.txt") -> bool:
        """Load cookies from a plain-text cookie file (semicolon-separated name=value pairs).

        Args:
            cookie_file: Path to the cookie file.

        Returns:
            True if cookies loaded successfully, False otherwise.
        """
        if not os.path.exists(cookie_file):
            return False

        with open(cookie_file, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip() and not line.startswith("//")]

        if lines:
            self.cookie_string = lines[0]
            return True
        return False

    def parse_cookies(self) -> bool:
        """Parse the cookie string into a dictionary and extract DSID.

        Returns:
            True if cookies parsed and DSID extracted, False otherwise.
        """
        if not self.cookie_string:
            return False

        self.cookie_dict = {}
        # Handle both semicolon-separated and newline-separated formats
        raw = self.cookie_string.replace("\n", ";")
        pairs = raw.split(";")

        for pair in pairs:
            pair = pair.strip()
            if "=" in pair:
                idx = pair.index("=")
                name = pair[:idx].strip()
                value = pair[idx + 1 :].strip()
                if name:
                    self.cookie_dict[name] = value

        # Extract DSID from X-APPLE-WEBAUTH-USER cookie
        dsid = self._extract_dsid()
        if dsid:
            self.dsid = dsid
            return True
        return False

    def _extract_dsid(self) -> Optional[str]:
        """Extract the DSID (Directory Services Identifier) from the auth cookie.

        The DSID is embedded in X-APPLE-WEBAUTH-USER cookie in format:
            "v=1:s=0:d=YOUR_DSID"

        Returns:
            The DSID string or None if not found.
        """
        user_cookie = self.cookie_dict.get("X-APPLE-WEBAUTH-USER", "")
        if not user_cookie:
            return None

        # Try d=DSID pattern
        match = re.search(r"d=(\d+)", user_cookie)
        if match:
            return match.group(1)

        # Try extracting from quoted value
        cleaned = user_cookie.strip('"').strip("'")
        match = re.search(r"d=(\d+)", cleaned)
        if match:
            return match.group(1)

        return None

    def validate_cookies(self) -> Tuple[bool, str]:
        """Validate that all required cookies are present.

        Returns:
            Tuple of (is_valid, error_message).
        """
        if not self.cookie_dict:
            return False, "No cookies loaded. Run parse_cookies() first."

        missing = []
        for name in REQUIRED_COOKIE_NAMES:
            if name not in self.cookie_dict:
                missing.append(name)

        if missing:
            return False, f"Missing required cookies: {', '.join(missing)}"

        if not self.dsid:
            return False, "Could not extract DSID from X-APPLE-WEBAUTH-USER cookie."

        return True, "Cookies valid."

    def get_cookie_header_string(self) -> str:
        """Build a cookie header string from the parsed dictionary.

        Returns:
            Semicolon-separated cookie string for HTTP headers.
        """
        if self.cookie_string:
            return self.cookie_string.strip()
        return "; ".join(f"{k}={v}" for k, v in self.cookie_dict.items())

    def get_api_params(self) -> Dict[str, str]:
        """Build the query parameters needed by all iCloud HME API calls.

        Returns:
            Dict with clientBuildNumber, clientMasteringNumber, clientId, dsid.
        """
        return {
            "clientBuildNumber": self.client_build_number,
            "clientMasteringNumber": self.client_mastering_number,
            "clientId": "icloud-hide-my-email",
            "dsid": self.dsid,
        }

    def get_base_headers(self) -> Dict[str, str]:
        """Build the HTTP headers needed for iCloud API requests.

        Returns:
            Dict of HTTP headers including Cookie.
        """
        return {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "text/plain",
            "Origin": "https://www.icloud.com",
            "Referer": "https://www.icloud.com/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "sec-ch-ua": '"Chromium";v="131", "Google Chrome";v="131", "Not?A_Brand";v="8"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Cookie": self.get_cookie_header_string(),
        }

    def initialize(self) -> Tuple[bool, str]:
        """Full initialization: load config, parse cookies, validate.

        Tries config.json first, then falls back to cookie.txt.

        Returns:
            Tuple of (success, message).
        """
        # Try loading from config.json
        if self.load_config() and self.cookie_string:
            if self.parse_cookies():
                valid, msg = self.validate_cookies()
                if valid:
                    return True, f"Authenticated via config.json. DSID: {self.dsid}"
                return False, msg

        # Fallback to cookie.txt
        if self.load_cookie_file():
            if self.parse_cookies():
                valid, msg = self.validate_cookies()
                if valid:
                    return True, f"Authenticated via cookie.txt. DSID: {self.dsid}"
                return False, msg

        return False, (
            "No valid cookies found. Please either:\n"
            "  1) Add your cookie string to config.json under 'icloud_cookie_string'\n"
            "  2) Create a cookie.txt file with your iCloud cookie string\n"
            "\n"
            "To get cookies:\n"
            "  - Log in to https://www.icloud.com\n"
            "  - Open DevTools (F12) -> Application -> Cookies\n"
            "  - Copy all cookie name=value pairs separated by semicolons"
        )
