from pydantic import ValidationError

from config.types import Config as ConfigModel
from files.File import read_json_file, validate_file


class Config:
    def __init__(self, config_path: str):
        try:
            validate_file(config_path)
        except ValueError as e:
            raise ValueError(f"Invalid config path: {config_path}") from e

        try:
            self.config_dict = read_json_file(config_path)
        except ValueError as e:
            raise ValueError(f"Error reading config file: {config_path}") from e

        try:
            self._validate_config()
        except ValueError as e:
            raise ValueError(f"Invalid config content in file: {config_path}") from e

    def _validate_config(self):
        try:
            self.config = ConfigModel(**self.config_dict)
        except ValidationError as e:
            raise ValueError(f"Config validation error: {e}") from e

    def get_config(self) -> ConfigModel:
        return self.config
