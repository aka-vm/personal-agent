"""
Central config + secrets loader.

Config (non-secret) lives at  ~/.config/agent/config.yaml
Secrets live at               ~/.config/agent/secrets.env
Both are OUTSIDE the repo so nothing personal is ever committed.
"""
import os
import yaml
from dotenv import dotenv_values

CONFIG_DIR  = os.path.expanduser("~/.config/agent")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.yaml")
SECRETS_FILE = os.path.join(CONFIG_DIR, "secrets.env")


def _expand(path: str) -> str:
    return os.path.expanduser(os.path.expandvars(path)) if path else path


class Config:
    def __init__(self):
        if not os.path.exists(CONFIG_FILE):
            raise FileNotFoundError(
                f"Missing {CONFIG_FILE}. Copy config/config.example.yaml there and fill it in."
            )
        with open(CONFIG_FILE) as f:
            self._cfg = yaml.safe_load(f) or {}
        self._secrets = dotenv_values(SECRETS_FILE) if os.path.exists(SECRETS_FILE) else {}

        # state dir
        self.state_dir = _expand(self.get("paths.state_dir", "~/.config/agent/state"))
        os.makedirs(self.state_dir, exist_ok=True)

    def get(self, dotted_key: str, default=None):
        """cfg.get('telegram.allowed_id')"""
        node = self._cfg
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def secret(self, key: str, default=None):
        return self._secrets.get(key, os.environ.get(key, default))

    # convenience accessors
    @property
    def model(self):        return self.get("agent.model", "claude-sonnet-4-6")
    @property
    def work_dir(self):     return _expand(self.get("agent.work_dir", "/home/vineet/agent"))
    @property
    def timeout(self):      return int(self.get("agent.timeout", 600))
    @property
    def session_timeout(self): return int(self.get("agent.session_timeout", 0))


# singleton
config = Config()
