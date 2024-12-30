import yaml

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
    merge_configs("config.default.yaml", "config.yaml")
