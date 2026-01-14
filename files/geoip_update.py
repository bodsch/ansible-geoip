#!/usr/bin/python3

import argparse
import datetime
import gzip
import logging
import os
import sys
import tarfile
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

try:
    import grp
    import pwd
except Exception:
    pwd = None  # type: ignore
    grp = None  # type: ignore

import requests


class GeoIPConfigError(Exception):
    """
    Raised when parsing a GeoIP.conf-style configuration fails.

    This exception is used to signal malformed or missing configuration values
    (e.g., invalid AccountID, empty LicenseKey, missing EditionIDs).
    """

    pass


class GeoIp:
    """
    GeoIP database updater for MaxMind GeoLite2 (mmdb) and legacy GeoIP (dat) formats.

    Features:
      - Downloads GeoLite2 databases using a MaxMind license key (GeoIP.conf).
      - Optional legacy mode downloads prebuilt legacy databases (gzip) from dl.miyuru.lk.
      - Simple time-based caching using a marker file in /var/cache/geoip.
      - Supports dry-run mode and configurable log levels.

    Notes:
      - The script uses a local cache marker file (geoip.run / geoip.legacy.run). If that file
        is younger than `cache_minutes`, downloads are skipped.
      - In non-legacy mode, a GeoIP.conf is required (default: /etc/GeoIP.conf).
    """

    def __init__(self) -> None:
        """
        Initialize the updater and parse CLI arguments.

        This sets instance configuration such as output directory, dry-run mode, log level,
        legacy mode, and config file path. It also initializes cache handling and logging.

        Returns:
            None
        """
        self.args = {}
        self.parse_args()

        self.output_dir = self.args.directory
        self.dry_run = self.args.dry_run
        self.log_level = self.args.log_level
        self.legacy = self.args.legacy
        self.config_file = self.args.config_file

        # NEW: ownership config (empty means: don't chown)
        self.owner: str = (self.args.owner or "").strip()
        self.group: str = (self.args.group or "").strip()

        self.cache_minutes = 30240  # 3 weeks
        self.cache_minutes = 10080  # 1 week

        self.datetime = time.strftime("%Y%m%d-%H%M")
        self.datetime_readable = time.strftime("%Y-%m-%d")

        self.setup_logging()

        self.cache_directory = "/var/cache/geoip"
        # self.cache_file_name = os.path.join(self.cache_directory, "geoip.run")
        if self.legacy:
            cache_file_name = "geoip.legacy.run"
        else:
            cache_file_name = "geoip.run"
        self.cache_file_name = os.path.join(self.cache_directory, cache_file_name)

        self.url = "https://dl.miyuru.lk/geoip"

        # Supported editions (default set if not provided via GeoIP.conf)
        self.geoip_editions = {
            "City": "GeoLite2-City",
            "Country": "GeoLite2-Country",
            "ASN": "GeoLite2-ASN",
        }

        # License key is populated when parsing config / downloading.
        self.license_key: Optional[str] = None

    def parse_args(self) -> None:
        """
        Parse command-line arguments and store them in `self.args`.

        Supported options:
          - --directory: destination directory for extracted databases
          - --dry-run: skip downloads/extraction but still perform logic
          - --log-level: logging verbosity
          - --config-file: GeoIP.conf path (non-legacy mode)
          - --legacy: download legacy DBs instead of mmdb files

        Returns:
            None
        """
        p = argparse.ArgumentParser(description="Download GeoIP files")

        p.add_argument(
            "-d",
            "--directory",
            required=False,
            help="directory to store geoip data.",
            default="/usr/share/GeoIP",
        )

        p.add_argument(
            "--dry-run",
            required=False,
            help="do nothing",
            default=False,
            action="store_true",
        )
        p.add_argument(
            "--log-level",
            type=str,
            default="INFO",
            choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            help="Setzt das Log-Level (default: INFO)",
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
            action="store_true",
        )
        p.add_argument(
            "--owner",
            type=str,
            default="",
            help="Set owner (user name or numeric uid) for extracted files",
        )
        p.add_argument(
            "--group",
            type=str,
            default="",
            help="Set group (group name or numeric gid) for extracted files",
        )

        self.args = p.parse_args()

    def setup_logging(self) -> None:
        """
        Configure the root logger and silence noisy HTTP client loggers.

        - Root logger outputs to stdout.
        - httpcore and httpx loggers are reduced to WARNING and do not propagate.

        Returns:
            None
        """
        log_level_numeric = getattr(
            logging, self.log_level
        )  # Umwandlung von Text in Level

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

    def run(self) -> None:
        """
        Main execution method.

        Workflow:
          1) Ensure cache directory exists.
          2) Determine whether cached state is expired (or missing).
          3) If expired:
              - legacy mode: download legacy DBs
              - non-legacy: parse GeoIP.conf and download GeoLite2 DBs
          4) On success (HTTP 200) and not dry-run: update cache marker file.

        Returns:
            None

        Raises:
            FileNotFoundError: If non-legacy mode and the config file does not exist.
            GeoIPConfigError: If config parsing fails.
            requests.RequestException: If network requests fail (depending on call path).
            Exception: If a download returns non-200 in `download_geoip_db`.
        """
        logging.debug("GeoIp::run()")

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

    def parse_geoip_conf(self) -> Dict[str, Any]:
        """
        Parse a GeoIP.conf-style configuration file.

        Expected keys:
          - AccountID (numeric)
          - LicenseKey (non-empty)
          - EditionIDs (space-separated list)

        Unknown keys are ignored. Malformed lines (without whitespace) are ignored
        and logged as a warning.

        Returns:
            dict[str, Any]: Parsed configuration with keys:
                - "AccountID": int
                - "LicenseKey": str
                - "EditionIDs": list[str]

        Raises:
            FileNotFoundError: If the config file does not exist.
            GeoIPConfigError: If required values are invalid or UTF-8 decoding fails.
            SystemExit: If required keys are missing (the original implementation exits).
        """
        logging.debug("GeoIp::parse_geoip_conf()")

        if not os.path.exists(self.config_file):
            raise FileNotFoundError(f"GeoIP config file not found: {self.config_file}")

        logging.debug(f" read config file: {self.config_file}")

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

    def download_data(self, config: Dict[str, Any]) -> Tuple[int, str]:
        """
        Download and extract GeoLite2 databases (mmdb) based on the provided configuration.

        For each requested edition:
          - downloads `<edition>.tar.gz` into the cache directory
          - extracts `.mmdb` file(s) into `self.output_dir`

        Args:
            config: Parsed configuration (from :meth:`parse_geoip_conf`), must include:
                - "LicenseKey": str
                - "EditionIDs": list[str] (optional; falls back to `self.geoip_editions`)

        Returns:
            tuple[int, str]: (http_status, message)
                http_status: The highest HTTP status code observed among editions.
                    - 200 indicates all downloads succeeded.
                message: Human-readable summary message.

        Raises:
            requests.RequestException: On request errors (via `requests.get` / `raise_for_status`).
            Exception: If a download returns non-200 in `download_geoip_db`.
        """
        logging.debug(f"GeoIp::download_data({config})")

        result: Dict[str, int] = {}
        geoip_editions = config.get("EditionIDs") or self.geoip_editions

        self.license_key = config.get("LicenseKey")

        for edition in geoip_editions:
            logging.debug(f"Download {edition} ...")
            result[edition] = {}

            if self.dry_run:
                logging.info(
                    f" - dry-run. The download of {edition}.tar.gz is skipped."
                )
                result[edition] = 200
            else:
                status_code, tarball = self.download_geoip_db(
                    edition_id=edition, dest_dir=self.cache_directory
                )
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

    def download_legacy_data(self) -> Tuple[int, str]:
        """
        Download legacy GeoIP databases (gzip) from dl.miyuru.lk and write `.dat` files.

        Legacy DBs downloaded:
          - City  -> GeoIP-City.dat
          - Country -> GeoIP-Country.dat

        Returns:
            tuple[int, str]: (http_status, message)
                http_status: The highest HTTP status code observed.
                message: Human-readable summary message.

        Raises:
            requests.RequestException: On request errors.
            OSError: On file write errors.
        """
        logging.debug("GeoIp::download_legacy_data()")

        result: Dict[str, int] = {}

        dbs = {
            "GeoIP2-City": {
                "output_file": "GeoIP-City.dat",
                "download_file": "dbip/city/dbip.dat.gz",
            },
            "GeoIP2-Country": {
                "output_file": "GeoIP-Country.dat",
                "download_file": "dbip/country/dbip.dat.gz",
            },
        }

        for k, v in dbs.items():
            # logging.info(f" - {k}")

            result[k] = {}

            download_url = f"{self.url}/{v.get('download_file')}"
            safe_as = os.path.join(self.output_dir, v.get("output_file"))

            logging.info(f" - download from: {download_url}")

            if self.dry_run:
                logging.info(
                    f" - dry-run. The download of {v.get('output_file')} is skipped."
                )
                result[k] = 200
            else:
                logging.info(f" - safe as file : {safe_as}")

                r = requests.get(download_url)

                result[k] = r.status_code

                if r.status_code == requests.codes.ok:
                    with open(safe_as, "wb") as f:
                        f.write(gzip.decompress(r.content))

                else:
                    logging.error(f"Download failed for {k}: {r.status_code}\n")
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

    def cache_valid(self, cache_file_remove: bool = True) -> bool:
        """
        Check cache marker file age against the configured cache window.

        Behavior:
          - If dry-run is enabled, this always returns True (treated as "out of cache").
          - If cache marker does not exist, returns True.
          - If marker exists: compares marker ctime to now and returns True if expired.
          - If expired and `cache_file_remove` is True: removes the cache marker file.

        Args:
            cache_file_remove: Whether to remove the marker file when it is expired.

        Returns:
            bool: True if the cache is expired or missing ("out of cache"),
            False if the cache is still valid.
        """
        logging.debug(f"GeoIp::cache_valid(cache_file_remove={cache_file_remove})")

        if self.dry_run:
            logging.debug(" - dry-run. skip cache validation.")
            return True

        out_of_cache = False

        if os.path.isfile(self.cache_file_name):
            """ """
            logging.debug(f"read cache file '{self.cache_file_name}'")

            now = datetime.datetime.now()
            creation_time = datetime.datetime.fromtimestamp(
                os.path.getctime(self.cache_file_name)
            )
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

        logging.debug("cache is {0}valid".format("not " if out_of_cache else ""))

        return out_of_cache

    def update_cache_information(self) -> None:
        """
        Create or update the cache marker file.

        The marker file is used to track the last successful update time via filesystem ctime.

        Returns:
            None

        Raises:
            OSError: If the marker file cannot be created/written.
        """
        logging.debug("GeoIp::update_cache_information()")

        open(self.cache_file_name, "w")

    def create_directory(self, directory: str, mode: Optional[str] = None) -> bool:
        """
        Ensure a directory exists and optionally apply permissions.

        Args:
            directory: Directory path to create.
            mode: Optional octal permission string (e.g. "0755"). If provided, chmod is applied.

        Returns:
            bool: True if the directory exists after this call, otherwise False.

        Raises:
            OSError: If creation or chmod fails (except FileExistsError is ignored).
            ValueError: If `mode` is provided but cannot be parsed as octal.
        """
        logging.debug(f"GeoIp::create_directory({directory}, {mode})")

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

    def download_geoip_db(self, edition_id: str, dest_dir: str) -> Tuple[int, Path]:
        """
        Download a GeoLite2 tarball for a given edition from MaxMind.

        URL format:
            https://download.maxmind.com/app/geoip_download?edition_id=<edition_id>&license_key=<license>&suffix=tar.gz

        Args:
            edition_id: Edition identifier (e.g. "GeoLite2-City", "GeoLite2-Country", "GeoLite2-ASN").
            dest_dir: Destination directory for the downloaded tarball.

        Returns:
            tuple[int, Path]: (status_code, tarball_path)
                status_code: HTTP status code (expected 200).
                tarball_path: Filesystem path of the downloaded tar.gz archive.

        Raises:
            requests.RequestException: If the request fails or `raise_for_status()` triggers.
            Exception: If a non-200 status code is returned after the request.
            OSError: If the tarball cannot be written to disk.
        """
        logging.debug(f"GeoIp::download_geoip_db({edition_id}, {dest_dir})")

        if not self.license_key:
            raise GeoIPConfigError("Missing LicenseKey (license key not initialized).")

        # url = f"https://download.maxmind.com/app/geoip_download?edition_id={edition_id}&license_key={self.license_key}&suffix=tar.gz"
        url = (
            "https://download.maxmind.com/app/geoip_download"
            f"?edition_id={edition_id}&license_key={self.license_key}&suffix=tar.gz"
        )

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

    def extract_mmdb(
        self, tarball_path: Union[str, Path], dest_dir: Union[str, Path]
    ) -> None:
        """
        Extract `.mmdb` files from a tar.gz archive into the destination directory.

        Returns:
            None
        """
        logging.debug(f"GeoIp::extract_mmdb({tarball_path}, {dest_dir})")

        extracted: List[Path] = []
        dest_dir_path = Path(dest_dir)

        with tarfile.open(tarball_path, "r:gz") as tar:
            for member in tar.getmembers():
                # only extract regular files ending with .mmdb
                if not (member.isfile() and member.name.endswith(".mmdb")):
                    continue

                safe_name = os.path.basename(member.name)

                # avoid mutating TarInfo when replace() exists
                try:
                    member = member.replace(name=safe_name)
                except AttributeError:
                    member.name = safe_name

                # future-proof: Python 3.14 default filter is 'data'
                try:
                    tar.extract(member, path=dest_dir, filter="data")
                except TypeError:
                    tar.extract(member, path=dest_dir)

                extracted_path = dest_dir_path / safe_name
                extracted.append(extracted_path)

        # Apply ownership to extracted files only
        if extracted and (self.owner or self.group):
            for p in extracted:
                try:
                    self._chown_path(p, self.owner, self.group)
                except PermissionError as e:
                    # harte Fehlermeldung, weil Ownership gefordert ist
                    raise
                except FileNotFoundError:
                    # falls das Archiv "komisch" war; surfacing ist meist sinnvoll
                    raise

    def _resolve_uid_gid(self, owner: str, group: str) -> Tuple[int, int]:
        """
        Resolve owner/group to numeric uid/gid.

        Args:
            owner: User name or numeric uid (empty string means "unchanged").
            group: Group name or numeric gid (empty string means "unchanged").

        Returns:
            tuple[int, int]: (uid, gid)
                uid/gid are -1 if not specified (meaning: keep existing value).

        Raises:
            RuntimeError: If called on a platform without chown support.
            ValueError: If owner/group cannot be resolved.
        """
        logging.debug(f"GeoIp::_resolve_uid_gid(owner={owner}, group={group})")

        if not hasattr(os, "chown"):
            raise RuntimeError("os.chown is not available on this platform.")

        uid = -1
        gid = -1

        if owner:
            if owner.isdigit():
                uid = int(owner)
            else:
                if pwd is None:
                    raise ValueError(
                        "User name resolution not available (pwd module missing)."
                    )
                uid = pwd.getpwnam(owner).pw_uid

        if group:
            if group.isdigit():
                gid = int(group)
            else:
                if grp is None:
                    raise ValueError(
                        "Group name resolution not available (grp module missing)."
                    )
                gid = grp.getgrnam(group).gr_gid

        return uid, gid

    def _chown_path(self, path: Union[str, Path], owner: str, group: str) -> None:
        """
        Apply ownership to a single file path.

        Args:
            path: File path to change ownership for.
            owner: User name or numeric uid (empty means unchanged).
            group: Group name or numeric gid (empty means unchanged).

        Returns:
            None

        Raises:
            PermissionError: If the current process is not permitted to chown.
            FileNotFoundError: If the file path does not exist.
            ValueError: If owner/group cannot be resolved.
        """
        logging.debug(f"GeoIp::_chown_path(path={path}, owner={owner}, group={group})")

        if not owner and not group:
            return

        if self.dry_run:
            logging.info(f" - dry-run. chown skipped for {path}")
            return

        uid, gid = self._resolve_uid_gid(owner, group)
        os.chown(str(path), uid, gid)


if __name__ == "__main__":
    """ """
    r = GeoIp()
    r.run()
