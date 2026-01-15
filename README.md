
# ansible-role `ansible-geoip`

Installs legacy geoip data from [miyuru.lk](https://www.miyuru.lk/geoiplegacy) or from [download.maxmind.com](https://download.maxmind.com/app/geoip_download)

## state

WIP

## Requirements & Dependencies

Ansible Collections

- [bodsch.core](https://github.com/bodsch/ansible-collection-core)

```bash
ansible-galaxy collection install bodsch.core
```
or
```bash
ansible-galaxy collection install --requirements-file collections.yml
```

## supported operating systems

* Arch Linux
* Debian based

## usage 

```yaml
geoip_force: false

geoip_destination: /usr/share/GeoIP

geoip_update_service:
  name: geoip-update
  enabled: true
  state: started

geoip_files:
  owner: ""
  group: ""

geoip_legacy: true

geoip_maxmind:
  account_id: ""
  license_key: ""
  edition_ids:
    - GeoLite2-ASN
    - GeoLite2-City
    - GeoLite2-Country

geoip_databases:
  db_ip:
    country:
      both: true
      ipv4: true
      ipv6: false
    city:
      both: true
      ipv4: false
      ipv6: true
  maxmind:
    asn:
      both: false
      ipv4: false
      ipv6: false
    country:
      both: false
      ipv4: false
      ipv6: false
    city:
      both: false
      ipv4: false
      ipv6: false
```


## Contribution

Please read [Contribution](CONTRIBUTING.md)

## Development,  Branches (Git Tags)

The `master` Branch is my *Working Horse* includes the "latest, hot shit" and can be complete broken!

If you want to use something stable, please use a [Tagged Version](https://github.com/bodsch/ansible-geoip/tags)!

---

## Author

- Bodo Schulz

## License

[Apache](LICENSE)

**FREE SOFTWARE, HELL YEAH!**
