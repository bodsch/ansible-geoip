# python 3 headers, required if submitting to Ansible

# (c) 2025, Bodo Schulz <bodo@boone-schulz.de>
# Apache (see LICENSE or https://opensource.org/licenses/Apache-2.0)

from __future__ import absolute_import, division, print_function

__metaclass__ = type


from ansible.utils.display import Display

display = Display()

_STR_WRAPPERS = {
    "AnsibleUnsafeText",
    "AnsibleUnicode",
    "AnsibleVaultEncryptedUnicode",
    "_AnsibleTaggedStr",
}


class FilterModule(object):
    """
    Ansible file jinja2 tests
    """

    def filters(self):
        return {
            "geoip_owner": self.geoip_owner,
            "geoip_group": self.geoip_group,
            "geoip_downloads": self.geoip_downloads,
            "geoip_filename": self.geoip_filename,
        }

    def geoip_owner(self, data, default="root"):
        """ """
        display.vv(f"geoip_owner({data}, default={default})")

        result = default

        if data is None:
            return default

        t = type(data)

        # String-ähnliche Wrapper (z.B. AnsibleUnsafeText)
        if isinstance(data, str) or t.__name__ in _STR_WRAPPERS:
            if len(data) == 0:
                result = default
            else:
                result = data

        # display.vv(f"= result: '{result}' {type(result)}")
        return result

    def geoip_group(self, data, default="root"):
        """ """
        display.vv(f"geoip_group({data}, default={default})")

        result = default

        if data is None:
            return default

        t = type(data)

        # String-ähnliche Wrapper (z.B. AnsibleUnsafeText)
        if isinstance(data, str) or t.__name__ in _STR_WRAPPERS:
            if len(data) == 0:
                result = default
            else:
                result = data

        # display.vv(f"= result: '{result}' {type(result)}")
        return result

    def geoip_downloads(self, data):
        """
        return a list of files
        """
        display.vv(f"geoip_downloads({data})")
        result = []

        result = self.expand_and_clean(data)
        result = self.generate_paths(result)

        display.vv(f" = result {result}")
        return result

    def geoip_filename(self, data):
        """
        return a list of files
        """
        display.vv(f"geoip_filename({data})")

        *_, db_type, filename = data.strip("/").split("/")

        display.v(f" - {filename}")

        filename = filename.replace(".dat.gz", "")

        result = f"{filename}_{db_type}.dat.gz"

        display.vv(f" = result {result}")

        return result

    def expand_and_clean(self, data):
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                if isinstance(value, dict):
                    # Check for "both: true"
                    if value.get("both") is True:
                        value["ipv4"] = True
                        value["ipv6"] = True
                    # Entferne "both" komplett
                    value.pop("both", None)
                    # Rekursiv bereinigen
                    cleaned = self.expand_and_clean(value)
                    if cleaned:  # nur behalten, wenn was übrig ist
                        result[key] = cleaned
                elif value is True:
                    result[key] = True
            return result
        return data if data is True else None

    def generate_paths(self, data, prefix=[]):
        """ """
        display.vv(f"generate_paths({data}, {prefix})")
        paths = []
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, dict) and set(value.keys()).issubset(
                    {"ipv4", "ipv6"}
                ):
                    provider = prefix[-1].replace("_", "")
                    database_type = key
                    ipv4 = value.get("ipv4", False)
                    ipv6 = value.get("ipv6", False)

                    if ipv4 and ipv6:
                        paths.append(f"{provider}/{database_type}/{provider}.dat.gz")
                    else:
                        if ipv4:
                            paths.append(
                                f"{provider}/{database_type}/{provider}4.dat.gz"
                            )
                        if ipv6:
                            paths.append(
                                f"{provider}/{database_type}/{provider}6.dat.gz"
                            )
                else:
                    paths.extend(self.generate_paths(value, prefix + [key]))
        return paths
