import socket
import ssl
from datetime import datetime
import subprocess
import platform
from ConfQuick import ConfQuick, BASE_DIR


class SerMon:
    defaults = {"servers": [
        {
            "name": "Google Web Plain",
            "host": "google.com",
            "port": 80,  # not used for ping
            "con_type": "plain",
            "priority": "high",
            "timeout": 1000
        },
        {
            "name": "Google Web SSL",
            "host": "google.com",
            "port": 443,  # not used for ping
            "con_type": "ssl",
            "priority": "high",
            "timeout": 1000
        },
        {
            "name": "Google Server Ping",
            "host": "google.com",
            "port": 80,  # not used for ping
            "con_type": "ping",
            "priority": "high",
            "timeout": 1000
        },
    ]}

    def __init__(self, **kwargs):
        self.name = kwargs.get('name', '?')
        self.name_norm = self.normalize(self.name)
        self.logname = f"{BASE_DIR}/{self.name_norm}.log"
        self.host = kwargs.get('host', '').lower()
        self.port = kwargs.get('port', 80)
        self.conn_type = kwargs.get('conn_type', 'plain').lower()  # plain (default), ssl, ping
        self.priority = kwargs.get('priority', 'high').lower()
        self.timeout = kwargs.get('timeout', 1000)

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
            server_list = conf.get("servers")
            my_servers = []
            for server in server_list:
                server: dict
                server.update(conf.get(cls.normalize(server.get('name', '')), {}))
                my_servers.append(cls(**server))

            return my_servers
        except Exception as ex:
            raise ex

    def _connection(self, use_ssl=False):
        cn = socket.create_connection((self.host, self.port), timeout=self.timeout)
        return ssl.wrap_socket(cn) if use_ssl else cn

    def _save_log(self, text):
        with open(self.logname, "a") as f:
            f.write(f"{text}\n")

    def _save_state(self):
        conf = ConfQuick("sermon", self.defaults)
        conf.set(f"{self.name_norm}.alert", self.alert, False)
        conf.set(f"{self.name_norm}.last_alert", self.last_alert, False)
        conf.set(f"{self.name_norm}.alert_start", self.alert_start, False)
        conf.set(f"{self.name_norm}.alert_count", self.alert_count, False)
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
            self.alert_start = now.strftime('%Y-%m-%d %I:%M %p')
            self.last_alert = now.strftime('%Y-%m-%d %I:%M %p')
            # send the message here
        elif success is True and self.alert is True:
            self.alert = False
        elif success is False and self.alert is True:
            if str(self.alert_count).isnumeric():
                self.alert_count += 1
            else:
                self.alert_count = 1
            self.last_alert = now.strftime('%Y-%m-%d %I:%M %p')

        try:
            self._save_state()
            self._save_log(f"{now.strftime('%Y-%m-%d %I:%M %p')} - {message}")
        except Exception as e:
            message += f"\n{repr(e)}"
        return message


if __name__ == '__main__':
    servers = SerMon.load_config()

    for s in servers:
        print(s.check_connection())

