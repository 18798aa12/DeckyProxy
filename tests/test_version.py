import json

import pytest
from decky_proxy.errors import ProxyError
from decky_proxy.version import package_version


def test_reads_the_installed_package_version(tmp_path):
    package = tmp_path / "package.json"
    package.write_text('{"version":"9.10.11"}')
    assert package_version(package) == "9.10.11"


@pytest.mark.parametrize("value", [{}, [], None, {"version": None}, {"version": "v1.2.3"},
                                  {"version": "1.2"}, {"version": "01.2.3"}])
def test_invalid_package_metadata_cannot_confirm_update_health(tmp_path, value):
    package = tmp_path / "package.json"
    package.write_text(json.dumps(value))
    with pytest.raises(ProxyError, match="版本信息"):
        package_version(package)


def test_missing_package_has_a_safe_error(tmp_path):
    with pytest.raises(ProxyError, match="版本信息"):
        package_version(tmp_path / "package.json")
