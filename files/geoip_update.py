#!/usr/bin/python3

import requests
import gzip
import sys

url = 'https://dl.miyuru.lk/geoip/'

dbs = {
    'GeoIP2-City': {
        'output_file': '/usr/share/GeoIP/GeoIP-City.dat',
        'download_file': 'dbip/city/dbip.dat.gz'
    },
    'GeoIP2-Country': {
        'output_file': '/usr/share/GeoIP/GeoIP-Country.dat',
        'download_file': 'dbip/country/dbip.dat.gz'
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
