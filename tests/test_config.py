import pytest

from server.config import ConfigError, load_settings

GOOD_TOKEN = "t" * 20


def env(tmp_path, **over):
    base = {
        "WORKSPACE_ROOT": str(tmp_path),
        "MCP_TOKEN": GOOD_TOKEN,
    }
    base.update(over)
    return base


def test_valid_settings(tmp_path):
    s = load_settings(env(tmp_path))
    assert s.workspace_root == tmp_path.resolve()
    assert s.mcp_token == GOOD_TOKEN
    assert s.public_hostname == "localhost"


def test_public_hostname_can_be_configured(tmp_path):
    s = load_settings(env(tmp_path, PUBLIC_HOSTNAME="example.ngrok-free.dev"))
    assert s.public_hostname == "example.ngrok-free.dev"


@pytest.mark.parametrize(
    "over",
    [
        {"WORKSPACE_ROOT": ""},
        {"WORKSPACE_ROOT": "/definitely/not/here"},
        {"MCP_TOKEN": ""},
        {"MCP_TOKEN": "short"},
        {"MCP_TOKEN": "change-me-token"},
        {"PUBLIC_HOSTNAME": "https://example.ngrok-free.dev"},
        {"PUBLIC_HOSTNAME": "example.ngrok-free.dev/mcp"},
    ],
)
def test_unsafe_config_rejected(tmp_path, over):
    with pytest.raises(ConfigError):
        load_settings(env(tmp_path, **over))


def test_relative_log_path_is_anchored_to_project_root(tmp_path):
    from server.config import PROJECT_ROOT

    s = load_settings(env(tmp_path, LOG_PATH="logs/x.jsonl"))
    assert s.log_path == (PROJECT_ROOT / "logs" / "x.jsonl").resolve()


def test_absolute_log_path_is_kept(tmp_path):
    target = tmp_path / "audit.jsonl"
    s = load_settings(env(tmp_path, LOG_PATH=str(target)))
    assert s.log_path == target.resolve()
