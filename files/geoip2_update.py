#!/usr/bin/python3

import requests
import datetime
import gzip
import sys

url = 'https://download.db-ip.com/free/'
date = datetime.datetime.now().strftime('%Y-%m')

dbs = {
    'GeoIP2-City': {
        'output_file': '/usr/share/GeoIP/GeoIP2-City.mmdb',
        'download_file': f'dbip-city-lite-{date}.mmdb.gz'
    },
    'GeoIP2-ASN': {
        'output_file': '/usr/share/GeoIP/GeoIP2-ASN.mmdb',
        'download_file': f'dbip-asn-lite-{date}.mmdb.gz'
    },
    'GeoIP2-Country': {
        'output_file': '/usr/share/GeoIP/GeoIP2-Country.mmdb',
        'download_file': f'dbip-country-lite-{date}.mmdb.gz'
    },
}

for k, v in dbs.items():
    print(k)
    r = requests.get(url + v['download_file'])
    if r.status_code == requests.codes.ok:
        with open(v['output_file'], 'wb') as f:
            f.write(gzip.decompress(r.content))
    else:
        sys.stderr.write(f'Download failed for {k}: {r.status_code}\n')
        sys.exit(1)


"""
cat >> /etc/cron.d/geoip2-update << EOF
MAILTO=root
$(( $RANDOM % 59 + 0 )) $(( $RANDOM % 23 + 0 )) 28 * *     root  /usr/local/sbin/geoip2_update.py
EOF
"""
