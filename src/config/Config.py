from pydantic import ValidationError

from config.types import Config as ConfigModel
from files.File import read_json_file, validate_file


class Config:
    """
    Loads and validates the configuration for the job search application.
    The configuration is expected to be a JSON file containing the candidate's profile, job preferences, document categories, and API call descriptors.

    Attributes:
        config_dict (dict): The raw configuration data loaded from the JSON file.
        config (ConfigModel): The validated configuration model instance.

    Methods:
        __init__(config_path: str): Initializes the Config instance by loading and validating the configuration file.
        _validate_config(): Validates the loaded configuration against the ConfigModel schema.
        get_config() -> ConfigModel: Returns the validated configuration model instance.
    """

    def __init__(self, config_path: str):
        """Initializes the object using data from the file located at config_path

        Args:
            config_path (str): The path to the config file

        Raises:
            ValueError: Invalid config path if the file doesn't exist
            ValueError: Error reading config file if the file can't be read for some reason
            ValueError: Invalid config content if the content of the file doesn't satisfy the requirements defined in types.py
        """
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
        """Tries to interpret config_dict as a ConfigModel, testing for some specific characteristics

        Raises:
            ValueError: Config validation error if the config isn't properly filled
        """
        try:
            self.config = ConfigModel(**self.config_dict)
        except ValidationError as e:
            raise ValueError(f"Config validation error: {e}") from e

    def get_config(self) -> ConfigModel:
        """Returns the parsed config

        Returns:
            ConfigModel: The ConfigModel object derived from the config.json file
        """
        return self.config
