import hashlib
import json

import pytest
from decky_proxy.errors import ProxyError
from decky_proxy.geodata import prepare_geodata


def test_geodata_copies_verified_bundled_files_without_network(tmp_path):
    plugin, runtime = tmp_path / "plugin", tmp_path / "runtime"
    (plugin / "assets").mkdir(parents=True)
    (plugin / "bin" / "geodata").mkdir(parents=True)
    files = {}
    for name in ("geoip.dat", "geosite.dat", "ASN.mmdb"):
        data = ("fixture " + name).encode()
        (plugin / "bin" / "geodata" / name).write_bytes(data)
        files[name] = {"sha256": hashlib.sha256(data).hexdigest()}
    (plugin / "assets" / "geodata-lock.json").write_text(json.dumps({"files": files}))
    prepare_geodata(plugin, runtime, {"rules": ["GEOSITE,cn,DIRECT"]})
    assert (runtime / "geosite.dat").read_bytes() == b"fixture geosite.dat"
    assert (runtime / "ASN.mmdb").read_bytes() == b"fixture ASN.mmdb"
    (runtime / "geoip.dat").write_bytes(b"corrupt cache")
    prepare_geodata(plugin, runtime, {})
    assert (runtime / "geoip.dat").read_bytes() == b"fixture geoip.dat"
    (plugin / "bin" / "geodata" / "geoip.dat").write_bytes(b"tampered bundle")
    (runtime / "geoip.dat").unlink()
    with pytest.raises(ProxyError, match="校验"):
        prepare_geodata(plugin, runtime, {})


def test_geo_rules_require_data_and_symlink_cache_is_refused(tmp_path):
    with pytest.raises(ProxyError, match="地理"):
        prepare_geodata(tmp_path, tmp_path / "runtime", {"rules": ["GEOIP,CN,DIRECT"]})
    prepare_geodata(tmp_path, tmp_path / "runtime", {"rules": ["MATCH,DIRECT"]})
