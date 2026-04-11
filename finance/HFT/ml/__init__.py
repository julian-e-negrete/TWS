from pathlib import Path
import yaml

_cfg_path = Path(__file__).parent / 'config.yaml'

def get_config() -> dict:
    with open(_cfg_path) as f:
        return yaml.safe_load(f)
