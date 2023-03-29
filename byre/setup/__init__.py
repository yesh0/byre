#  Copyright (C) 2023 Yesh
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""自动下载 qBittorrent-nox 并进行相关配置。"""

import importlib.resources
import logging
import os.path
import pathlib
import platform
import sys
import typing
import urllib
from urllib.parse import urlparse

import click
import requests
import urllib3

from byre import BtClient

_QBITTORRENT_SIZE = "qbittorrent.size"

_logger = logging.getLogger("byre.setup")
_debug, _info, _warning = _logger.debug, _logger.info, _logger.warning


def _get_download_url(arch: str, version: str = "4.5.2", libtorrent: str = "1.2.18") -> str:
    return ("https://github.com/userdocs/qbittorrent-nox-static/releases/download/" +
            f"release-{version}_v{libtorrent}/{arch}-qbittorrent-nox")


def _get_arch() -> str:
    mapping = {
        "aarch64": "aarch64",
        "armv7l": "armv7",
        "armv6l": "armhf",
        "x86_64": "x86_64",
    }
    arch = platform.machine()
    if arch in mapping:
        return mapping[arch]
    if arch in mapping.values():
        return arch
    raise NotImplementedError(f"平台 {arch} 不受支持")


def download(output: pathlib.Path):
    size_file = output.with_name(_QBITTORRENT_SIZE)
    if output.exists():
        if size_file.exists():
            with size_file.open() as f:
                size = int(f.readline())
            if size == os.path.getsize(output):
                _info("检测到已下载完成的 qBittorrent 客户端")
                return
            os.remove(size_file)
        os.remove(output)
    _info("正在下载 qBittorrent 客户端……")
    os.makedirs(output.parent, exist_ok=True)
    response = requests.get(_get_download_url(_get_arch()), stream=True)
    content_length = response.headers.get('content-length')
    _debug("qBittorrent 客户端下载大小：%s", content_length)
    with size_file.open("w") as size_output:
        size_output.write(content_length)
        size_output.flush()
    with click.progressbar(
        length=int(content_length),
        show_eta=True,
    ) as bar:
        with open(output, "wb") as out:
            for chunk in response.iter_content(4096):
                out.write(chunk)
                bar.update(len(chunk))


def _check_platform():
    if not sys.platform.startswith("linux"):
        raise NotImplementedError("只支持 Linux 平台")
    if not os.path.exists("/bin/systemctl"):
        raise NotImplementedError("只支持 SystemD 的自动配置")


def _init_qbittorrent_config(path: pathlib.Path, port: int):
    with open("/proc/meminfo") as meminfo:
        kilobytes = int([line.split() for line in meminfo.readlines() if line.startswith("MemTotal:")][0][1])
    allowed_mb = round(kilobytes / 1024 / 2)
    _info("总内存大小 %d kB，默认允许 qBittorrent 使用 1/2 的内存：%d MB", kilobytes, allowed_mb)
    with importlib.resources.files(__package__).joinpath("qBittorrent.conf.tmpl").open() as f:
        template = f.read()
    config = template.format_map({
        "memory": allowed_mb,
        "max_connections": 1024,
        "torrent_port": 34112,
        "webui_port": port,
    })
    _debug("qBittorrent 配置文件内容：\n%s", config)
    _info("""
    使用本程序视同您已同意 qBittorrent 的条款：
        *** Legal Notice ***
        qBittorrent is a file sharing program. When you run a torrent,
        its data will be made available to others by means of upload.
        Any content you share is your sole responsibility.
    """)
    _warning("请您确保防火墙（如果有的话）的 IPv6 34112 端口开放")
    os.makedirs(path.parent, exist_ok=True)
    with path.open("w") as config_out:
        config_out.write(config)


def _init_systemd_unit(home: pathlib.Path, executable: pathlib.Path, profile_dir: pathlib.Path):
    service_file = home.joinpath(".config", "systemd", "user", "qbittorrent.service")
    with importlib.resources.files(__package__).joinpath("qbittorrent.service.tmpl").open() as f:
        template = f.read()
    unit = template.format_map({
        "qbittorrent_command": f"{executable} --profile=\"{profile_dir}\"",
    })
    _debug("SystemD Unit 文件内容：\n%s", unit)
    os.makedirs(service_file.parent, exist_ok=True)
    with service_file.open("w") as service:
        service.write(unit)
    os.system("systemctl --user daemon-reload")
    os.system("systemctl --user enable qbittorrent.service")
    os.system("systemctl --user start qbittorrent.service")
    _warning(f"""
    请使用以下命令来确保 qBittorrent 开机运行：
        sudo loginctl enable-linger {os.getlogin()}
    """)


def init_qbittorrent(executable: pathlib.Path, home: pathlib.Path, webui_port: int):
    executable.chmod(0o755)
    profile_dir = home.joinpath(".config", "byre")
    os.makedirs(profile_dir, exist_ok=True)
    _init_qbittorrent_config(profile_dir.joinpath("qBittorrent", "config", "qBittorrent.conf"), webui_port)
    _init_systemd_unit(home, executable, profile_dir)


def _parse_url(url: str):
    parsed = urlparse(url)
    if parsed.hostname not in ["localhost", "127.0.0.1"] or parsed.port is None or parsed.port <= 1024:
        _warning("qBittorrent Web UI 端口设定为 33332，如果要进行反向代理等操作请自行设定")
        port = 33332
    else:
        port = parsed.port
    if not parsed.username or not parsed.password:
        raise ValueError("用户名 / 密码为空，可能是配置中 qBittorrent 的 URL 含有非法字符")
    return parsed.username, parsed.password, port


def setup(url: str, home: typing.Optional[pathlib.Path] = None):
    _check_platform()
    if home is None:
        home = pathlib.Path.home()
    data_dir = home.joinpath(".local", "lib", "byre")
    executable = data_dir.joinpath("qbittorrent")
    download(executable)
    user, password, port = _parse_url(url)
    init_qbittorrent(executable, home, port)
    client = BtClient(f"http://admin:adminadmin@localhost:{port}", "/tmp")
    client.init_webui(user, password)
