import pytest

from homelab_mcp.config import ConfigError, config_from_dict, load_config


def test_example_config_loads():
    from pathlib import Path

    cfg = load_config(Path(__file__).parent.parent / "config.example.toml")
    assert cfg.allowed_namespaces == ["default"]
    assert cfg.log_max_lines == 200


def test_caps_cannot_be_raised():
    cfg = config_from_dict({"logs": {"max_lines": 5000}, "sqlite": {"max_rows": 10_000}})
    assert cfg.log_max_lines == 200
    assert cfg.sqlite_max_rows == 200


def test_kubectl_string_is_split():
    assert config_from_dict({"k3s": {"kubectl": "k3s kubectl"}}).kubectl == ["k3s", "kubectl"]


def test_relative_db_path_rejected():
    with pytest.raises(ConfigError):
        config_from_dict({"sqlite": {"databases": {"a": "rel.db"}}})


def test_bad_toml(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("not = [valid")
    with pytest.raises(ConfigError):
        load_config(p)
