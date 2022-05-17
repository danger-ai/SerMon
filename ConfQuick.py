from typing import Optional
from benedict import benedict as bd
from dotty_dict.dotty_dict import dotty
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class ConfQuick:
    def __init__(self, app_name: str = "general", default_defs: Optional[dict] = None,
                 notes: Optional[dict] = None, custom_file_path: str = None, django=False, debug=False):
        """
        Initialize and load the ConfQuick object. if no arguments are supplied, example values will be used
        :param app_name: used to generate config file names, examples and the initial django secret key
        :param default_defs: dictionary cannot contain tuple values
        :param notes: for generating documentation. same structure as above, but only allows string values
        :param custom_file_path: by default, the file name is generated from the app name and placed in the base folder
        :param django: True if the config file is meant for use by django. (Auto-generates a secret key)
        """
        self.debug = debug
        if type(custom_file_path) is not str:
            self.conf_file = f"{BASE_DIR}/{app_name}-conf.yaml"
        else:
            self.conf_file = custom_file_path
        self.conf = bd()
        self.default_conf = default_defs if type(default_defs) is dict else {
            f'{app_name}': {
                'server_name': 'example',
                'secret_key': '',
                "database": {
                    "engine": "django.db.backends.mysql",
                    "hosts": ["localhost"],
                    "port": 3306,
                    "user": "root",
                    "password": "",
                    "name": "django",
                },
            }
        } if app_name == 'general' else {}
        self.conf_notes = notes if type(notes) is dict else {}
        if os.path.exists(self.conf_file):
            self._conf = bd.from_yaml(self.conf_file)
            result = self.apply(merge=True)
            if self.debug:
                print(f"Loaded {self.conf_file.split('/')[-1]}!")
            if result:
                print("Warning: Encountered the following issues:")
                print("\n".join(result))
        else:
            if self.debug:
                print("Configuration file not found.")
            self._conf = bd(self.default_conf)
            self.apply(merge=False)

        # finally, check for the django secret key
        if django and not self.get(f'{app_name}.secret_key'):
            self.set(f'{app_name}.secret_key', self.random_string(50), apply=False)
            self.save(self.conf_file)
            raise Exception("Configuration is incomplete. A new Secret Key value was generated. "
                            "Please ensure all configuration has been set before continuing.")

    @staticmethod
    def random_string(length: int):
        """
        Generate a string of random pre-defined characters of any set length
        :param length: the length of the final randomized string
        :return: a random string
        """
        import random
        return ''.join(
            random.choice(
                'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!@#$%^&*0123456789') for _ in range(length))

    def get(self, key_path: str, default=None, cast_as_type=False):
        """
        Get a desired key value from the current configuration
        :param key_path: the key name (ex: 'cfg.my_key_name' or 'cfg.my_list_key.3')
        :param default: a default value to return if the key is not found
        :param cast_as_type: if we are casting, the type of the default value is used to ensure the correct type
        :return: the desired value
        """
        cfg = dotty(self.conf.dict())
        value = cfg.get(key_path, default)
        if cast_as_type is False or default is None:
            return value
        elif type(default) is str:
            return str(value)
        elif type(default) is int:
            if str(value).isnumeric():
                return int(value)
            else:
                print(f'value at: "{key_path}":"{str(value)}" could not be cast as int -- returned default value')
                return default
        elif type(default) is float:
            if str(value).isdecimal():
                return float(value)
            else:
                print(f'value at: "{key_path}":"{str(value)}" could not be cast as float -- returned default value')
                return default
        else:
            print(f'value at: "{key_path}":"{str(value)}" could not be cast like '
                  f'"{str(default)}" ({str(type(default))}) '
                  f'-- returned default value')
            return default

    def cond_get(self, cond_key_path, key_path, default=None, cast_as_type=False):
        """
        Return a key value only if the conditional key value is non-empty, non-zero, etc
        :param cond_key_path: the key name value to check
        :param key_path: the key name (ex: 'cfg.my_key_name' or 'cfg.my_list_key.3')
        :param default: a default value to return if the key is not found
        :param cast_as_type: if we are casting, the type of the default value is used to ensure the correct type
        :return: the desired value
        """
        if self.get(cond_key_path):
            return self.get(key_path, default, cast_as_type)
        return default

    def set(self, key_path, value, apply=True):
        """
        Set the configuration key
        :param key_path: the key name (ex: 'my_cfg_key', 'cfg.my_key_name' or 'cfg.my_list_key.3')
        :param value: the value to set - must be type str, int, dict, or list
        :param apply: the values are only in self._conf unless applied (disabling saves time if updating multiple keys)
        :return: nothing
        """
        cfg = dotty(self._conf.dict())
        cfg[key_path] = value
        self._conf = bd(cfg)
        if apply:
            self.apply()

    def save(self, config_file=None):
        """
        Save current configuration to a file
        :param config_file: the file path
        """
        if config_file is None:
            config_file = self.conf_file
        self._conf.to_yaml(filepath=config_file)

    def apply(self, merge=True):
        """
        Apply/Activate and optionally merge the self._conf shadow configuration -- also updates values using tags
        :param merge: merge the default configuration values
        :return: the results of the merge if one was performed, an empty list otherwise
        """
        temp_conf = self.default_conf.copy()
        result = []
        if merge:
            temp_c_dict = self._conf.dict()
            temp_conf, result = self._verify_merge("", temp_conf, temp_c_dict, [])
            temp_conf.update(temp_c_dict)
        temp_conf = self._update_template_vars(temp_conf)
        self.conf = bd(temp_conf)
        return result

    def _return_template_value(self, value_in, full_dict_obj: dict):
        """
        Used to return the value of a key while traversing possible values (tags)
        :param value_in: can be a str, dict, list, or int
        :param full_dict_obj: the dictionary we can pull values from
        :return: the templated value, or the original value
        """
        if type(value_in) is dict:
            final_val = self._update_template_vars(value_in, full_dict_obj)
        elif type(value_in) is list:
            temp_list = value_in.copy()
            for i in range(0, len(temp_list)):
                temp_list[i] = self._return_template_value(temp_list[i], full_dict_obj)
            final_val = temp_list
        elif type(value_in) is str:
            temp_value = value_in
            params = re.findall(r'{[^}]*[^{]*}', value_in)
            if params:
                for p in params:
                    p: str
                    temp_value = temp_value.replace(p, self._get_replacement_value(p, full_dict_obj))
            final_val = temp_value
        else:
            final_val = value_in
        return final_val

    def _update_template_vars(self, dict_part_obj: dict, full_dict_obj: Optional[dict] = None):
        """
        Traverse a dictionary and evaluate template tag strings that are part of the str, list, or dict
        :param dict_part_obj: Required dictionary to update
        :param full_dict_obj: Optional dictionary to use for applying the template tags (defaults to dict_part_obj)
        :return: the updated dictionary object
        """
        if full_dict_obj is None:
            full_dict_obj = dict_part_obj.copy()
        final_obj = dict_part_obj.copy()
        for k, v in dict_part_obj.items():
            final_obj[k] = self._return_template_value(v, full_dict_obj)
        return final_obj

    @staticmethod
    def _get_replacement_value(template_tag: str, full_dict_obj: dict, as_str: bool = True):
        """
        Traverse a dictionary using a template tag in dotty-dictionary format
        :param template_tag: the template tag string
        :param full_dict_obj: the dictionary to traverse
        :return: the value at the location (strings only)
        """
        from dotty_dict.dotty_dict import dotty

        key_path = template_tag.replace("{", "").replace("}", "")
        cfg = dotty(full_dict_obj)
        return str(cfg[key_path]) if as_str else cfg[key_path]

    def _verify_merge(self, path, dict_obj: dict, comp_dict_obj: dict, result: list):
        """
        Verify dictionary types using the comparison dictionary. Issues are returned to the result object
        :param path: the current dotty-dict-formatted key path (optional)
        :param dict_obj: the input dictionary values are compared with the other dictionary
        :param comp_dict_obj: the dictionary that is used to compare values
        :param result: a list object to store results
        :return: (tuple) merged_dictionary_object, result_list
        """
        result_dict = {}
        for k, v in dict_obj.items():
            current_path = f"{path}.{k}" if path else k
            comp_val = comp_dict_obj.get(k, None)
            comp_type = type(comp_val)
            if comp_val is not None and type(v) is comp_type:
                if comp_type is dict and comp_type:
                    v: dict
                    result_dict[k], result = self._verify_merge(current_path, v, comp_val, result)
                elif comp_type is list:
                    v: list
                    if len(comp_val) > 0:
                        list_type = type(v[0])
                        try:
                            final_list = []
                            for i in range(0, len(comp_val)):
                                comp_type = type(comp_val[i])
                                comp_path = f"{current_path}.{i}"
                                if comp_type is dict:
                                    temp_dict, result = self._verify_merge(comp_path, v[0], comp_val[i], result)
                                    final_list.append(temp_dict)
                                elif comp_type is list_type:
                                    final_list.append(comp_val[i])
                                else:
                                    result.append(f'invalid type was ignored for list '
                                                  f'path: "{comp_path}" value:"{str(comp_val[i])}"')
                            result_dict[k] = final_list
                        except Exception as ex:
                            result_dict[k] = v
                            result.append(f'Error: {repr(ex)} - default value was used for list: "{current_path}"')
                    else:
                        result.append(f'list is empty for "{current_path}"')
                        result_dict[k] = comp_val
                elif comp_type is str or comp_type is int or comp_type is float or comp_type is bool:
                    result_dict[k] = comp_val
                else:
                    result_dict[k] = v
                    result.append(f'default value was used for "{current_path}"')
            elif comp_val is not None and type(v) is int and comp_type is str:
                if str(comp_val).isnumeric():
                    # expecting an int, so convert to an int...
                    result_dict[k] = int(comp_val)
                    # result.append(f'string converted to int at: "{current_path}"')
                elif str(comp_val).strip().startswith("{") and str(comp_val).strip().endswith("}"):
                    result_dict[k] = str(comp_val).strip()
                    # result.append(f'template tag used for int value at: "{current_path}" (we assume this is fine)')
                else:
                    result_dict[k] = v
                    result.append(f'default value was used for "{current_path}" because string was set for int value')
            else:
                result_dict[k] = v
                result.append(f'default value was used for "{current_path}"')
        return result_dict, result