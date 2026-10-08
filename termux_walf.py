#!/usr/bin/env python3
"""Interactive WALF runner for Termux with manual Windscribe Android switching."""

import argparse
import csv
import datetime
import os
from pathlib import Path
import sqlite3
import sys
import time

import speedtest


DB_HEADERS = (
    "id", "location", "city", "country", "protocol", "port", "status",
    "duration", "ping", "download", "upload", "profile_name", "timestamp",
)


def canonical_country_name(value):
    country = (value or "").strip()
    normalized = country.lower()
    if normalized in {"us", "usa", "united states"} or normalized.startswith(
        ("us ", "united states ")
    ):
        return "United States"
    if normalized == "canada" or normalized.startswith("canada "):
        return "Canada"
    return country


def load_locations(csv_path):
    locations = []
    with open(csv_path, mode="r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file, skipinitialspace=True)
        required_columns = {"Location", "City", "Region"}
        if not reader.fieldnames or not required_columns.issubset(reader.fieldnames):
            raise ValueError(
                "The location CSV must include Location, City, and Region columns."
            )
        for row in reader:
            location = (row.get("Location") or "").strip()
            city = (row.get("City") or "").strip()
            country = canonical_country_name(row.get("Region") or "")
            if location and city and country:
                locations.append(
                    {"location": location, "city": city, "country": country}
                )
    if not locations:
        raise ValueError("The location CSV contains no usable server rows.")
    return locations


def open_database(db_path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path))
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            location TEXT,
            city TEXT,
            country TEXT,
            protocol TEXT,
            port INTEGER,
            status TEXT,
            duration REAL,
            ping REAL,
            download REAL,
            upload REAL,
            profile_name TEXT,
            timestamp TEXT,
            UNIQUE(location, city, country, protocol, port)
        )
        """
    )
    connection.commit()
    return connection


def record_result(connection, location, protocol, port, status, duration,
                  ping, download, upload, profile_name):
    connection.execute(
        """
        INSERT OR REPLACE INTO tests
        (location, city, country, protocol, port, status, duration, ping,
         download, upload, profile_name, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            location["location"],
            location["city"],
            location["country"],
            protocol,
            port,
            status,
            round(duration, 2),
            ping,
            download,
            upload,
            profile_name,
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    connection.commit()


def export_report(connection, output_path):
    output_path = Path(output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cursor = connection.execute(
        """
        SELECT id, location, city, country, protocol, port, status, duration,
               ping, download, upload, profile_name, timestamp
        FROM tests ORDER BY id
        """
    )
    with output_path.open("w", newline="", encoding="utf-8-sig") as report_file:
        writer = csv.writer(report_file)
        writer.writerow(DB_HEADERS)
        writer.writerows(cursor.fetchall())
    return output_path


class TermuxWALF:
    def __init__(self, csv_path, data_dir):
        self.locations = load_locations(csv_path)
        self.data_dir = Path(data_dir).expanduser()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.connection = open_database(self.data_dir / "windscribe_results.db")
        self.reports_dir = self.data_dir / "reports"

    @staticmethod
    def ask(prompt):
        return input(prompt).strip()

    def choose(self, title, options, allow_all=False):
        options = list(options)
        print(f"\n{title}")
        if allow_all:
            print("  0) All")
        for index, option in enumerate(options, start=1):
            print(f"  {index}) {option}")
        while True:
            answer = self.ask("Number: ")
            if allow_all and answer == "0":
                return None
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return options[int(answer) - 1]
            print("Please enter one of the listed numbers.")

    def select_locations(self):
        countries = sorted({row["country"] for row in self.locations})
        country = self.choose("Choose a country", countries, allow_all=True)
        rows = self.locations
        if country:
            rows = [row for row in rows if row["country"] == country]

        cities = sorted({row["city"] for row in rows})
        city = self.choose("Choose a city", cities, allow_all=True)
        if city:
            rows = [row for row in rows if row["city"] == city]

        servers = sorted({row["location"] for row in rows})
        server = self.choose("Choose a server", servers, allow_all=True)
        if server:
            rows = [row for row in rows if row["location"] == server]
        return rows

    def ask_yes_no(self, prompt, default=False):
        suffix = "Y/n" if default else "y/N"
        while True:
            answer = self.ask(f"{prompt} [{suffix}]: ").lower()
            if not answer:
                return default
            if answer in {"y", "yes"}:
                return True
            if answer in {"n", "no"}:
                return False
            print("Please answer y or n.")

    def measure(self, test_ping, test_download, test_upload):
        ping = download = upload = 0.0
        if not (test_ping or test_download or test_upload):
            return ping, download, upload
        try:
            tester = speedtest.Speedtest()
            tester.get_best_server()
            if test_ping:
                ping = float(tester.results.ping)
                print(f"Ping: {ping:.0f} ms")
            if test_download:
                download = tester.download() / 1_000_000
                print(f"Download: {download:.1f} Mbps")
            if test_upload:
                upload = tester.upload() / 1_000_000
                print(f"Upload: {upload:.1f} Mbps")
        except Exception as error:
            print(f"Speed test failed: {error}")
        return ping, download, upload

    def run_session(self):
        selected_locations = self.select_locations()
        if not selected_locations:
            print("No locations matched the selection.")
            return
        print(f"\nSelected {len(selected_locations)} server(s).")
        if len(selected_locations) > 10 and not self.ask_yes_no(
            "This will require manual switching for many servers. Continue?"
        ):
            return

        test_ping = self.ask_yes_no("Measure ping?")
        test_download = self.ask_yes_no("Measure download speed?")
        test_upload = self.ask_yes_no("Measure upload speed?")
        profile_name = self.ask("Profile name [Termux]: ") or "Termux"
        completed = 0

        for index, location in enumerate(selected_locations, start=1):
            print(
                f"\n[{index}/{len(selected_locations)}] "
                f"{location['location']} — {location['city']}, {location['country']}"
            )
            while True:
                protocol = self.ask(
                    "Protocol label exactly as shown in Windscribe Android [Auto]: "
                ).lower() or "auto"
                if all(character.isalnum() or character in "-_ " for character in protocol):
                    break
                print("Use letters, numbers, spaces, hyphens, or underscores only.")
            port_text = self.ask(
                "Port for report metadata (optional; configure it in Windscribe if supported): "
            )
            if port_text:
                try:
                    port = int(port_text)
                    if not 1 <= port <= 65535:
                        raise ValueError
                except ValueError:
                    print("Invalid port; this result will use an empty port field.")
                    port = None
            else:
                port = None

            print(
                f"\nOpen Windscribe on Android and connect to {location['location']} "
                f"using {protocol.upper()}."
            )
            print("The connection is not changed or verified automatically by Termux.")
            started = time.monotonic()
            while True:
                action = self.ask(
                    "Press Enter after you confirm connection, 'f' for failed, "
                    "'s' to skip, or 'q' to stop: "
                ).lower()
                if action in {"", "f", "s", "q"}:
                    break
                print("Please press Enter, or type f, s, or q.")
            duration = time.monotonic() - started

            if action == "q":
                break
            if action == "s":
                continue

            status = "SUCCESS" if action == "" else "FAILURE"
            result_location = dict(location)
            ping = download = upload = 0.0
            if status == "SUCCESS":
                actual_server = self.ask(
                    "Server/location label shown in the Android app "
                    f"(blank to use {location['location']}): "
                )
                if actual_server:
                    result_location["location"] = actual_server
                print(
                    "Recorded as successful based on your confirmation; "
                    "the VPN state itself is not verified."
                )
                ping, download, upload = self.measure(
                    test_ping, test_download, test_upload
                )

            record_result(
                self.connection, result_location, protocol, port, status,
                duration, ping, download, upload, profile_name
            )
            completed += 1

        print(f"\nSession finished. {completed} result(s) recorded.")
        print(
            "The saved duration includes manual app switching and confirmation; "
            "it is not an automatic VPN connection-time measurement."
        )
        print(f"Database: {self.data_dir / 'windscribe_results.db'}")

    def show_recent_results(self):
        rows = self.connection.execute(
            """
            SELECT location, city, country, protocol, port, status, ping,
                   download, upload, timestamp
            FROM tests ORDER BY id DESC LIMIT 20
            """
        ).fetchall()
        if not rows:
            print("There are no saved results yet.")
            return
        print("\nRecent results:")
        for row in rows:
            location, city, country, protocol, port, status, ping, down, up, stamp = row
            port_label = f":{port}" if port is not None else ""
            ping = ping or 0
            down = down or 0
            up = up or 0
            print(
                f"{stamp} | {location} ({city}, {country}) | "
                f"{protocol}{port_label} | {status} | "
                f"Ping {ping:g} ms | Down {down:g} Mbps | Up {up:g} Mbps"
            )

    def run(self):
        while True:
            print("\nWALF for Termux")
            print("1) Start a manual server test session")
            print("2) Show recent results")
            print("3) Export CSV report")
            print("0) Exit")
            choice = self.ask("Select: ")
            if choice == "1":
                self.run_session()
            elif choice == "2":
                self.show_recent_results()
            elif choice == "3":
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                output = self.reports_dir / f"termux_{timestamp}.csv"
                print(f"Report saved: {export_report(self.connection, output)}")
            elif choice == "0":
                return
            else:
                print("Please choose 0, 1, 2, or 3.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    app_dir = Path(__file__).resolve().parent
    parser.add_argument(
        "--csv",
        dest="csv_path",
        default=str(app_dir / "cities_extended.csv"),
        help="Path to cities_extended.csv",
    )
    parser.add_argument(
        "--data-dir",
        default=os.path.join(os.path.expanduser("~"), ".walf"),
        help="Directory for database and exported reports",
    )
    args = parser.parse_args()
    app = None
    try:
        app = TermuxWALF(args.csv_path, args.data_dir)
        app.run()
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f"WALF could not start: {error}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nExiting WALF.")
    finally:
        if app is not None:
            app.connection.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
