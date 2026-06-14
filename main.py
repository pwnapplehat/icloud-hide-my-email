"""
iCloud Hide My Email CLI

Main entry point with CLI interface for:
  1. Generating new Hide My Email addresses
  2. Listing existing HME addresses
  3. Waiting for and extracting OTP codes from incoming emails
  4. Cleaning up (deactivate + delete) HME addresses
  5. Full pipeline: generate email -> wait for OTP

Usage:
  python main.py generate [--count N] [--label LABEL]
  python main.py list [--active-only] [--inactive-only]
  python main.py otp [--email ADDRESS] [--from SENDER] [--timeout SECONDS]
  python main.py cleanup [--email ADDRESS | --all-inactive]
  python main.py pipeline [--count N]
  python main.py test-auth
  python main.py test-imap
"""

import argparse
import asyncio
import csv
import json
import os
import sys
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from icloud_auth import iCloudAuth
from hme_generator import HideMyEmailGenerator
from mail_reader import iCloudMailReader

console = Console()


# ======================================================================
# Utility
# ======================================================================


def ensure_config():
    """Ensure config.json exists, create from example if not."""
    if not os.path.exists("config.json"):
        if os.path.exists("config.example.json"):
            console.print(
                "[yellow]config.json not found. Copying from config.example.json...[/]"
            )
            with open("config.example.json", "r") as f:
                data = json.load(f)
            with open("config.json", "w") as f:
                json.dump(data, f, indent=4)
            console.print(
                "[yellow]Please edit config.json with your actual credentials.[/]"
            )
            return False
        else:
            console.print("[red]No config.json or config.example.json found![/]")
            return False
    return True


def save_emails_to_csv(emails: list, filename: str = "generated_emails.csv"):
    """Append generated emails to a CSV file.

    Args:
        emails: List of email address strings.
        filename: Output CSV file path.
    """
    file_exists = os.path.exists(filename)

    with open(filename, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["email", "created_at", "status"])
        for em in emails:
            writer.writerow([em, datetime.now().isoformat(), "active"])

    console.print(f"[green]Saved {len(emails)} email(s) to {filename}[/]")


def init_auth() -> iCloudAuth:
    """Initialize and validate iCloud authentication.

    Returns:
        Configured iCloudAuth instance.

    Raises:
        SystemExit if authentication fails.
    """
    auth = iCloudAuth()
    ok, msg = auth.initialize()

    if ok:
        console.print(f"[green]{msg}[/]")
    else:
        console.print(f"[red]Authentication failed: {msg}[/]")
        sys.exit(1)

    return auth


# ======================================================================
# Commands
# ======================================================================


async def cmd_generate(args):
    """Generate new Hide My Email address(es)."""
    auth = init_auth()

    count = args.count
    label = args.label or ""
    note = args.note or ""

    console.print(f"\n[bold cyan]Generating {count} Hide My Email address(es)...[/]\n")

    async with HideMyEmailGenerator(auth) as gen:
        if count == 1:
            success, email_addr, error = await gen.create_email(label=label, note=note)
            if success:
                console.print(f"[bold green]Created:[/] {email_addr}")
                save_emails_to_csv([email_addr])
            else:
                console.print(f"[red]Failed: {error}[/]")
        else:
            emails = await gen.create_emails_batch(
                count=count,
                label=label,
                note=note,
                delay=args.delay,
            )
            if emails:
                console.print(f"\n[bold green]Successfully created {len(emails)} email(s):[/]")
                for em in emails:
                    console.print(f"  {em}")
                save_emails_to_csv(emails)
            else:
                console.print("[red]No emails were created. Check cookies and rate limits.[/]")


async def cmd_list(args):
    """List all Hide My Email addresses."""
    auth = init_auth()

    async with HideMyEmailGenerator(auth) as gen:
        console.print("[cyan]Fetching Hide My Email list...[/]\n")
        entries = await gen.get_all_emails()

        if not entries:
            console.print("[yellow]No Hide My Email entries found.[/]")
            return

        # Filter
        if args.active_only:
            entries = [e for e in entries if e.get("isActive")]
        elif args.inactive_only:
            entries = [e for e in entries if not e.get("isActive")]

        # Build table
        table = Table(title=f"Hide My Email Addresses ({len(entries)} entries)")
        table.add_column("#", style="dim", width=5)
        table.add_column("Email", style="cyan")
        table.add_column("Label", style="white")
        table.add_column("Active", style="green")
        table.add_column("Forward To", style="blue")
        table.add_column("Created", style="dim")

        for i, entry in enumerate(entries, 1):
            created = ""
            if "createTimestamp" in entry:
                created = datetime.fromtimestamp(
                    entry["createTimestamp"] / 1000
                ).strftime("%Y-%m-%d %H:%M")

            active_str = "[green]Yes[/]" if entry.get("isActive") else "[red]No[/]"

            table.add_row(
                str(i),
                entry.get("hme", ""),
                entry.get("label", ""),
                active_str,
                entry.get("forwardToEmail", ""),
                created,
            )

        console.print(table)
        console.print(f"\n[dim]Total: {len(entries)} entries[/]")


async def cmd_otp(args):
    """Wait for and extract an OTP code from incoming email."""
    reader = iCloudMailReader()
    ok, msg = reader.connect()

    if not ok:
        console.print(f"[red]IMAP connection failed: {msg}[/]")
        sys.exit(1)

    console.print(f"[green]{msg}[/]")

    hme_address = args.email or ""
    from_address = args.sender or ""
    subject_hint = args.subject or ""
    timeout = args.timeout

    console.print(
        f"\n[cyan]Waiting for OTP email"
        f"{' to ' + hme_address if hme_address else ''}"
        f"{' from ' + from_address if from_address else ''}"
        f" (timeout: {timeout}s)...[/]\n"
    )

    found, otp, error = reader.wait_for_otp(
        hme_address=hme_address,
        from_address=from_address,
        subject_hint=subject_hint,
        timeout_seconds=timeout,
        poll_interval=args.poll_interval,
    )

    if found:
        console.print(Panel(
            f"[bold green]{otp}[/]",
            title="OTP Code Found",
            border_style="green",
        ))
    else:
        console.print(f"[red]No OTP found: {error}[/]")

    reader.disconnect()


async def cmd_cleanup(args):
    """Deactivate and delete HME addresses."""
    auth = init_auth()

    async with HideMyEmailGenerator(auth) as gen:
        entries = await gen.get_all_emails()

        if not entries:
            console.print("[yellow]No entries found.[/]")
            return

        if args.email:
            # Cleanup a specific email
            target = next((e for e in entries if e["hme"] == args.email), None)
            if not target:
                console.print(f"[red]Email {args.email} not found.[/]")
                return

            ok, msg = await gen.cleanup_email(target["anonymousId"])
            icon = "[green]OK[/]" if ok else "[red]FAIL[/]"
            console.print(f"{icon} {args.email}: {msg}")

        elif args.all_inactive:
            # Cleanup all inactive
            inactive = [e for e in entries if not e.get("isActive")]
            console.print(f"[cyan]Deleting {len(inactive)} inactive entries...[/]")

            for entry in inactive:
                ok, msg = await gen.cleanup_email(entry["anonymousId"])
                icon = "[green]OK[/]" if ok else "[red]FAIL[/]"
                console.print(f"  {icon} {entry['hme']}: {msg}")
                await asyncio.sleep(0.5)

        else:
            console.print("[yellow]Specify --email ADDRESS or --all-inactive[/]")


async def cmd_pipeline(args):
    """Full pipeline: generate email, output it, optionally wait for OTP."""
    auth = init_auth()
    count = args.count

    console.print(Panel(
        f"[bold]Generating {count} email(s) + OTP retrieval pipeline[/]",
        title="Pipeline Mode",
        border_style="cyan",
    ))

    async with HideMyEmailGenerator(auth) as gen:
        for i in range(count):
            console.print(f"\n[bold cyan]--- Email {i + 1}/{count} ---[/]")

            # Step 1: Generate
            console.print("[cyan]Step 1: Generating HME address...[/]")
            success, email_addr, error = await gen.create_email()

            if not success:
                console.print(f"[red]Generation failed: {error}[/]")
                continue

            console.print(f"[green]Created: {email_addr}[/]")
            save_emails_to_csv([email_addr])

            # Step 2: Output the email for use
            console.print(
                Panel(
                    f"[bold]{email_addr}[/]",
                    title="Use this email for signup",
                    border_style="green",
                )
            )

            if not args.skip_otp:
                # Step 3: Wait for OTP
                console.print(f"[cyan]Step 2: Waiting for OTP (timeout: {args.timeout}s)...[/]")
                console.print("[dim]Use the email above for signup, then OTP will be captured here.[/]")

                reader = iCloudMailReader()
                ok, msg = reader.connect()

                if ok:
                    found, otp, err = reader.wait_for_otp(
                        hme_address=email_addr,
                        from_address=args.sender or "",
                        timeout_seconds=args.timeout,
                        poll_interval=args.poll_interval,
                    )

                    if found:
                        console.print(Panel(
                            f"[bold green]{otp}[/]",
                            title="OTP Code",
                            border_style="green",
                        ))
                    else:
                        console.print(f"[red]OTP not found: {err}[/]")

                    reader.disconnect()
                else:
                    console.print(f"[red]IMAP connection failed: {msg}[/]")
                    console.print("[yellow]Skipping OTP retrieval.[/]")

            if i < count - 1:
                await asyncio.sleep(args.delay)


async def cmd_test_auth(args):
    """Test iCloud cookie authentication."""
    auth = init_auth()

    console.print("\n[cyan]Testing API access by fetching email list...[/]")

    async with HideMyEmailGenerator(auth) as gen:
        entries = await gen.get_all_emails()

        if entries is not None:
            console.print(
                f"[bold green]Authentication working! "
                f"Found {len(entries)} Hide My Email entries.[/]"
            )
        else:
            console.print("[red]API call failed. Cookies may be expired.[/]")


async def cmd_test_imap(args):
    """Test IMAP connection to iCloud Mail."""
    reader = iCloudMailReader()
    ok, msg = reader.connect()

    if ok:
        console.print(f"[bold green]{msg}[/]")

        console.print("\n[cyan]Fetching latest 5 emails...[/]\n")
        emails = reader.get_latest_emails(count=5)

        if emails:
            table = Table(title="Latest Emails")
            table.add_column("From", style="cyan", max_width=30)
            table.add_column("To", style="blue", max_width=30)
            table.add_column("Subject", style="white", max_width=50)
            table.add_column("Date", style="dim")

            for em in emails:
                table.add_row(
                    em.get("from", "")[:30],
                    em.get("to", "")[:30],
                    em.get("subject", "")[:50],
                    em.get("date", ""),
                )

            console.print(table)
        else:
            console.print("[yellow]No emails found or inbox is empty.[/]")

        reader.disconnect()
    else:
        console.print(f"[red]{msg}[/]")


# ======================================================================
# CLI Parser
# ======================================================================


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="iCloud Hide My Email CLI — generate HME addresses and read OTP mail",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py generate                     # Generate 1 email
  python main.py generate --count 5           # Generate 5 emails
  python main.py list                          # List all HME emails
  python main.py list --active-only            # List only active emails
  python main.py otp --email xyz@icloud.com    # Wait for OTP to specific email
  python main.py otp --sender security@mail.instagram.com  # Filter by sender domain
  python main.py cleanup --email xyz@icloud.com  # Delete specific email
  python main.py pipeline --count 3            # Generate 3 emails with OTP
  python main.py test-auth                     # Test cookie authentication
  python main.py test-imap                     # Test IMAP mail access
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # --- generate ---
    gen_parser = subparsers.add_parser("generate", help="Generate new HME email(s)")
    gen_parser.add_argument("--count", "-n", type=int, default=1, help="Number of emails to generate")
    gen_parser.add_argument("--label", "-l", type=str, default="", help="Label for the email")
    gen_parser.add_argument("--note", type=str, default="", help="Note for the email")
    gen_parser.add_argument("--delay", type=float, default=2.0, help="Delay between generations (seconds)")

    # --- list ---
    list_parser = subparsers.add_parser("list", help="List HME email addresses")
    list_parser.add_argument("--active-only", action="store_true", help="Show only active emails")
    list_parser.add_argument("--inactive-only", action="store_true", help="Show only inactive emails")

    # --- otp ---
    otp_parser = subparsers.add_parser("otp", help="Wait for and extract OTP code")
    otp_parser.add_argument("--email", "-e", type=str, default="", help="HME email to watch")
    otp_parser.add_argument("--sender", "-s", type=str, default="", help="Expected sender address")
    otp_parser.add_argument("--subject", type=str, default="", help="Subject text to match")
    otp_parser.add_argument("--timeout", "-t", type=int, default=120, help="Timeout in seconds")
    otp_parser.add_argument("--poll-interval", type=int, default=5, help="Poll interval in seconds")

    # --- cleanup ---
    cleanup_parser = subparsers.add_parser("cleanup", help="Deactivate and delete HME emails")
    cleanup_parser.add_argument("--email", "-e", type=str, default="", help="Specific email to cleanup")
    cleanup_parser.add_argument("--all-inactive", action="store_true", help="Delete all inactive emails")

    # --- pipeline ---
    pipe_parser = subparsers.add_parser("pipeline", help="Generate email + wait for OTP")
    pipe_parser.add_argument("--count", "-n", type=int, default=1, help="Number of emails")
    pipe_parser.add_argument("--sender", "-s", type=str, default="", help="Expected OTP sender")
    pipe_parser.add_argument("--timeout", "-t", type=int, default=120, help="OTP timeout in seconds")
    pipe_parser.add_argument("--poll-interval", type=int, default=5, help="OTP poll interval")
    pipe_parser.add_argument("--delay", type=float, default=2.0, help="Delay between emails")
    pipe_parser.add_argument("--skip-otp", action="store_true", help="Skip OTP waiting step")

    # --- test-auth ---
    subparsers.add_parser("test-auth", help="Test iCloud authentication")

    # --- test-imap ---
    subparsers.add_parser("test-imap", help="Test IMAP mail connection")

    return parser


# ======================================================================
# Entry Point
# ======================================================================


def main():
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        console.print(
            Panel(
                "[bold white]iCloud Hide My Email CLI[/]\n"
                "[dim]Generate emails, read OTPs, manage HME addresses[/]",
                border_style="blue",
            )
        )
        parser.print_help()
        sys.exit(0)

    console.print(
        Panel(
            "[bold white]iCloud Hide My Email CLI[/]\n"
            "[dim]Generate emails, read OTPs, manage HME addresses[/]",
            border_style="blue",
        )
    )

    if not ensure_config():
        sys.exit(1)

    # Route to command handler
    command_map = {
        "generate": cmd_generate,
        "list": cmd_list,
        "otp": cmd_otp,
        "cleanup": cmd_cleanup,
        "pipeline": cmd_pipeline,
        "test-auth": cmd_test_auth,
        "test-imap": cmd_test_imap,
    }

    handler = command_map.get(args.command)
    if handler:
        asyncio.run(handler(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
