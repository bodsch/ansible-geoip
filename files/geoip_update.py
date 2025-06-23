#!/usr/bin/python3

import requests
import gzip
import sys
import os
import logging
import argparse
import time
import datetime
from pathlib import Path
import tarfile


class GeoIPConfigError(Exception):
    """Custom exception for GeoIP config parsing errors."""
    pass


class GeoIp:

    def __init__(self):
        """
        """
        self.args = {}
        self.parse_args()

        self.output_dir = self.args.directory
        self.dry_run = self.args.dry_run
        self.log_level = self.args.log_level
        self.legacy = self.args.legacy
        self.config_file = self.args.config_file

        self.cache_minutes = 30240  # 3 weeks
        self.cache_minutes = 10080  # 1 week

        self.datetime = time.strftime('%Y%m%d-%H%M')
        self.datetime_readable = time.strftime("%Y-%m-%d")

        self.setup_logging()

        self.cache_directory = "/var/cache/geoip"
        # self.cache_file_name = os.path.join(self.cache_directory, "geoip.run")
        if self.legacy:
            cache_file_name = "geoip.legacy.run"
        else:
            cache_file_name = "geoip.run"
        self.cache_file_name = os.path.join(self.cache_directory, cache_file_name)

        self.url = 'https://dl.miyuru.lk/geoip'

        # Unterstützte Editionen
        self.geoip_editions = {
            "City": "GeoLite2-City",
            "Country": "GeoLite2-Country",
            "ASN": "GeoLite2-ASN",
        }

    def parse_args(self):
        """
            parse arguments
        """
        p = argparse.ArgumentParser(description='bsky bot')

        p.add_argument(
            "-d",
            "--directory",
            required=False,
            help="directory to store geoip data.",
            default="/usr/share/GeoIP"
        )

        p.add_argument(
            "--dry-run",
            required=False,
            help="do nothing",
            default=False,
            action='store_true',
        )
        p.add_argument(
            "--log-level",
            type=str,
            default="INFO",
            choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            help="Setzt das Log-Level (default: INFO)"
        )
        p.add_argument(
            "--config-file",
            type=str,
            default="/etc/GeoIP.conf",
        )
        p.add_argument(
            "--legacy",
            required=False,
            help="use legacy databases",
            default=False,
            action='store_true',
        )

        self.args = p.parse_args()

    def setup_logging(self):
        """
            Konfiguriert das Logging mit dem gegebenen Log-Level.
        """
        log_level_numeric = getattr(logging, self.log_level)  # Umwandlung von Text in Level

        # DEBUG-Format (kurzer Zeitstempel)
        # debug_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", "%H:%M:%S")

        # Standard-Format für INFO+
        # standard_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S")

        # Konsolen-Logging
        console_handler = logging.StreamHandler(sys.stdout)
        # console_handler.setLevel(log_level_numeric)
        # console_handler.setFormatter(debug_formatter if log_level_numeric == logging.DEBUG else standard_formatter)

        # Haupt-Logger konfigurieren
        logger = logging.getLogger()
        logger.setLevel(log_level_numeric)
        logger.addHandler(console_handler)

        # httpcore-Logger
        httpcore_logger = logging.getLogger("httpcore")
        httpcore_logger.setLevel(logging.WARNING)
        httpcore_logger.propagate = False

        # httpx-Logger
        httpx_logger = logging.getLogger("httpx")
        httpx_logger.setLevel(logging.WARNING)
        httpx_logger.propagate = False

    def run(self):
        """
        """
        logging.info(f"geoip update {self.datetime_readable} ...")

        self.create_directory(self.cache_directory)

        out_of_cache = self.cache_valid(cache_file_remove=False)

        if out_of_cache:
            if self.legacy:
                status_code, output = self.download_legacy_data()
            else:
                geoip_config = self.parse_geoip_conf()
                status_code, output = self.download_data(config=geoip_config)

            if status_code == 200 and not self.dry_run:
                self.update_cache_information()
            else:
                pass

        else:
            logging.info("The current data is not yet out of date.")

    def parse_geoip_conf(self):
        """
        Parses a GeoIP.conf-style configuration file and returns a dict
        with keys: AccountID (int), LicenseKey (str), and EditionIDs (list).
        """
        if not os.path.exists(self.config_file):
            raise FileNotFoundError(f"GeoIP config file not found: {self.config_file}")

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                raw_lines = f.readlines()

            # Vorverarbeitung: leere Zeilen und Kommentare entfernen
            lines = [
                line.strip()
                for line in raw_lines
                if line.strip() and not line.strip().startswith("#")
            ]

            config = {}
            malformed_lines = []
            allowed_keys = {"AccountID", "LicenseKey", "EditionIDs"}

            for line in lines:
                if " " not in line:
                    malformed_lines.append(line)
                    continue

                key, value = line.split(None, 1)

                if key not in allowed_keys:
                    continue  # optional: log unknown keys

                if key == "AccountID":
                    if not value.isdigit():
                        raise GeoIPConfigError("Invalid AccountID: must be numeric")
                    config["AccountID"] = int(value)

                elif key == "LicenseKey":
                    if not value:
                        raise GeoIPConfigError("LicenseKey is empty")
                    config["LicenseKey"] = value

                elif key == "EditionIDs":
                    editions = value.strip().split()
                    if not editions:
                        raise GeoIPConfigError("EditionIDs list is empty")
                    config["EditionIDs"] = editions

            if malformed_lines:
                logging.warning(
                    f"Ignoring malformed lines: {', '.join(malformed_lines)}"
                )

            # Pflichtfelder prüfen
            required = {"AccountID", "LicenseKey", "EditionIDs"}
            missing = required - config.keys()
            if missing:
                logging.debug(f"Missing required keys: {', '.join(missing)}")
                # raise GeoIPConfigError(f"Missing required keys: {', '.join(missing)}")
                sys.exit(1)

            return config

        except UnicodeDecodeError:
            raise GeoIPConfigError("File is not valid UTF-8 text")
        except GeoIPConfigError:
            raise
        except Exception as e:
            raise GeoIPConfigError(f"Unexpected failure while parsing: {e}")

    def parse_geoip_conf_old(self):
        """
        Parses a GeoIP.conf-style configuration file and returns a dict
        with keys: AccountID, LicenseKey, and EditionIDs (as list).

        Returns:
            dict: Parsed configuration.

        Raises:
            FileNotFoundError: If the file does not exist.
            GeoIPConfigError: For missing or malformed config values.
        """
        if not os.path.exists(self.config_file):
            raise FileNotFoundError(f"GeoIP config file not found: {self.config_file}")

        config = {}

        try:
            with open(self.config_file, "r") as f:
                for line in f:
                    line = line.strip()

                    # Skip comments and blank lines
                    if not line or line.startswith("#"):
                        continue

                    if " " not in line:
                        logging.error(f"Malformed line: '{line}'")
                        continue
                        # raise GeoIPConfigError(f"Malformed line: '{line}'")

                    key, value = line.split(None, 1)

                    if key == "AccountID":
                        if not value.isdigit():
                            raise GeoIPConfigError("Invalid AccountID: must be numeric")
                        config["AccountID"] = int(value)

                    elif key == "LicenseKey":
                        if not value:
                            raise GeoIPConfigError("LicenseKey is empty")
                        config["LicenseKey"] = value

                    elif key == "EditionIDs":
                        editions = value.strip().split()
                        if not editions:
                            raise GeoIPConfigError("EditionIDs list is empty")
                        config["EditionIDs"] = editions

                    else:
                        # Optional: ignore unknown keys or collect them
                        config[key] = value

            # Validate required fields
            required_keys = {"AccountID", "LicenseKey", "EditionIDs"}
            missing = required_keys - config.keys()
            if missing:
                raise GeoIPConfigError(f"Missing required keys: {', '.join(missing)}")

            return config

        except UnicodeDecodeError:
            raise GeoIPConfigError("File is not valid UTF-8 text")
        except Exception as e:
            raise GeoIPConfigError(f"Failed to parse config: {e}")

    def download_data(self, config: dict):
        """
        """
        result = {}
        geoip_editions = config.get("EditionIDs") or self.geoip_editions

        self.license_key = config.get("LicenseKey")

        for edition in geoip_editions:
            logging.debug(f"Download {edition} ...")
            result[edition] = {}

            if self.dry_run:
                logging.info(f" - dry-run. The download of {edition}.tar.gz is skipped.")
                result[edition] = 200
            else:
                status_code, tarball = self.download_geoip_db(edition_id=edition, dest_dir=self.cache_directory)
                result[edition] = status_code

                if status_code == 200:
                    self.extract_mmdb(tarball, self.output_dir)
            # tarball.unlink()  # tar.gz löschen

        logging.debug(result)

        # extract http result codes
        # unifed all list entries and get highest value
        _sorted = sorted(list(set(list(result.values()))), reverse=True)

        return_code = _sorted[0]

        if return_code == 200:
            return_msg = "The downloads were successful."
        else:
            return_msg = "At least one download was faulty."

        return return_code, return_msg

    def download_legacy_data(self):
        """
        """
        result = {}

        dbs = {
            'GeoIP2-City': {
                'output_file': 'GeoIP-City.dat',
                'download_file': 'dbip/city/dbip.dat.gz'
            },
            'GeoIP2-Country': {
                'output_file': 'GeoIP-Country.dat',
                'download_file': 'dbip/country/dbip.dat.gz'
            },
        }

        for k, v in dbs.items():
            # logging.info(f" - {k}")

            result[k] = {}

            download_url = f"{self.url}/{v.get('download_file')}"
            safe_as = os.path.join(self.output_dir, v.get('output_file'))

            logging.info(f" - download from: {download_url}")

            if self.dry_run:
                logging.info(f" - dry-run. The download of {v.get('output_file')} is skipped.")
                result[k] = 200
            else:
                logging.info(f" - safe as file : {safe_as}")

                r = requests.get(download_url)

                result[k] = r.status_code

                if r.status_code == requests.codes.ok:
                    with open(safe_as, 'wb') as f:
                        f.write(gzip.decompress(r.content))

                else:
                    logging.error(f'Download failed for {k}: {r.status_code}\n')
                    # sys.exit(1)

        logging.debug(result)

        # extract http result codes
        # unifed all list entries and get highest value
        _sorted = sorted(list(set(list(result.values()))), reverse=True)

        return_code = _sorted[0]

        if return_code == 200:
            return_msg = "The downloads were successful."
        else:
            return_msg = "At least one download was faulty."

        return return_code, return_msg

    def cache_valid(self, cache_file_remove=True) -> bool:
        """
            read local file and check the creation time against local time

            returns 'False' when cache are out of sync
        """
        if self.dry_run:
            return True

        out_of_cache = False

        if os.path.isfile(self.cache_file_name):
            """
            """
            logging.debug(msg=f"read cache file '{self.cache_file_name}'")
            now = datetime.datetime.now()
            creation_time = datetime.datetime.fromtimestamp(os.path.getctime(self.cache_file_name))
            diff = now - creation_time
            # define the difference from now to the creation time in minutes
            cached_time = diff.total_seconds() / 60
            out_of_cache = cached_time > self.cache_minutes

            logging.debug(msg=f" - now            {now}")
            logging.debug(msg=f" - creation_time  {creation_time}")
            logging.debug(msg=f" - cached since   {cached_time}")
            logging.debug(msg=f" - out of cache   {out_of_cache}")

            if out_of_cache and cache_file_remove:
                os.remove(self.cache_file_name)
        else:
            out_of_cache = True

        logging.debug(msg="cache is {0}valid".format('not ' if out_of_cache else ''))

        return out_of_cache

    def update_cache_information(self):
        """
            create or update the cache information file
        """
        open(self.cache_file_name, "w")

    def create_directory(self, directory, mode=None):
        """
        """
        try:
            os.makedirs(directory, exist_ok=True)
        except FileExistsError:
            pass

        if mode is not None:
            os.chmod(directory, int(mode, base=8))

        if os.path.isdir(directory):
            return True
        else:
            return False

    def download_geoip_db(self, edition_id, dest_dir):
        """
        """
        logging.debug(f"download_geoip_db({edition_id}, {dest_dir})")

        url = f"https://download.maxmind.com/app/geoip_download?edition_id={edition_id}&license_key={self.license_key}&suffix=tar.gz"
        response = requests.get(url, stream=True)
        response.raise_for_status()

        status_code = response.status_code

        if status_code != 200:
            raise Exception(f"Fehler beim Download ({edition_id}): {status_code}")

        tarball_path = Path(dest_dir) / f"{edition_id}.tar.gz"

        with open(tarball_path, "wb") as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)

        return (status_code, tarball_path)

    def extract_mmdb(self, tarball_path, dest_dir):
        logging.debug(f"extract_mmdb({tarball_path}, {dest_dir})")

        with tarfile.open(tarball_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith(".mmdb"):
                    member.name = os.path.basename(member.name)  # Pfad entfernen
                    tar.extract(member, path=dest_dir)
                    # logging.debug(f"Extrahiert: {member.name}")


if __name__ == '__main__':
    """
    """
    r = GeoIp()
    r.run()

"""
>>> current_time = datetime.datetime.now()
>>> new_time =  current_time + datetime.timedelta(minutes=cache_minutes)
>>> print(new_time)
"""
