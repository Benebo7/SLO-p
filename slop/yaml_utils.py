from io import StringIO

from ruamel.yaml import YAML


def _create_yaml(width=None):
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    if width is not None:
        yaml.width = width
    return yaml


def extract_data(file_path):
    """Load and validate a YAML config file while preserving round-trip metadata."""
    yaml = _create_yaml()
    with open(file_path, "r", encoding="utf-8") as f:
        full_dict = yaml.load(f)
        if not isinstance(full_dict, dict):
            raise ValueError("YAML content is not a dictionary.")

    return full_dict


def write_yaml(file_path, data, width=None):
    """Serialize a mapping to YAML and write it safely to file_path."""
    yaml = _create_yaml(width=width)
    buffer = StringIO()
    yaml.dump(data, buffer)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(buffer.getvalue())
