import os
import sys
import shutil
from pathlib import Path

# PyInstaller --noconsole stream redirect fix
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import sqlite3
import csv
import subprocess
import time
import datetime
import threading
import platform
import json
import speedtest
import random

# --- Configuration ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")
ctk.set_widget_scaling(1.0)
ctk.set_window_scaling(1.0)

BASE_DIR = Path(__file__).resolve().parent if Path(__file__).resolve().parent.exists() else Path.cwd()


def resolve_asset_path(filename: str) -> str:
    return str((BASE_DIR / filename).resolve())


def canonical_country_name(value: str) -> str:
    country = (value or "").strip()
    normalized = country.lower()
    if normalized in {"us", "usa", "united states"} or normalized.startswith(("us ", "united states ")):
        return "United States"
    if normalized == "canada" or normalized.startswith("canada "):
        return "Canada"
    return country


COUNTRY_FLAG_CODES = {
    "Albania": "AL", "Argentina": "AR", "Australia": "AU", "Austria": "AT",
    "Belgium": "BE", "Bosnia": "BA", "Brazil": "BR", "Bulgaria": "BG",
    "Canada": "CA", "Chile": "CL", "Colombia": "CO", "Croatia": "HR",
    "Cyprus": "CY", "Czech Republic": "CZ", "Denmark": "DK", "Ecuador": "EC",
    "El Salvador": "SV", "Estonia": "EE", "Fake Antarctica": "AQ", "Finland": "FI",
    "France": "FR", "Georgia": "GE", "Germany": "DE", "Greece": "GR",
    "Guatemala": "GT", "Hong Kong": "HK", "Hungary": "HU", "Iceland": "IS",
    "India": "IN", "Indonesia": "ID", "Ireland": "IE", "Israel": "IL",
    "Italy": "IT", "Japan": "JP", "Kenya": "KE", "Latvia": "LV",
    "Lithuania": "LT", "Luxembourg": "LU", "Malaysia": "MY", "Mexico": "MX",
    "Moldova": "MD", "Netherlands": "NL", "New Zealand": "NZ", "Nigeria": "NG",
    "North Macedonia": "MK", "Norway": "NO", "Panama": "PA", "Paraguay": "PY",
    "Peru": "PE", "Philippines": "PH", "Poland": "PL", "Portugal": "PT",
    "Romania": "RO", "Russia": "RU", "Serbia": "RS", "Singapore": "SG",
    "Slovakia": "SK", "Slovenia": "SI", "South Africa": "ZA", "South Korea": "KR",
    "Spain": "ES", "Sweden": "SE", "Switzerland": "CH", "Taiwan": "TW",
    "Thailand": "TH", "Turkey": "TR", "Ukraine": "UA", "United Arab Emirates": "AE",
    "United Kingdom": "GB", "United States": "US", "Vietnam": "VN",
}


def country_flag(country: str) -> str:
    if country == "All":
        return "\U0001f310"
    if country == "Fake Antarctica":
        return "\U0001f9ca"
    code = COUNTRY_FLAG_CODES.get(country)
    if not code:
        return "\U0001f3f3\ufe0f"
    return "".join(chr(127397 + ord(letter)) for letter in code)


def find_windscribe_cli() -> str:
    candidates = []
    if platform.system() == "Windows":
        candidates.extend([
            r"C:\Program Files\Windscribe\windscribe-cli.exe",
            r"C:\Program Files (x86)\Windscribe\windscribe-cli.exe",
        ])
    else:
        candidates.extend(["windscribe-cli", "windscribe"])

    resolved = shutil.which("windscribe-cli") or shutil.which("windscribe")
    if resolved:
        return resolved

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate

    return candidates[0] if candidates else "windscribe-cli"

DEFAULT_PROTOCOLS = {
    "wireguard": [443, 80, 53, 123, 1194, 65142],
    "ikev2": [500],
    "udp": [443, 80, 53, 123, 1194, 54783],
    "tcp": [443, 587, 21, 22, 80, 123, 143, 3306, 8080, 54783, 1194],
    "stealth": [443, 587, 21, 22, 80, 123, 143, 3306, 8080, 54783, 8443],
    "wstunnel": [443]
}

if getattr(sys, 'frozen', False):
    APP_PATH = str(Path(sys.executable).resolve().parent)
else:
    APP_PATH = str(BASE_DIR)

DB_FILE = resolve_asset_path("windscribe_results.db")
CONFIG_FILE = resolve_asset_path("config.json")
CSV_FILE = resolve_asset_path("cities_extended.csv")
MAX_VISIBLE_LOG_LINES = 5000
RETAINED_LOG_LINES = 4000


# --- Config Manager ---
class ConfigManager:
    @staticmethod
    def load_config():
        default_data = {
            "saved_profiles": {},
            "last_settings": {
                "timeout": "25",
                "speed_wait": "5",
                "test_ping": False,
                "test_down": False,
                "test_up": False,
                "filter_country": "All",
                "filter_city": "All",
                "filter_location": "All",
                "random_cities": False,
                "chaos_mode": False,
                "stop_on_success": False,
                "anti_censorship": False,
                "priority_order": list(DEFAULT_PROTOCOLS.keys()),
                "protocols": {}
            }
        }
        for proto, ports in DEFAULT_PROTOCOLS.items():
            default_data["last_settings"]["protocols"][proto] = {"enabled": True,
                                                                 "ports": {str(p): True for p in ports}}

        if not os.path.exists(CONFIG_FILE):
            return default_data

        try:
            with open(CONFIG_FILE, 'r') as f:
                loaded = json.load(f)
                if "saved_profiles" not in loaded: loaded["saved_profiles"] = {}
                if "last_settings" not in loaded: loaded["last_settings"] = default_data["last_settings"]
                # Ensure new keys exist
                ls = loaded["last_settings"]
                if "filter_location" not in ls: ls["filter_location"] = "All"
                if "filter_country" not in ls:
                    ls["filter_country"] = "All"
                if "random_cities" not in ls: ls["random_cities"] = False
                if "chaos_mode" not in ls: ls["chaos_mode"] = False
                if "stop_on_success" not in ls: ls["stop_on_success"] = False
                if "anti_censorship" not in ls: ls["anti_censorship"] = False
                if "priority_order" not in ls: ls["priority_order"] = list(DEFAULT_PROTOCOLS.keys())
                if "protocols" not in ls: ls["protocols"] = {}
                for proto, ports in DEFAULT_PROTOCOLS.items():
                    proto_cfg = ls["protocols"].get(proto, {})
                    if "enabled" not in proto_cfg:
                        proto_cfg["enabled"] = True
                    if "ports" not in proto_cfg:
                        proto_cfg["ports"] = {}
                    for port in ports:
                        proto_cfg["ports"].setdefault(str(port), True)
                return loaded
        except Exception as e:
            print(f"Config Load Error: {e}")
            return default_data

    @staticmethod
    def save_config(data):
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Config Save Error: {e}")


# --- Database Manager ---
class DatabaseManager:
    def __init__(self, app=None):
        self.app = app
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_table()

    def create_table(self):
        self.cursor.execute('''
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
        ''')
        self.conn.commit()

        try:
            self.cursor.execute("SELECT profile_name FROM tests LIMIT 1")
        except:
            if self.app: self.app.log_message("[DB] Migrating table columns...", "WARN")
            try:
                self.cursor.execute("ALTER TABLE tests ADD COLUMN profile_name TEXT")
            except:
                pass
            try:
                self.cursor.execute("ALTER TABLE tests RENAME COLUMN location_nickname TO location")
            except:
                pass
            try:
                self.cursor.execute("ALTER TABLE tests RENAME COLUMN region TO country")
            except:
                pass
            self.conn.commit()

    def record_result(self, location, city, country, proto, port, status, duration, ping, down, up, profile_name):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            duration = round(duration, 2)
            self.cursor.execute('''
                INSERT OR REPLACE INTO tests
                (location, city, country, protocol, port, status, duration, ping, download, upload, profile_name, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (location, city, country, proto, port, status, duration, ping, down, up, profile_name, timestamp))
            self.conn.commit()
            return True
        except Exception as e:
            if self.app: self.app.log_message(f"DB ERROR: {e}", "FAILURE")
            return False

    def get_row_count(self):
        try:
            self.cursor.execute("SELECT COUNT(*) FROM tests")
            return self.cursor.fetchone()[0]
        except:
            return 0

    def is_tested(self, location, city, country, proto, port):
        self.cursor.execute(
            "SELECT 1 FROM tests WHERE location=? AND city=? AND country=? AND protocol=? AND port=?",
            (location, city, country, proto, port))
        return self.cursor.fetchone() is not None

    def get_tested_keys(self):
        self.cursor.execute(
            "SELECT location, city, country, protocol, port FROM tests"
        )
        return set(self.cursor.fetchall())

    def export_to_csv(self, current_profile_name="Manual", output_path=None):
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_profile = "".join(
            [c for c in current_profile_name if c.isalnum() or c in (' ', '-', '_')]).strip().replace(' ', '_')
        if not safe_profile: safe_profile = "Manual"

        if output_path is None:
            reports_dir = os.path.join(APP_PATH, "reports")
            try:
                os.makedirs(reports_dir, exist_ok=True)
                existing_files = os.listdir(reports_dir)
            except OSError as e:
                return -1, f"Failed to access reports directory: {e}"

            max_id = 0
            for filename in existing_files:
                if filename.endswith(".csv"):
                    parts = filename.split('_')
                    if parts and parts[0].isdigit():
                        max_id = max(max_id, int(parts[0]))
            output_path = os.path.join(
                reports_dir, f"{max_id + 1}_{safe_profile}_{ts}.csv")

        self.cursor.execute("SELECT * FROM tests")
        rows = self.cursor.fetchall()
        headers = [description[0] for description in self.cursor.description]

        try:
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(rows)
            return len(rows), output_path
        except OSError as e:
            return -1, f"Could not write report: {e}"

    def clear_db(self):
        self.cursor.execute("DELETE FROM tests")
        self.conn.commit()


# --- Logic Worker ---
class WindscribeWorker:
    def __init__(self, app_instance):
        self.app = app_instance
        self.db = DatabaseManager(app=app_instance)
        self.stop_event = threading.Event()
        self.cli_cmd = find_windscribe_cli()

    def log(self, msg, tag="INFO"):
        self.app.log_message(msg, tag)

    def update_dashboard(self, ping="-", down="-", up="-", status="Idle", progress=0.0):
        count = self.db.get_row_count()
        self.app.update_live_dashboard(ping, down, up, status, progress, count)

    def run_cli(self, args):
        cmd = [self.cli_cmd] + args
        try:
            startupinfo = None
            if platform.system() == "Windows":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                    startupinfo=startupinfo)
            return result.returncode, result.stdout
        except Exception as e:
            self.log(f"CLI Error: {e}", "FAILURE")
            return -1, ""

    def get_protocol_ports(self):
        ports_by_protocol = {}
        for protocol in DEFAULT_PROTOCOLS:
            code, output = self.run_cli(["ports", protocol])
            if code != 0:
                raise RuntimeError(
                    f"Windscribe CLI could not list {protocol} ports: "
                    f"{output.strip() or 'unknown error'}"
                )
            try:
                ports = sorted({
                    int(value.strip())
                    for value in output.replace("\n", ",").split(",")
                    if value.strip()
                })
            except ValueError as error:
                raise RuntimeError(
                    f"Windscribe CLI returned an invalid port list for {protocol}: {output.strip()}"
                ) from error
            if not ports or any(port < 1 or port > 65535 for port in ports):
                raise RuntimeError(
                    f"Windscribe CLI returned no valid ports for {protocol}: "
                    f"{output.strip() or 'empty response'}"
                )
            ports_by_protocol[protocol] = ports
        return ports_by_protocol

    def ensure_disconnected(self):
        # IMPROVED DISCONNECT LOGIC
        max_retries = 5
        for i in range(max_retries):
            code, out = self.run_cli(["status"])
            if "DISCONNECTED" in out.upper():
                return True

            # Attempt to force firewall off and disconnect
            self.run_cli(["firewall", "off"])
            self.run_cli(["disconnect"])
            time.sleep(3)  # Wait for CLI to process

        # Final Check
        code, out = self.run_cli(["status"])
        return "DISCONNECTED" in out.upper()

    def wait_for_connection(self, start_time, timeout):
        while time.time() - start_time < timeout:
            code, out = self.run_cli(["status"])
            if "CONNECTED" in out.upper() and "DISCONNECTED" not in out.upper():
                if "CONNECTING" not in out.upper():
                    duration = time.time() - start_time
                    return True, duration
            time.sleep(1)
            if self.stop_event.is_set(): return False, 0.0
        return False, 0.0

    def start(self, work_plan, resume, timeout, speed_wait, do_ping, do_down, do_up, filter_country, filter_city,
              filter_location, random_cities, chaos_mode, stop_on_success, profile_name):
        self.stop_event.clear()
        threading.Thread(target=self._run,
                         args=(
                         work_plan, resume, timeout, speed_wait, do_ping, do_down, do_up, filter_country, filter_city,
                         filter_location, random_cities, chaos_mode, stop_on_success, profile_name)).start()

    def stop(self):
        self.stop_event.set()
        self.log("Stopping...", "WARN")

    def _run(self, work_plan, resume, conn_timeout, speed_wait, do_ping, do_down, do_up, filter_country, filter_city,
             filter_location, random_cities, chaos_mode, stop_on_success, profile_name):
        try:
            if not os.path.exists(CSV_FILE):
                self.log(f"{CSV_FILE} missing! Run convert_csv.py first.", "FAILURE")
                self.app.on_job_finish()
                return

            if not resume: self.db.clear_db()

            raw_locations = self.app.raw_locations

            # --- 1. FILTERING ---
            locations = []
            skipped_count = 0

            for loc in raw_locations:
                country = canonical_country_name(loc.get("country") or "")
                city = (loc.get("city") or "").strip()
                location_name = (loc.get("location") or "").strip()

                # Country
                if filter_country != "All" and filter_country != country:
                    skipped_count += 1
                    continue

                # City
                if filter_city != "All" and filter_city != city:
                    skipped_count += 1
                    continue

                # Location
                if filter_location != "All" and filter_location != location_name:
                    skipped_count += 1
                    continue

                locations.append(loc)

            # --- 2. RANDOMIZE CITIES (Normal Random) ---
            if random_cities:
                self.log("Randomizing CITY order...", "INFO")
                random.shuffle(locations)

            self.log(f"Queued {len(locations)} locations (Skipped {skipped_count})", "HEADER")

            total_tests = len(locations) * sum(len(ports) for ports in work_plan.values())

            def iter_tasks():
                for loc in locations:
                    for proto, ports in work_plan.items():
                        for port in ports:
                            yield loc, proto, port

            # --- 3. CHAOS MODE ---
            if chaos_mode:
                self.log("CHAOS MODE: Randomizing ALL individual tests...", "WARN")
                all_tasks = list(iter_tasks())
                random.shuffle(all_tasks)
                tasks = iter(all_tasks)
            else:
                self.log(f"Sequential Mode (City Grouped): {total_tests} tests queued.", "INFO")
                tasks = iter_tasks()

            tested_keys = self.db.get_tested_keys() if resume else set()

            # --- 4. EXECUTE ---
            for i, task in enumerate(tasks):
                if self.stop_event.is_set(): break

                loc_data, proto, port = task
                target_city = loc_data['city']
                location_name = loc_data['location']
                country = loc_data['country']

                # Resume Check
                if resume:
                    if (location_name, target_city, country, proto, port) in tested_keys:
                        continue

                self.log("-" * 40, "INFO")
                self.log(f"Test {i + 1}/{total_tests}: {location_name} ({country}) -> {proto}:{port}", "HEADER")

                # *** CRITICAL: Ensure we are disconnected first ***
                if not self.ensure_disconnected():
                    self.log("ERROR: Could not disconnect. Skipping...", "FAILURE")
                    continue

                target_arg = f"{proto}:{port}"
                self.update_dashboard("-", "-", "-", f"Conn {target_city}...", 0.2)

                start_ts = time.time()
                self.run_cli(["connect", "-n", target_city, target_arg])

                # Small buffer for CLI to update
                time.sleep(1)

                _, status_out = self.run_cli(["status"])
                print(f"\n[DEBUG] {target_city} ({target_arg}):")
                print(status_out)
                print("-" * 40)

                # Skip Logic
                if "Location does not exist" in status_out or "is disabled" in status_out:
                    self.log(f"SKIPPING: {location_name} unavailable.", "FAILURE")
                    self.db.record_result(location_name, target_city, country, proto, port, "INVALID_LOC", 0, 0, 0, 0,
                                          "N/A")
                    continue

                connected, duration = self.wait_for_connection(start_ts, conn_timeout)
                ping, down, up, isp = 0, 0, 0, "N/A"
                status_str = "FAILURE"

                if connected:
                    status_str = "SUCCESS"
                    self.log(f"Connected in {duration:.2f}s", "SUCCESS")
                    self.app.add_success(f"{location_name} - {target_city} ({country}) | {proto}:{port}")

                    st = None
                    if do_ping or do_down or do_up:
                        try:
                            self.update_dashboard("-", "-", "-", "Fetch ISP...", 0.3)
                            st = speedtest.Speedtest()
                        except Exception as ex:
                            self.log(f"Speedtest initialization error: {ex}", "WARN")

                        if st is not None:
                            try:
                                client_info = st.results.client
                                isp = client_info.get("isp", "Unknown")
                                self.log(f"ISP: {isp}", "INFO")
                            except Exception as ex:
                                self.log(f"Could not read ISP information: {ex}", "WARN")
                                isp = "Unknown"

                    if st is not None:
                        self.log(f"Waiting {speed_wait}s...", "INFO")
                        time.sleep(speed_wait)
                        if not self.stop_event.is_set():
                            try:
                                self.update_dashboard("-", "-", "-", "Finding Server...", 0.4)
                                st.get_best_server()
                                if do_ping:
                                    ping = st.results.ping
                                    self.update_dashboard(f"{ping:.0f}", "-", "-", "Ping...", 0.6)
                                if do_down:
                                    down = st.download() / 1_000_000
                                    self.update_dashboard(f"{ping:.0f}", f"{down:.1f}", "-", "Down...", 0.7)
                                if do_up:
                                    up = st.upload() / 1_000_000
                                    self.update_dashboard(f"{ping:.0f}", f"{down:.1f}", f"{up:.1f}", "Up...", 0.9)
                                self.log(f"P:{ping:.0f} D:{down:.1f} U:{up:.1f}", "INFO")
                            except Exception as ex:
                                self.log(f"Speedtest Error: {ex}", "WARN")
                else:
                    self.log(f"Timeout on {target_arg}", "FAILURE")

                self.db.record_result(location_name, target_city, country, proto, port, status_str, duration, ping,
                                      down, up, profile_name)
                self.update_dashboard(f"{ping:.0f}" if ping else "-", f"{down:.1f}" if down else "-",
                                      f"{up:.1f}" if up else "-", "Saved", 0)

                # Disconnect after job
                self.run_cli(["disconnect"])
                time.sleep(3)

                if connected and stop_on_success:
                    self.log("STOP ON SUCCESS ENABLED. Stopping job.", "WARN")
                    self.stop_event.set()
                    break

        except Exception as e:
            self.log(f"Critical Error: {e}", "FAILURE")
        finally:
            self.app.on_job_finish()


# --- Main App ---
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("WALF | Windscribe Location Finder")
        self.geometry("1180x980")
        self.minsize(960, 600)
        self.configure(fg_color="#0b1120")

        self.protocol_vars = {}
        self.port_vars = {}
        self.protocol_labels = {}
        self.config_data = ConfigManager.load_config()
        self.last_settings = self.config_data.get("last_settings", {})
        self.saved_profiles = self.config_data.get("saved_profiles", {})
        self.priority_order = self.last_settings.get("priority_order", list(DEFAULT_PROTOCOLS.keys()))

        self.is_log_fullscreen = False
        self.current_profile_name = "Manual"
        self.selected_country = "All"
        self.selected_city = "All"
        self.selected_location = "All"
        self.country_picker_popup = None
        self.locations_by_country = {}
        self.country_values = ["All"]
        self.all_cities_list = ["All"]
        self.all_locations_list = ["All"]
        self.raw_locations = []
        self.csv_load_error = None

        self.load_csv_data()
        self.init_vars()
        self.setup_ui()
        self.worker = WindscribeWorker(self)
        self.apply_config_to_ui()
        if self.csv_load_error:
            self.log_message(f"Could not load location data: {self.csv_load_error}", "FAILURE")
        if platform.system() == "Windows":
            self.after(0, lambda: self.state("zoomed"))

    def load_csv_data(self):
        if os.path.exists(CSV_FILE):
            try:
                locations_by_country = {}
                raw_locations = []
                with open(CSV_FILE, mode='r', encoding='utf-8-sig') as f:
                    reader = csv.DictReader(f, skipinitialspace=True)
                    for row in reader:
                        if "City" in row:
                            raw_locations.append({
                                "city": (row.get("City") or "").strip(),
                                "location": (row.get("Location") or "").strip(),
                                "country": canonical_country_name(row.get("Region") or ""),
                            })
                        city = (row.get("City") or "").strip()
                        location = (row.get("Location") or "").strip()
                        country = canonical_country_name(row.get("Region") or "")
                        if not city or not country:
                            continue
                        locations_by_country.setdefault(country, {}).setdefault(city, set()).add(location)

                self.locations_by_country = locations_by_country
                self.raw_locations = raw_locations
                self.country_values = ["All"] + sorted(locations_by_country)
                selected_country = self.last_settings.get("filter_country", "All")
                if selected_country not in locations_by_country:
                    selected_country = "All"
                self.all_cities_list = self.get_city_values(selected_country)
                selected_city = self.last_settings.get("filter_city", "All")
                if selected_city not in self.all_cities_list:
                    selected_city = "All"
                self.all_locations_list = self.get_location_values(selected_country, selected_city)
            except (OSError, csv.Error, UnicodeError) as e:
                self.csv_load_error = str(e)
                self.locations_by_country = {}
                self.raw_locations = []
                self.country_values = ["All"]
                self.all_cities_list = ["All", "Error"]
                self.all_locations_list = ["All", "Error"]
        else:
            self.locations_by_country = {}
            self.raw_locations = []
            self.country_values = ["All"]
            self.all_cities_list = ["All", "CSV Missing"]
            self.all_locations_list = ["All", "CSV Missing"]

    @staticmethod
    def format_country_label(country):
        return f"{country_flag(country)}  {country}"

    def set_selected_country(self, country):
        if country not in self.country_values:
            country = "All"
        self.selected_country = country
        self.btn_country_picker.configure(
            text=self.format_country_label(country) + "   \u25be"
        )
        self.on_country_change(country)

    def open_country_picker(self):
        self.open_searchable_picker(
            title="Choose a country",
            values=self.country_values,
            selected=self.selected_country,
            anchor=self.btn_country_picker,
            item_icon=country_flag,
            on_select=self.set_selected_country,
            search_placeholder="Search countries..."
        )

    def open_city_picker(self):
        self.open_searchable_picker(
            title=f"Choose a city in {self.selected_country}",
            values=self.get_city_values(self.selected_country),
            selected=self.selected_city,
            anchor=self.btn_city_picker,
            item_icon=lambda _value: "\U0001f3d9\ufe0f",
            on_select=self.set_selected_city,
            search_placeholder="Search cities..."
        )

    def open_server_picker(self):
        self.open_searchable_picker(
            title=f"Choose a server in {self.selected_city}",
            values=self.get_location_values(self.selected_country, self.selected_city),
            selected=self.selected_location,
            anchor=self.btn_server_picker,
            item_icon=lambda _value: "\U0001f5a5\ufe0f",
            on_select=self.set_selected_server,
            search_placeholder="Search servers..."
        )

    def open_searchable_picker(
            self, title, values, selected, anchor, item_icon, on_select, search_placeholder):
        popup = ctk.CTkToplevel(self)
        self.country_picker_popup = popup
        popup.title(title)
        popup.transient(self)
        popup.attributes("-topmost", True)
        popup_width = 360
        popup_height = 380
        scale = ctk.ScalingTracker.get_widget_scaling(self)
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height()
        actual_height = popup_height * scale
        screen_bottom = self.winfo_screenheight() - 80
        if y + actual_height > screen_bottom:
            y = max(0, anchor.winfo_rooty() - actual_height)
        popup.geometry(f"{popup_width}x{popup_height}+{x}+{y}")
        popup.grid_columnconfigure(0, weight=1)
        popup.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            popup, text=title, font=("Segoe UI", 14, "bold"),
            text_color="#e2e8f0"
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 5))
        search = ctk.CTkEntry(
            popup, placeholder_text=search_placeholder, height=34
        )
        search.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        country_list_viewport = ctk.CTkFrame(
            popup, height=popup_height - 105, fg_color="transparent"
        )
        country_list_viewport.grid(
            row=2, column=0, sticky="nsew", padx=10, pady=(0, 10)
        )
        country_list_viewport.grid_propagate(False)
        country_list = ctk.CTkScrollableFrame(
            country_list_viewport, fg_color="#151d2b", corner_radius=10,
            scrollbar_button_color="#334155", scrollbar_button_hover_color="#475569"
        )
        country_list.pack(fill="both", expand=True)
        country_list.grid_columnconfigure(0, weight=1)
        self.country_picker_list = country_list

        def populate_list(query=""):
            for widget in country_list.winfo_children():
                widget.destroy()
            query = query.strip().casefold()
            matches = [
                value for value in values
                if query in value.casefold()
            ]
            for row, value in enumerate(matches):
                is_selected = value == selected
                button = ctk.CTkButton(
                    country_list,
                    text=f"{item_icon(value)}   {value}",
                    anchor="w", height=34, corner_radius=7,
                    fg_color="#1d4ed8" if is_selected else "transparent",
                    hover_color="#263449",
                    text_color="#f8fafc" if is_selected else "#dbe4f0",
                    font=("Segoe UI Emoji", 12),
                    command=lambda item=value: choose_value(item)
                )
                button.grid(row=row, column=0, sticky="ew", padx=4, pady=1)
            if not matches:
                ctk.CTkLabel(
                    country_list, text="No matching items",
                    text_color="#94a3b8", font=("Segoe UI", 11)
                ).grid(row=0, column=0, pady=12)

        def choose_value(value):
            on_select(value)
            popup.destroy()

        search.bind("<KeyRelease>", lambda _event: populate_list(search.get()))
        populate_list()
        popup.bind("<Escape>", lambda _event: popup.destroy())
        popup.after(50, search.focus_set)

    def set_selected_city(self, city):
        if city not in self.get_city_values(self.selected_country):
            city = "All"
        self.selected_city = city
        self.btn_city_picker.configure(text=f"\U0001f3d9\ufe0f  {city}   \u25be")
        self.on_city_change(city)

    def set_selected_server(self, server):
        if server not in self.get_location_values(self.selected_country, self.selected_city):
            server = "All"
        self.selected_location = server
        self.btn_server_picker.configure(text=f"\U0001f5a5\ufe0f  {server}   \u25be")

    def get_city_values(self, country):
        if country == "All":
            cities = {
                city
                for country_cities in self.locations_by_country.values()
                for city in country_cities
            }
        else:
            cities = set(self.locations_by_country.get(country, {}))
        return ["All"] + sorted(cities)

    def get_location_values(self, country, city):
        if country == "All":
            locations = {
                location
                for country_cities in self.locations_by_country.values()
                for city_locations in country_cities.values()
                for location in city_locations
                if location
            }
        elif city == "All":
            locations = {
                location
                for city_locations in self.locations_by_country.get(country, {}).values()
                for location in city_locations
                if location
            }
        else:
            locations = set(
                self.locations_by_country.get(country, {}).get(city, set())
            )
            locations.discard("")
        return ["All"] + sorted(locations)

    def update_location_filter_labels(self, country, city):
        self.lbl_country_filter.configure(
            text=f"COUNTRY · {country}" if country != "All" else "COUNTRY"
        )
        self.lbl_city_filter.configure(
            text=f"CITY · {country}" if country != "All" else "CITY"
        )
        if city != "All":
            self.lbl_server_filter.configure(text=f"SERVER · {city}")
        elif country != "All":
            self.lbl_server_filter.configure(text=f"SERVER · {country}")
        else:
            self.lbl_server_filter.configure(text="SERVER")

    def on_country_change(self, country):
        self.selected_country = country
        if hasattr(self, "btn_country_picker"):
            self.btn_country_picker.configure(
                text=self.format_country_label(country) + "   \u25be"
            )
        cities = self.get_city_values(country)
        self.selected_city = "All"
        if hasattr(self, "btn_city_picker"):
            self.btn_city_picker.configure(text="\U0001f3d9\ufe0f  All   \u25be")
        locations = self.get_location_values(country, "All")
        self.selected_location = "All"
        if hasattr(self, "btn_server_picker"):
            self.btn_server_picker.configure(text="\U0001f5a5\ufe0f  All   \u25be")
        self.update_location_filter_labels(country, "All")

    def on_city_change(self, city):
        country = self.selected_country
        self.selected_city = city
        locations = self.get_location_values(country, city)
        self.selected_location = "All"
        if hasattr(self, "btn_server_picker"):
            self.btn_server_picker.configure(text="\U0001f5a5\ufe0f  All   \u25be")
        self.update_location_filter_labels(country, city)

    def init_vars(self):
        saved_protocols = self.last_settings.get("protocols", {})
        for proto, ports in DEFAULT_PROTOCOLS.items():
            proto_config = saved_protocols.get(proto, {})
            is_proto_enabled = proto_config.get("enabled", True)
            self.protocol_vars[proto] = ctk.BooleanVar(value=is_proto_enabled)
            self.port_vars[proto] = {}
            saved_ports = proto_config.get("ports", {})
            saved_ports = saved_ports if isinstance(saved_ports, dict) else {}
            configured_ports = set(ports)
            for saved_port in saved_ports:
                try:
                    port_number = int(saved_port)
                except (TypeError, ValueError):
                    continue
                if 1 <= port_number <= 65535:
                    configured_ports.add(port_number)
            for port in sorted(configured_ports):
                is_port_enabled = saved_ports.get(str(port), True)
                self.port_vars[proto][port] = ctk.BooleanVar(value=is_port_enabled)

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(5, weight=1)

        self.frame_header = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_header.grid(row=0, column=0, padx=24, pady=(12, 4), sticky="ew")
        ctk.CTkLabel(
            self.frame_header, text="WALF", font=("Segoe UI", 28, "bold"),
            text_color="#60a5fa"
        ).pack(side="left")
        ctk.CTkLabel(
            self.frame_header, text="  WINDSCRIBE LOCATION FINDER",
            font=("Segoe UI", 13, "bold"), text_color="#94a3b8"
        ).pack(side="left", pady=(8, 0))
        ctk.CTkLabel(
            self.frame_header, text="VPN benchmark & server discovery",
            font=("Segoe UI", 12), text_color="#64748b"
        ).pack(side="right", pady=(8, 0))

        self.frame_dashboard = ctk.CTkFrame(
            self, fg_color="#111c2f", corner_radius=18,
            border_width=1, border_color="#1e293b"
        )
        self.frame_dashboard.grid(row=1, column=0, padx=24, pady=8, sticky="ew")
        self.frame_dashboard.columnconfigure((0, 1, 2, 3), weight=1, uniform="metrics")

        self.lbl_ping_val = self.create_tile(self.frame_dashboard, 0, "PING", "-", "#f8fafc", "ms")
        self.lbl_down_val = self.create_tile(self.frame_dashboard, 1, "DOWNLOAD", "-", "#60a5fa", "Mbps")
        self.lbl_up_val = self.create_tile(self.frame_dashboard, 2, "UPLOAD", "-", "#a78bfa", "Mbps")
        self.lbl_count_val = self.create_tile(self.frame_dashboard, 3, "SAVED RESULTS", "0", "#34d399", "tests")

        self.lbl_status = ctk.CTkLabel(
            self.frame_dashboard, text="Ready to scan",
            font=("Segoe UI", 12, "bold"), text_color="#cbd5e1"
        )
        self.lbl_status.grid(row=2, column=0, columnspan=4, pady=(4, 8))
        self.progress_bar = ctk.CTkProgressBar(self.frame_dashboard)
        self.progress_bar.configure(
            height=8, corner_radius=8, progress_color="#3b82f6",
            fg_color="#263449"
        )
        self.progress_bar.grid(row=3, column=0, columnspan=4, padx=22, pady=(0, 10), sticky="ew")
        self.progress_bar.set(0)

        self.frame_settings = ctk.CTkFrame(
            self, fg_color="#111c2f", corner_radius=16,
            border_width=1, border_color="#1e293b"
        )
        self.frame_settings.grid(row=2, column=0, padx=24, pady=8, sticky="ew")
        self.frame_settings.columnconfigure(0, weight=1)

        config_frame = ctk.CTkFrame(self.frame_settings, fg_color="transparent")
        config_frame.pack(fill="x", padx=14, pady=(7, 3))
        ctk.CTkLabel(config_frame, text="PROFILE", font=("Segoe UI", 11, "bold"),
                     text_color="#94a3b8").pack(side="left", padx=(4, 10))
        self.combo_profiles = ctk.CTkComboBox(
            config_frame, values=list(self.saved_profiles.keys()), width=190,
            command=self.load_profile, height=34
        )
        self.combo_profiles.pack(side="left", padx=4)
        ctk.CTkButton(
            config_frame, text="Delete", command=self.delete_profile, width=78, height=34,
            fg_color="#7f1d1d", hover_color="#991b1b", corner_radius=8
        ).pack(side="left", padx=4)
        self.entry_save_name = ctk.CTkEntry(
            config_frame, placeholder_text="New profile name", width=180, height=34
        )
        self.entry_save_name.pack(side="right", padx=(4, 0))
        ctk.CTkButton(
            config_frame, text="Save profile", command=self.save_current_profile,
            width=112, height=34, corner_radius=8
        ).pack(side="right", padx=6)

        filter_frame = ctk.CTkFrame(self.frame_settings, fg_color="transparent")
        filter_frame.pack(fill="x", padx=14, pady=3)
        self.lbl_country_filter = ctk.CTkLabel(
            filter_frame, text="COUNTRY", font=("Segoe UI", 10, "bold"),
            text_color="#94a3b8"
        )
        self.lbl_city_filter = ctk.CTkLabel(
            filter_frame, text="CITY", font=("Segoe UI", 10, "bold"),
            text_color="#94a3b8"
        )
        self.lbl_server_filter = ctk.CTkLabel(
            filter_frame, text="SERVER", font=("Segoe UI", 10, "bold"),
            text_color="#94a3b8"
        )
        for column, label in enumerate(
                (self.lbl_country_filter, self.lbl_city_filter, self.lbl_server_filter)):
            label.grid(row=0, column=column, sticky="w", padx=6)
        filter_frame.columnconfigure((0, 1, 2), weight=1, uniform="filters")
        self.btn_country_picker = ctk.CTkButton(
            filter_frame, text=self.format_country_label("All") + "   ▾",
            height=34, anchor="w", corner_radius=8,
            fg_color="#30343b", hover_color="#414854",
            border_width=1, border_color="#565d68",
            command=self.open_country_picker
        )
        self.btn_country_picker.grid(row=1, column=0, sticky="ew", padx=5, pady=(3, 0))
        self.btn_city_picker = ctk.CTkButton(
            filter_frame, text="\U0001f3d9\ufe0f  All   \u25be",
            height=34, anchor="w", corner_radius=8,
            fg_color="#30343b", hover_color="#414854",
            border_width=1, border_color="#565d68",
            command=self.open_city_picker
        )
        self.btn_city_picker.grid(row=1, column=1, sticky="ew", padx=5, pady=(3, 0))
        self.btn_server_picker = ctk.CTkButton(
            filter_frame, text="\U0001f5a5\ufe0f  All   \u25be",
            height=34, anchor="w", corner_radius=8,
            fg_color="#30343b", hover_color="#414854",
            border_width=1, border_color="#565d68",
            command=self.open_server_picker
        )
        self.btn_server_picker.grid(row=1, column=2, sticky="ew", padx=5, pady=(3, 0))

        options_frame = ctk.CTkFrame(self.frame_settings, fg_color="transparent")
        options_frame.pack(fill="x", padx=14, pady=3)
        self.chk_random_cities = ctk.CTkCheckBox(
            options_frame, text="Randomize cities", font=("Segoe UI", 11)
        )
        self.chk_random_cities.pack(side="left", padx=(5, 18))
        self.chk_random = ctk.CTkCheckBox(
            options_frame, text="Chaos mode", font=("Segoe UI", 11)
        )
        self.chk_random.pack(side="left", padx=18)
        self.chk_stop_success = ctk.CTkCheckBox(
            options_frame, text="Stop on success", font=("Segoe UI", 11)
        )
        self.chk_stop_success.pack(side="left", padx=18)
        self.chk_anti_censorship = ctk.CTkCheckBox(
            options_frame, text="Use Anti-Censorship scan (Stealth/WStunnel)", font=("Segoe UI", 11)
        )
        self.chk_anti_censorship.pack(side="left", padx=18)
        self.btn_clear_log = ctk.CTkButton(
            options_frame, text="Clear logs", command=self.clear_logs,
            fg_color="#263449", hover_color="#334155", width=100, height=30, corner_radius=8
        )
        self.btn_clear_log.pack(side="right", padx=5)

        param_frame = ctk.CTkFrame(self.frame_settings, fg_color="transparent")
        param_frame.pack(fill="x", padx=14, pady=(2, 7))
        ctk.CTkLabel(param_frame, text="TIMEOUT", font=("Segoe UI", 10, "bold"),
                     text_color="#94a3b8").pack(side="left", padx=(5, 8))
        self.entry_timeout = ctk.CTkEntry(param_frame, width=72, height=32, justify="center")
        self.entry_timeout.pack(side="left")
        ctk.CTkLabel(param_frame, text="WAIT", font=("Segoe UI", 10, "bold"),
                     text_color="#94a3b8").pack(side="left", padx=(18, 8))
        self.entry_speed_wait = ctk.CTkEntry(param_frame, width=72, height=32, justify="center")
        self.entry_speed_wait.pack(side="left")
        ctk.CTkLabel(param_frame, text="BENCHMARK", font=("Segoe UI", 10, "bold"),
                     text_color="#94a3b8").pack(side="left", padx=(24, 8))
        self.chk_ping = ctk.CTkCheckBox(param_frame, text="Ping", font=("Segoe UI", 11))
        self.chk_ping.pack(side="left", padx=8)
        self.chk_down = ctk.CTkCheckBox(param_frame, text="Download", font=("Segoe UI", 11))
        self.chk_down.pack(side="left", padx=8)
        self.chk_up = ctk.CTkCheckBox(param_frame, text="Upload", font=("Segoe UI", 11))
        self.chk_up.pack(side="left", padx=8)

        self.frame_config_tabs = ctk.CTkFrame(self, fg_color="transparent", height=190)
        self.frame_config_tabs.grid(row=4, column=0, padx=24, pady=8, sticky="nsew")
        self.frame_config_tabs.grid_propagate(False)
        self.frame_config_tabs.grid_columnconfigure(0, weight=1)
        self.frame_config_tabs.grid_rowconfigure(0, weight=1)
        self.tab_config = ctk.CTkTabview(
            self.frame_config_tabs, height=180, corner_radius=14, fg_color="#111c2f",
            segmented_button_fg_color="#1e293b",
            segmented_button_selected_color="#2563eb",
            segmented_button_selected_hover_color="#1d4ed8",
            segmented_button_unselected_hover_color="#334155"
        )
        self.tab_config.grid(row=0, column=0, sticky="nsew")
        self.tab_config.add("Configuration")
        self.tab_config.add("Priority Order")
        self.setup_config_tab(self.tab_config.tab("Configuration"))
        self.setup_priority_tab(self.tab_config.tab("Priority Order"))

        self.frame_logs_container = ctk.CTkFrame(
            self, fg_color="#111c2f", corner_radius=14,
            border_width=1, border_color="#1e293b"
        )
        self.frame_logs_container.grid(row=5, column=0, padx=24, pady=8, sticky="nsew")
        self.frame_logs_container.grid_columnconfigure(0, weight=1)
        self.frame_logs_container.grid_rowconfigure(1, weight=1)
        log_header = ctk.CTkFrame(self.frame_logs_container, fg_color="transparent")
        log_header.grid(row=0, column=0, padx=12, pady=(7, 0), sticky="ew")
        ctk.CTkLabel(log_header, text="ACTIVITY", font=("Segoe UI", 11, "bold"),
                     text_color="#94a3b8").pack(side="left", padx=5)
        self.btn_maximize = ctk.CTkButton(
            log_header, text="Expand logs", command=self.toggle_log_fullscreen,
            fg_color="#263449", hover_color="#334155", height=28, width=112, corner_radius=8
        )
        self.btn_maximize.pack(side="right", padx=4)

        self.log_tabview = ctk.CTkTabview(
            self.frame_logs_container, fg_color="transparent",
            segmented_button_fg_color="#1e293b",
            segmented_button_selected_color="#2563eb",
            segmented_button_selected_hover_color="#1d4ed8",
            segmented_button_unselected_hover_color="#334155"
        )
        self.log_tabview.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="nsew")
        self.log_tabview.add("All Logs")
        self.log_tabview.add("Success List")

        self.log_box = tk.Text(
            self.log_tabview.tab("All Logs"), bg="#0b1220", fg="#e2e8f0",
            insertbackground="#e2e8f0", selectbackground="#1d4ed8",
            font=("Cascadia Mono", 10), relief="flat", borderwidth=0,
            padx=12, pady=10
        )
        self.log_box.pack(fill="both", expand=True, padx=4, pady=4)
        self.log_box.tag_config("SUCCESS", foreground="#2cc985")
        self.log_box.tag_config("FAILURE", foreground="#ff4d4d")
        self.log_box.tag_config("WARN", foreground="orange")
        self.log_box.tag_config("HEADER", foreground="#60a5fa", font=("Cascadia Mono", 10, "bold"))
        self.log_box.tag_config("INFO", foreground="#cbd5e1")

        self.txt_success = tk.Text(
            self.log_tabview.tab("Success List"), bg="#0b1220", fg="#34d399",
            insertbackground="#e2e8f0", selectbackground="#1d4ed8",
            font=("Cascadia Mono", 10), relief="flat", borderwidth=0,
            padx=12, pady=10
        )
        self.txt_success.pack(fill="both", expand=True, padx=4, pady=4)

        self.frame_actions = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_actions.grid(row=3, column=0, padx=24, pady=(8, 4), sticky="ew")

        self.btn_fresh = ctk.CTkButton(
            self.frame_actions, text="Start test", command=self.start_fresh,
            fg_color="#16a34a", hover_color="#15803d", height=44, corner_radius=10,
            font=("Segoe UI", 12, "bold")
        )
        self.btn_fresh.pack(side="left", padx=(0, 8), expand=True, fill="x")
        self.btn_continue = ctk.CTkButton(
            self.frame_actions, text="Continue test", command=self.start_continue,
            fg_color="#2563eb", hover_color="#1d4ed8", height=44, corner_radius=10,
            font=("Segoe UI", 12, "bold")
        )
        self.btn_continue.pack(side="left", padx=8, expand=True, fill="x")
        self.btn_stop = ctk.CTkButton(
            self.frame_actions, text="Stop operation", command=self.stop_job,
            fg_color="#b91c1c", hover_color="#991b1b",
            state="disabled", height=44, corner_radius=10,
            font=("Segoe UI", 12, "bold")
        )
        self.btn_stop.pack(side="left", padx=8, expand=True, fill="x")
        self.btn_export = ctk.CTkButton(
            self.frame_actions, text="Request report", command=self.export_csv,
            fg_color="#334155", hover_color="#475569", height=44, corner_radius=10,
            font=("Segoe UI", 12, "bold")
        )
        self.btn_export.pack(side="left", padx=(8, 0), expand=True, fill="x")

    def toggle_log_fullscreen(self):
        if not self.is_log_fullscreen:
            self.frame_header.grid_remove()
            self.frame_dashboard.grid_remove()
            self.frame_settings.grid_remove()
            self.frame_config_tabs.grid_remove()
            self.frame_actions.grid_remove()
            self.btn_maximize.configure(text="Restore view", fg_color="#16a34a")
            self.is_log_fullscreen = True
        else:
            self.frame_header.grid()
            self.frame_dashboard.grid()
            self.frame_settings.grid()
            self.frame_config_tabs.grid()
            self.frame_actions.grid()
            self.btn_maximize.configure(text="Expand logs", fg_color="#263449")
            self.is_log_fullscreen = False

    def apply_config_to_ui(self):
        self.entry_timeout.delete(0, "end")
        self.entry_timeout.insert(0, str(self.last_settings.get("timeout", "25")))
        self.entry_speed_wait.delete(0, "end")
        self.entry_speed_wait.insert(0, str(self.last_settings.get("speed_wait", "5")))

        if self.last_settings.get("test_ping", False):
            self.chk_ping.select()
        else:
            self.chk_ping.deselect()
        if self.last_settings.get("test_down", False):
            self.chk_down.select()
        else:
            self.chk_down.deselect()
        if self.last_settings.get("test_up", False):
            self.chk_up.select()
        else:
            self.chk_up.deselect()

        if self.last_settings.get("random_cities", False):
            self.chk_random_cities.select()
        else:
            self.chk_random_cities.deselect()
        if self.last_settings.get("chaos_mode", False):
            self.chk_random.select()
        else:
            self.chk_random.deselect()
        if self.last_settings.get("stop_on_success", False):
            self.chk_stop_success.select()
        else:
            self.chk_stop_success.deselect()
        if self.last_settings.get("anti_censorship", False):
            self.chk_anti_censorship.select()
        else:
            self.chk_anti_censorship.deselect()

        country = self.last_settings.get("filter_country", "All")
        if country not in self.country_values:
            country = "All"
        self.selected_country = country
        self.btn_country_picker.configure(
            text=self.format_country_label(country) + "   \u25be"
        )

        cities = self.get_city_values(country)
        city = self.last_settings.get("filter_city", "All")
        if city not in cities:
            city = "All"
        self.selected_city = city
        self.btn_city_picker.configure(text=f"\U0001f3d9\ufe0f  {city}   \u25be")

        locations = self.get_location_values(country, city)
        location = self.last_settings.get("filter_location", "All")
        if location not in locations:
            location = "All"
        self.selected_location = location
        self.btn_server_picker.configure(text=f"\U0001f5a5\ufe0f  {location}   \u25be")
        self.update_location_filter_labels(country, city)

    def gather_config_data(self):
        data = {
            "timeout": self.entry_timeout.get(),
            "speed_wait": self.entry_speed_wait.get(),
            "test_ping": bool(self.chk_ping.get()),
            "test_down": bool(self.chk_down.get()),
            "test_up": bool(self.chk_up.get()),
            "filter_country": self.selected_country,
            "filter_city": self.selected_city,
            "filter_location": self.selected_location,
            "random_cities": bool(self.chk_random_cities.get()),
            "chaos_mode": bool(self.chk_random.get()),
            "stop_on_success": bool(self.chk_stop_success.get()),
            "anti_censorship": bool(self.chk_anti_censorship.get()),
            "priority_order": self.priority_order,
            "protocols": {}
        }
        for proto, p_var in self.protocol_vars.items():
            ports_data = {str(p): bool(v.get()) for p, v in self.port_vars[proto].items()}
            data["protocols"][proto] = {"enabled": bool(p_var.get()), "ports": ports_data}
        return data

    def save_current_profile(self):
        name = self.entry_save_name.get().strip()
        if not name:
            name = self.combo_profiles.get().strip()

        if not name:
            tk.messagebox.showerror("Error", "Please enter a profile name.")
            return

        current_settings = self.gather_config_data()
        self.saved_profiles[name] = current_settings
        self.config_data["saved_profiles"] = self.saved_profiles
        self.config_data["last_settings"] = current_settings
        ConfigManager.save_config(self.config_data)

        self.combo_profiles.configure(values=list(self.saved_profiles.keys()))
        self.combo_profiles.set(name)
        self.current_profile_name = name
        tk.messagebox.showinfo("Saved", f"Profile '{name}' saved.")

    def load_profile(self, choice=None):
        name = choice if choice else self.combo_profiles.get()
        if name in self.saved_profiles:
            profile = self.saved_profiles[name]
            self.last_settings = profile
            self.apply_config_to_ui()
            self.current_profile_name = name

            saved_protocols = profile.get("protocols", {})
            for proto in DEFAULT_PROTOCOLS:
                settings = saved_protocols.get(proto, {})
                if not isinstance(settings, dict):
                    settings = {}
                self.protocol_vars[proto].set(settings.get("enabled", True))
                saved_ports = settings.get("ports", {})
                saved_ports = saved_ports if isinstance(saved_ports, dict) else {}
                port_states = {}
                for saved_port, enabled in saved_ports.items():
                    try:
                        port_number = int(saved_port)
                    except (TypeError, ValueError):
                        continue
                    if 1 <= port_number <= 65535:
                        port_states[port_number] = bool(enabled)

                if "ports" not in settings:
                    port_states = {port: True for port in DEFAULT_PROTOCOLS[proto]}
                self.port_vars[proto] = {
                    port: ctk.BooleanVar(value=enabled)
                    for port, enabled in sorted(port_states.items())
                }

            self.priority_order = profile.get("priority_order", list(DEFAULT_PROTOCOLS.keys()))
            selected_proto = self.protocol_selector.get().lower()
            self.show_protocol(selected_proto)
            self.refresh_priority_list()
            self.log_message(f"Loaded profile: {name}", "INFO")

    def delete_profile(self):
        name = self.combo_profiles.get()
        if name in self.saved_profiles:
            if tk.messagebox.askyesno("Delete", f"Delete profile '{name}'?"):
                del self.saved_profiles[name]
                self.config_data["saved_profiles"] = self.saved_profiles
                ConfigManager.save_config(self.config_data)

                profiles = list(self.saved_profiles.keys())
                self.combo_profiles.configure(values=profiles)
                if profiles:
                    self.combo_profiles.set(profiles[0])
                else:
                    self.combo_profiles.set("")
                self.log_message(f"Deleted profile: {name}", "WARN")

    def create_tile(self, parent, col, title, initial, color, unit):
        tile = ctk.CTkFrame(parent, fg_color="#17243a", corner_radius=12)
        tile.grid(row=1, column=col, padx=8, pady=(14, 10), sticky="nsew")
        ctk.CTkLabel(
            tile, text=title, font=("Segoe UI", 10, "bold"),
            text_color="#94a3b8"
        ).pack(pady=(10, 0))
        lbl = ctk.CTkLabel(
            tile, text=initial, font=("Segoe UI", 27, "bold"), text_color=color
        )
        lbl.pack(pady=(0, 0))
        ctk.CTkLabel(
            tile, text=unit, font=("Segoe UI", 9), text_color="#64748b"
        ).pack(pady=(0, 9))
        return lbl

    def update_live_dashboard(self, ping, down, up, status, progress, count):
        self.lbl_ping_val.configure(text=str(ping))
        self.lbl_down_val.configure(text=str(down))
        self.lbl_up_val.configure(text=str(up))
        self.lbl_count_val.configure(text=str(count))
        self.lbl_status.configure(text=status)
        self.progress_bar.set(progress)
        if ping != "-" and str(ping).replace('.', '').isdigit():
            p = float(ping)
            if p < 50:
                self.lbl_ping_val.configure(text_color="#2cc985")
            elif p < 100:
                self.lbl_ping_val.configure(text_color="orange")
            else:
                self.lbl_ping_val.configure(text_color="#ff4d4d")

    def add_success(self, msg):
        ts = datetime.datetime.now().strftime("[%H:%M] ")
        self.txt_success.configure(state="normal")
        self.txt_success.insert("end", ts + msg + "\n")
        line_count = int(self.txt_success.index("end-1c").split(".")[0])
        if line_count > MAX_VISIBLE_LOG_LINES:
            self.txt_success.delete("1.0", f"{line_count - RETAINED_LOG_LINES}.0")
        self.txt_success.see("end")
        self.txt_success.configure(state="disabled")

    def setup_config_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=10, pady=(5, 3))
        self.protocol_selector = ctk.CTkSegmentedButton(
            toolbar, values=[proto.upper() for proto in DEFAULT_PROTOCOLS],
            command=self.show_protocol,
            selected_color="#2563eb", selected_hover_color="#1d4ed8",
            unselected_color="#1e293b", unselected_hover_color="#334155",
            text_color="#e2e8f0", font=("Segoe UI", 10, "bold"),
            corner_radius=8, height=30
        )
        self.protocol_selector.pack(side="left", fill="x", expand=True, padx=(2, 8))
        self.protocol_selector.set("WIREGUARD")
        ctk.CTkButton(
            toolbar, text="Sync client ports", width=112, height=27, corner_radius=8,
            fg_color="#263449", hover_color="#334155",
            command=self.sync_client_ports
        ).pack(side="right", padx=2)
        ctk.CTkButton(
            toolbar, text="Enable all", width=82, height=27, corner_radius=8,
            fg_color="#1d4ed8", hover_color="#1e40af",
            command=lambda: self.set_all_protocols(True)
        ).pack(side="right", padx=(4, 2))
        ctk.CTkButton(
            toolbar, text="Disable all", width=86, height=27, corner_radius=8,
            fg_color="#263449", hover_color="#334155",
            command=lambda: self.set_all_protocols(False)
        ).pack(side="right", padx=2)

        self.protocol_detail = ctk.CTkFrame(
            parent, fg_color="transparent", corner_radius=10
        )
        self.protocol_detail.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 4))
        self.protocol_detail.grid_columnconfigure(0, weight=1)
        self.protocol_labels = {}
        self.port_selectors = {}
        self.show_protocol("WIREGUARD")

    def show_protocol(self, selection):
        proto = selection.lower()
        for widget in self.protocol_detail.winfo_children():
            widget.destroy()
        self.protocol_labels.clear()
        self.port_selectors.clear()

        card = ctk.CTkFrame(
            self.protocol_detail, fg_color="#17243a", corner_radius=11,
            border_width=1, border_color="#26364e"
        )
        card.grid(row=0, column=0, sticky="ew", padx=2, pady=0)
        card.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=(3, 0))
        ctk.CTkCheckBox(
            header, text=f"{proto.upper()} protocol",
            variable=self.protocol_vars[proto],
            font=("Segoe UI", 11, "bold"), text_color="#e2e8f0",
            checkbox_width=18, checkbox_height=18, corner_radius=5,
            command=lambda: self.update_summary(proto)
        ).pack(side="left")
        summary = ctk.CTkLabel(
            header, text="", font=("Segoe UI", 10), text_color="#94a3b8"
        )
        summary.pack(side="left", padx=10)
        self.protocol_labels[proto] = summary
        port_entry = ctk.CTkEntry(
            header, width=78, height=27, placeholder_text="Port #",
            justify="center"
        )
        port_entry.pack(side="right", padx=(4, 3))
        port_entry.bind(
            "<Return>",
            lambda _event, p=proto, entry=port_entry: self.add_protocol_port(p, entry)
        )
        ctk.CTkButton(
            header, text="Add", width=54, height=27, corner_radius=7,
            fg_color="#1d4ed8", hover_color="#1e40af",
            command=lambda p=proto, entry=port_entry: self.add_protocol_port(p, entry)
        ).pack(side="right", padx=3)
        ctk.CTkButton(
            header, text="Defaults", width=72, height=27, corner_radius=7,
            fg_color="#263449", hover_color="#334155",
            command=lambda p=proto: self.restore_default_ports(p)
        ).pack(side="right", padx=3)
        ctk.CTkButton(
            header, text="None", width=52, height=27, corner_radius=7,
            fg_color="#263449", hover_color="#334155",
            command=lambda p=proto: self.set_protocol_ports(p, False)
        ).pack(side="right", padx=3)
        ctk.CTkButton(
            header, text="All", width=44, height=27, corner_radius=7,
            fg_color="#263449", hover_color="#334155",
            command=lambda p=proto: self.set_protocol_ports(p, True)
        ).pack(side="right", padx=3)

        ports_frame = ctk.CTkFrame(card, fg_color="transparent")
        ports_frame.pack(fill="x", padx=10, pady=(0, 1))
        ports = sorted(self.port_vars[proto])
        column_count = min(len(ports), 12)
        if column_count:
            ports_frame.grid_columnconfigure(
                tuple(range(column_count)), weight=1, uniform=f"{proto}_ports"
            )
        self.port_selectors[proto] = {}
        for index, port in enumerate(ports):
            port_item = ctk.CTkFrame(
                ports_frame, fg_color="#202f46", corner_radius=8
            )
            port_item.grid(
                row=index // column_count, column=index % column_count,
                sticky="ew", padx=4, pady=1
            )
            selector = ctk.CTkCheckBox(
                port_item, text=str(port),
                variable=self.port_vars[proto][port],
                font=("Segoe UI", 10), text_color="#cbd5e1",
                checkbox_width=16, checkbox_height=16, corner_radius=4,
                command=lambda: self.update_summary(proto)
            )
            selector.pack(side="left", padx=(7, 2), pady=2)
            remove_button = ctk.CTkButton(
                port_item, text="×", width=22, height=22, corner_radius=6,
                fg_color="transparent", hover_color="#7f1d1d",
                text_color="#fca5a5", font=("Segoe UI", 13, "bold"),
                command=lambda p=proto, n=port: self.remove_protocol_port(p, n)
            )
            remove_button.pack(side="right", padx=(0, 3), pady=1)
            self.port_selectors[proto][port] = (selector, remove_button)

        self.update_summary(proto)

    def setup_priority_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            parent, text="Move protocols up or down to set the test order.",
            font=("Segoe UI", 11), text_color="#94a3b8"
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(9, 3))
        priority_viewport = ctk.CTkFrame(
            parent, height=105, fg_color="transparent", corner_radius=10
        )
        priority_viewport.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 7))
        priority_viewport.grid_propagate(False)
        self.priority_container = ctk.CTkScrollableFrame(
            priority_viewport, width=700, height=105, fg_color="transparent", corner_radius=10,
            scrollbar_button_color="#334155", scrollbar_button_hover_color="#475569"
        )
        self.priority_container.pack(fill="both", expand=True)
        self.refresh_priority_list()

    def refresh_priority_list(self):
        for widget in self.priority_container.winfo_children(): widget.destroy()
        self.priority_port_labels = {}
        for i, proto in enumerate(self.priority_order):
            f = ctk.CTkFrame(
                self.priority_container, fg_color="#17243a", corner_radius=10,
                border_width=1, border_color="#26364e"
            )
            f.pack(fill="x", pady=3, padx=3)
            ctk.CTkLabel(
                f, text=f"{i + 1:02d}", font=("Segoe UI", 11, "bold"),
                text_color="#60a5fa", width=38
            ).pack(side="left", padx=(8, 2), pady=5)
            ctk.CTkLabel(
                f, text=proto.upper(), font=("Segoe UI", 11, "bold"),
                text_color="#e2e8f0", width=115, anchor="w"
            ).pack(side="left", padx=4)
            enabled_count = sum(1 for var in self.port_vars[proto].values() if var.get())
            port_count_label = ctk.CTkLabel(
                f, text=f"{enabled_count}/{len(self.port_vars[proto])} ports",
                font=("Segoe UI", 10), text_color="#94a3b8"
            )
            port_count_label.pack(side="left", padx=8)
            self.priority_port_labels[proto] = port_count_label
            if i < len(self.priority_order) - 1:
                ctk.CTkButton(
                    f, text="Move down", width=90, height=27, corner_radius=7,
                    fg_color="#263449", hover_color="#334155",
                    command=lambda p=proto: self.move_down(p)
                ).pack(side="right", padx=(3, 7), pady=4)
            if i > 0:
                ctk.CTkButton(
                    f, text="Move up", width=80, height=27, corner_radius=7,
                    fg_color="#263449", hover_color="#334155",
                    command=lambda p=proto: self.move_up(p)
                ).pack(side="right", padx=3, pady=4)

    def move_up(self, proto):
        idx = self.priority_order.index(proto)
        if idx > 0:
            self.priority_order[idx], self.priority_order[idx - 1] = self.priority_order[idx - 1], self.priority_order[
                idx]
            self.refresh_priority_list()

    def move_down(self, proto):
        idx = self.priority_order.index(proto)
        if idx < len(self.priority_order) - 1:
            self.priority_order[idx], self.priority_order[idx + 1] = self.priority_order[idx + 1], self.priority_order[
                idx]
            self.refresh_priority_list()

    def set_protocol_ports(self, proto, enabled):
        for variable in self.port_vars[proto].values():
            variable.set(enabled)
        self.update_summary(proto)
        if hasattr(self, "priority_container"):
            self.refresh_priority_list()

    def add_protocol_port(self, proto, entry):
        value = entry.get().strip()
        try:
            port = int(value)
        except ValueError:
            messagebox.showwarning(
                "Invalid port", "Enter a port number between 1 and 65535.", parent=self
            )
            entry.focus_set()
            return

        if not 1 <= port <= 65535:
            messagebox.showwarning(
                "Invalid port", "Port numbers must be between 1 and 65535.", parent=self
            )
            entry.focus_set()
            return
        if port in self.port_vars[proto]:
            messagebox.showinfo(
                "Port already exists", f"Port {port} is already listed for {proto.upper()}.",
                parent=self
            )
            entry.delete(0, "end")
            return

        self.port_vars[proto][port] = ctk.BooleanVar(value=True)
        entry.delete(0, "end")
        self.show_protocol(proto)
        if hasattr(self, "priority_container"):
            self.refresh_priority_list()

    def remove_protocol_port(self, proto, port):
        if port not in self.port_vars[proto]:
            return
        del self.port_vars[proto][port]
        self.show_protocol(proto)
        if hasattr(self, "priority_container"):
            self.refresh_priority_list()

    def restore_default_ports(self, proto):
        self.port_vars[proto] = {
            port: ctk.BooleanVar(value=True) for port in DEFAULT_PROTOCOLS[proto]
        }
        self.show_protocol(proto)
        if hasattr(self, "priority_container"):
            self.refresh_priority_list()

    def set_all_protocols(self, enabled):
        for proto, variable in self.protocol_vars.items():
            variable.set(enabled)
            self.set_protocol_ports(proto, enabled)

    def sync_client_ports(self):
        try:
            current_ports = self.worker.get_protocol_ports()
        except RuntimeError as error:
            self.log_message(f"Could not sync protocol ports: {error}", "FAILURE")
            messagebox.showerror(
                "Port sync failed", str(error), parent=self
            )
            return

        selected_protocol = self.protocol_selector.get().lower()
        for proto, upstream_ports in current_ports.items():
            previous_vars = self.port_vars[proto]
            custom_ports = set(previous_vars) - set(DEFAULT_PROTOCOLS[proto])
            merged_ports = sorted(set(upstream_ports) | custom_ports)
            updated_vars = {}
            for port in merged_ports:
                existing = previous_vars.get(port)
                updated_vars[port] = existing or ctk.BooleanVar(value=True)
            self.port_vars[proto] = updated_vars
            DEFAULT_PROTOCOLS[proto] = list(upstream_ports)

        self.show_protocol(selected_protocol)
        self.refresh_priority_list()
        settings = self.gather_config_data()
        self.config_data["last_settings"] = settings
        ConfigManager.save_config(self.config_data)
        total_ports = sum(len(ports) for ports in current_ports.values())
        self.log_message(
            f"Synced {total_ports} protocol ports from Windscribe CLI.", "SUCCESS"
        )
        messagebox.showinfo(
            "Ports updated",
            f"Protocol ports were synced from the installed Windscribe client.\n"
            f"{total_ports} available protocol ports loaded.",
            parent=self
        )

    def update_summary(self, proto):
        active = sum(1 for v in self.port_vars[proto].values() if v.get())
        total = len(self.port_vars[proto])
        enabled = bool(self.protocol_vars[proto].get())
        txt = f"{active} of {total} ports" if enabled else f"Off · {active}/{total} ports"
        if proto in self.protocol_labels:
            self.protocol_labels[proto].configure(
                text=txt, text_color="#34d399" if enabled and active else "#94a3b8"
            )
        if proto in getattr(self, "priority_port_labels", {}):
            self.priority_port_labels[proto].configure(
                text=f"{active}/{total} ports"
            )

    def log_message(self, msg, tag):
        ts = datetime.datetime.now().strftime("[%H:%M:%S] ")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", ts + msg + "\n", tag)
        line_count = int(self.log_box.index("end-1c").split(".")[0])
        if line_count > MAX_VISIBLE_LOG_LINES:
            self.log_box.delete("1.0", f"{line_count - RETAINED_LOG_LINES}.0")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def clear_logs(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.txt_success.configure(state="normal")
        self.txt_success.delete("1.0", "end")
        self.txt_success.configure(state="disabled")

    def get_plan(self):
        plan = {}
        allowed_protocols = {"stealth", "wstunnel"} if self.chk_anti_censorship.get() else None
        for proto in self.priority_order:
            if allowed_protocols is not None and proto not in allowed_protocols:
                continue
            if self.protocol_vars[proto].get():
                ports = [p for p, v in self.port_vars[proto].items() if v.get()]
                if ports: plan[proto] = ports
        return plan

    def start_fresh(self):
        self.start_job(False)

    def start_continue(self):
        self.start_job(True)

    def start_job(self, resume):
        plan = self.get_plan()
        if not plan:
            if self.chk_anti_censorship.get():
                messagebox.showwarning(
                    "No stealth protocols selected",
                    "Enable at least one port for Stealth or WStunnel before starting.",
                    parent=self
                )
            else:
                messagebox.showwarning(
                    "No protocols selected",
                    "Enable at least one protocol and port before starting.",
                    parent=self
                )
            return
        try:
            to, sw = int(self.entry_timeout.get()), int(self.entry_speed_wait.get())
        except:
            to, sw = 20, 5

        current_settings = self.gather_config_data()
        self.config_data["last_settings"] = current_settings
        ConfigManager.save_config(self.config_data)

        self.btn_fresh.configure(state="disabled")
        self.btn_continue.configure(state="disabled")
        self.btn_stop.configure(state="normal")

        profile_name = self.entry_save_name.get().strip() or self.combo_profiles.get().strip() or "Manual"
        self.current_profile_name = profile_name

        self.worker.start(plan, resume, to, sw,
                          self.chk_ping.get(),
                          self.chk_down.get(),
                          self.chk_up.get(),
                          self.selected_country,
                          self.selected_city,
                          self.selected_location,
                          bool(self.chk_random_cities.get()),
                          bool(self.chk_random.get()),
                          bool(self.chk_stop_success.get()),
                          profile_name)

    def stop_job(self):
        self.worker.stop()
        self.btn_stop.configure(state="disabled")

    def on_job_finish(self):
        self.after(0, self._reset_btns)

    def _reset_btns(self):
        self.btn_fresh.configure(state="normal")
        self.btn_continue.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.log_message("Job Finished.", "HEADER")
        result_count = self.worker.db.get_row_count()
        self.update_live_dashboard("-", "-", "-", "Ready", 0, result_count)
        if result_count and messagebox.askyesno(
                "Save report", "The test run has finished. Would you like to save a CSV report now?",
                parent=self):
            self.export_csv()

    def export_csv(self):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_profile = "".join(
            c for c in self.current_profile_name if c.isalnum() or c in (" ", "-", "_")
        ).strip().replace(" ", "_") or "Manual"
        output_path = filedialog.asksaveasfilename(
            parent=self,
            title="Save CSV report",
            initialdir=APP_PATH,
            initialfile=f"{safe_profile}_{timestamp}.csv",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not output_path:
            return

        count, path = self.worker.db.export_to_csv(self.current_profile_name, output_path)
        if count == -1:
            messagebox.showerror("Error", f"Could not save CSV.\n{path}", parent=self)
        else:
            messagebox.showinfo("Export", f"Exported {count} rows.\nSaved to:\n{path}", parent=self)


if __name__ == "__main__":
    app = App()
    app.mainloop()