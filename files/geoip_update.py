#!/usr/bin/python3

import requests
import gzip
import sys
import os
import logging
import argparse
import time
import datetime


class GeoIp:

    def __init__(self):
        """
        """
        self.args = {}
        self.parse_args()

        self.output_dir = self.args.directory
        self.dry_run = self.args.dry_run
        self.log_level = self.args.log_level

        self.cache_minutes = 30240  # 3 weeks

        self.datetime = time.strftime('%Y%m%d-%H%M')
        self.datetime_readable = time.strftime("%Y-%m-%d")

        self.setup_logging()

        self.cache_directory = "/var/cache/geoip"
        self.cache_file_name = os.path.join(self.cache_directory, "geoip.run")

        self.url = 'https://dl.miyuru.lk/geoip'

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

        self.args = p.parse_args()

    def setup_logging(self):
        """
            Konfiguriert das Logging mit dem gegebenen Log-Level.
        """
        log_level_numeric = getattr(logging, self.log_level)  # Umwandlung von Text in Level

        # DEBUG-Format (kurzer Zeitstempel)
        debug_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", "%H:%M:%S")

        # Standard-Format für INFO+
        standard_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S")

        # Konsolen-Logging
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level_numeric)
        console_handler.setFormatter(debug_formatter if log_level_numeric == logging.DEBUG else standard_formatter)

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

        out_of_cache = self.cache_valid(cache_file_remove=True)

        if out_of_cache:
            status_code, output = self.download_data()

            if status_code == 200 and not self.dry_run:
                self.update_cache_information()
            else:
                pass

        else:
            logging.info("The current data is not yet out of date.")
            self.download_data()

    def download_data(self):
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

        # extract http result codes
        # unifed all list entries and get highest value
        _sorted = sorted(list(set(list(result.values()))), reverse=True)

        return_code = _sorted[0]
        logging.debug(return_code)

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
