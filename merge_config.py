"""
Script to merge default and user-specific YAML configuration files.

This script reads a default configuration file and a user-specific configuration file,
then merges the two by ensuring any missing keys in the user configuration are filled
with values from the default configuration. It writes the updated user configuration
back to the file.

Features:
- Recursively updates nested dictionaries.
- Preserves user-defined values while adding missing default values.

Usage:
Place a default configuration file (config.default.yaml) and a user-specific configuration file 
(config.yaml) in the same directory as this script. Run the script to merge the configurations.
"""

import os
import yaml

# Define paths for the default and user-specific configuration files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_FILE = os.path.join(BASE_DIR, "config.default.yaml")
USER_CONFIG_FILE = os.path.join(BASE_DIR, "config.yaml")

def merge_configs(default_file, user_file):
    """
    Merges a default configuration file with a user configuration file.
    
    Args:
        default_file (str): Path to the default configuration YAML file.
        user_file (str): Path to the user configuration YAML file.
    
    The function updates the user file by adding any missing keys from the default file.
    It writes the merged configuration back to the user file.
    """
    # Load the default configuration
    with open(default_file, "r", encoding="utf-8") as default:
        default_config = yaml.safe_load(default)

    # Load the user-specific configuration
    with open(user_file, "r", encoding="utf-8") as user:
        user_config = yaml.safe_load(user)

    def recursive_update(default, user):
        """
        Recursively updates the user configuration with default values.

        Args:
            default (dict): The default configuration dictionary.
            user (dict): The user configuration dictionary.
        
        Returns:
            dict: The updated user configuration dictionary.
        """
        for key, value in default.items():
            if isinstance(value, dict) and key in user:
                # If value is a dictionary, update it recursively
                user[key] = recursive_update(value, user[key])
            elif key not in user:
                # If key is missing in user configuration, add it
                user[key] = value
        return user

    # Merge the configurations
    merged_config = recursive_update(default_config, user_config)

    # Write the updated user configuration back to the file
    with open(user_file, "w", encoding="utf-8") as user:
        yaml.safe_dump(merged_config, user)

if __name__ == "__main__":
    merge_configs(DEFAULT_CONFIG_FILE, USER_CONFIG_FILE)
