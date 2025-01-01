import os
import sys


def get_bool(var_name) -> bool:
    value = _get_env(var_name)
    return value is not None and value.lower() in ('true', '1')


def get_env_or_exit(var_name):
    value = _get_env(var_name)

    if value is None:
        _print_error_message_and_exit(f'{var_name} environment variable is not set.')

    return value


def _get_env(var_name):
    return os.environ.get(var_name)


def _print_error_message_and_exit(error_message):
    sys.stderr.write(error_message + '\n')
    sys.exit(1)
