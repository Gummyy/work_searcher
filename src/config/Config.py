from pydantic import ValidationError

from config.types import Config as ConfigModel
from files.utils import read_json_file, validate_file


class Config:
    """Loads and validates the configuration for the job search application.

    The configuration is a JSON file containing the candidate's profile,
    job preferences, document categories, and API call descriptors.

    Attributes:
        config (ConfigModel): The validated configuration model instance.
    """

    def __init__(self, config_path: str):
        """Initializes the object using data from the file located at config_path.

        Args:
            config_path (str): The path to the config file.

        Raises:
            ValueError: If the path does not exist or the file cannot be read.
            ValueError: If the file content does not satisfy the ConfigModel schema.
        """
        try:
            validate_file(config_path)
        except ValueError as e:
            raise ValueError(f"Invalid config path: {config_path}") from e

        try:
            config_dict = read_json_file(config_path)
        except ValueError as e:
            raise ValueError(f"Error reading config file: {config_path}") from e

        try:
            self.config = ConfigModel(**config_dict)
        except ValidationError as e:
            raise ValueError(f"Invalid config content in file: {config_path}") from e

    def get_config(self) -> ConfigModel:
        """Returns the parsed config.

        Returns:
            ConfigModel: The ConfigModel object derived from the config.json file.
        """
        return self.config
