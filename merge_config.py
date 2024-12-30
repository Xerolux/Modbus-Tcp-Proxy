import os
import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_FILE = os.path.join(BASE_DIR, "config.default.yaml")
USER_CONFIG_FILE = os.path.join(BASE_DIR, "config.yaml")

def merge_configs(default_file, user_file):
    with open(default_file, "r") as default:
        default_config = yaml.safe_load(default)

    with open(user_file, "r") as user:
        user_config = yaml.safe_load(user)

    def recursive_update(default, user):
        for key, value in default.items():
            if isinstance(value, dict) and key in user:
                user[key] = recursive_update(value, user[key])
            elif key not in user:
                user[key] = value
        return user

    merged_config = recursive_update(default_config, user_config)

    with open(user_file, "w") as user:
        yaml.safe_dump(merged_config, user)

if __name__ == "__main__":
    merge_configs(DEFAULT_CONFIG_FILE, USER_CONFIG_FILE)
