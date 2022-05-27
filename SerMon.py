import socket
import ssl
from datetime import datetime
import subprocess
import platform
from ConfQuick import ConfQuick, BASE_DIR


class SerMon:
    defaults = {
        "sermon": {
            "timestamp_format": "%Y-%m-%d %H:%M:%S",
            "notification": {
                "smtp": {
                    "default": {
                        "host": "",
                        "username": "",
                        "password": "",
                        "port": "25",
                        "secure_mode": "ssl",  # ssl, tls, plain
                        "email": ""
                    }
                },
                "distribution_groups": {
                    "default": {
                        "smtp_server": "default",
                        "recipients": ["group_name"]
                    },
                    "group_name": {
                        "smtp_server": "default",
                        "recipients": ["danielb@agileisp.com", "no@email.com"]
                    }
                }
            },
            "servers": [
                {
                    "name": "Google Web Plain",
                    "host": "google.com",
                    "port": 80,  # not used for ping
                    "conn_type": "plain",
                    "priority": "high",
                    "timeout": 1000,
                    "distribution_group": "default"
                },
                {
                    "name": "Google Web SSL",
                    "host": "google.com",
                    "port": 443,  # not used for ping
                    "conn_type": "ssl",
                    "priority": "high",
                    "timeout": 1000,
                    "distribution_group": "default"
                },
                {
                    "name": "Google Server Ping",
                    "host": "google.com",
                    "port": 80,  # not used for ping
                    "conn_type": "ping",
                    "priority": "high",
                    "timeout": 1000,
                    "distribution_group": "default"
                },
            ]
        }
    }

    def __str__(self):
        return str(self.init_kwargs)

    def __init__(self, **kwargs):
        self.init_kwargs = kwargs
        self.name = kwargs.get('name', '?')
        self.timestamp_format = kwargs.get('timestamp_format', '%Y-%m-%d %H:%M:%S')
        self.name_norm = self.normalize(self.name)
        self.logname = f"{BASE_DIR}/{self.name_norm}.log"
        self.host = kwargs.get('host', '').lower()
        self.port = kwargs.get('port', 80)
        self.conn_type = kwargs.get('conn_type', 'plain').lower()  # plain (default), ssl, ping
        self.priority = kwargs.get('priority', 'high').lower()
        self.timeout = kwargs.get('timeout', 1000)

        self.smtp_settings = kwargs.get('smtp_server', {})
        self.recipients = kwargs.get('recipients', [])

        self.alert = kwargs.get('alert')
        self.last_alert = kwargs.get('last_alert')
        self.alert_start = kwargs.get('alert_start')
        self.alert_count = kwargs.get('alert_count', 0)

    @staticmethod
    def normalize(name: str):
        return name.replace(' ', '_')

    @classmethod
    def load_config(cls):
        try:
            conf = ConfQuick("sermon", cls.defaults)
            server_list = conf.get("sermon.servers")
            groups = conf.get("sermon.notification.distribution_groups")
            smtp_servers = conf.get("sermon.notification.smtp")
            my_servers = []
            for server in server_list:
                server: dict
                # merge the journal information for the current server
                server.update(conf.get(f"journal.{cls.normalize(server.get('name', ''))}", {}))
                # merge smtp and distribution group settings
                server['distribution_groups'] = cls._get_group_settings(
                    server.get('distribution_group', 'default'), groups, smtp_servers)
                my_servers.append(cls(**server))
            return my_servers
        except Exception as ex:
            raise ex

    @classmethod
    def _get_group_settings(cls, group_name: str, groups: dict, smtp_servers: dict) -> dict:
        final_vals = {}
        group_data = groups.get(group_name, {}).copy()
        smtp_name = group_data.get('smtp_server', 'default')
        smtp_data = smtp_servers.get(smtp_name, {})
        smtp_data['name'] = smtp_name
        rec_list = group_data.get('recipients', [])
        for e_idx in range(len(rec_list) - 1, 0, -1):
            email = rec_list[e_idx]
            if '@' not in email and rec_list[e_idx] in groups.keys():
                rec_list.pop(e_idx)
                sub_groups = cls._get_group_settings(email, groups, smtp_servers)
                sub_keys = list(sub_groups.keys())
                for sub_name in sub_keys:
                    sub_smtp_name = sub_groups[sub_name].get('smtp_server', {}).get('name')
                    if sub_smtp_name == smtp_name:  # merge recipient list
                        for recipient in sub_groups[sub_name].get('recipients', []):
                            if recipient not in rec_list:
                                rec_list.append(recipient)
                        sub_groups.pop(sub_name)
                final_vals.update(sub_groups)  # potential recursion issue
        group_data['smtp_server'] = smtp_data
        group_data['recipients'] = rec_list
        final_vals[group_name] = group_data
        return final_vals

    def _connection(self, use_ssl=False):
        cn = socket.create_connection((self.host, self.port), timeout=self.timeout)
        return ssl.wrap_socket(cn) if use_ssl else cn

    def _save_log(self, text):
        with open(self.logname, "a") as f:
            f.write(f"{text}\n")

    def _save_state(self):
        conf = ConfQuick("sermon", self.defaults)
        conf.set(f"journal.{self.name_norm}.alert", self.alert, False)
        conf.set(f"journal.{self.name_norm}.last_alert", self.last_alert, False)
        conf.set(f"journal.{self.name_norm}.alert_start", self.alert_start, False)
        conf.set(f"journal.{self.name_norm}.alert_count", self.alert_count, False)
        conf.save()

    def _ping(self):
        try:
            ms = platform.system().lower() == "windows"
            arg = 'n' if ms else 'c'
            to = 'w' if ms else 'W'
            ping_result = subprocess.check_output(f"ping -{to} {str(self.timeout)} -{arg} 1 {self.host}",
                                                  shell=True, universal_newlines=True)
            if 'unreachable' in ping_result or 'timed out' in ping_result:
                return False
            else:
                return True
        except Exception as err:
            print(repr(err))
            return False

    def _send_notification(self, subject, message):
        from email.mime.text import MIMEText as Message
        secure_mode = self.smtp_settings.get("secure_mode", 'plain')
        from_email = self.smtp_settings.get("email")

        if secure_mode == 'ssl':
            from smtplib import SMTP_SSL as SMTP
        else:
            from smtplib import SMTP

        try:
            msg = Message(message, "plain")
            msg["Subject"] = subject
            msg["From"] = from_email
            cn = SMTP(self.smtp_settings.get("host"), self.smtp_settings.get("port"))
            try:
                cn.ehlo()
                if secure_mode == 'tls':
                    cn.starttls()
                    cn.ehlo()
                cn.login(self.smtp_settings.get("username"), self.smtp_settings.get("password"))
                cn.sendmail(from_email, self.recipients, msg.as_string())
            finally:
                cn.quit()
        except Exception as ex:
            self._save_log(f"{datetime.now().strftime(self.timestamp_format)} - {repr(ex)}")

    def check_connection(self):
        message = ""
        success = False
        now = datetime.now()

        try:
            if self.conn_type == "ping":
                success = self._ping()
            else:
                self._connection(self.conn_type == "ssl")
                success = True
            if success:
                self.alert = False
                message = f"{self.name} is up! {self.host}:{self.port} using {self.conn_type}"
        except socket.timeout:
            message = f"{self.name} connection timed out! {self.host}:{self.port} using {self.conn_type}"
        except (ConnectionRefusedError, ConnectionResetError) as e:
            message = f"{self.name} connection failed! {self.host}:{self.port} using {self.conn_type} error: {repr(e)}"
        except Exception as e:
            message = f"{self.name} unknown error! {self.host}:{self.port} using {self.conn_type} error: {repr(e)}"

        if success is False and not self.alert:
            self.alert = True
            self.alert_count = 1
            self.alert_start = now.strftime(self.timestamp_format)
            self.last_alert = now.strftime(self.timestamp_format)
            # send the message here
        elif success is True and self.alert is True:
            self.alert = False
        elif success is False and self.alert is True:
            if str(self.alert_count).isnumeric():
                self.alert_count += 1
            else:
                self.alert_count = 1
            self.last_alert = now.strftime(self.timestamp_format)

        try:
            self._save_state()
            self._save_log(f"{now.strftime(self.timestamp_format)} - {message}")
            if self.alert:
                self._send_notification(f"{message}", f"{now.strftime(self.timestamp_format)} - {message}")
        except Exception as e:
            message += f"\n{repr(e)}"
        return message


# a yaml file will be generated when the script is run the first time
if __name__ == '__main__':
    servers = SerMon.load_config()

    for s in servers:
        print(s.check_connection())
