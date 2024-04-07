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

import importlib.resources
import logging
import os.path
import pathlib
import typing

import click

from byre.bt import BtClient
from byre.clients import SITES, CLIENTS
from byre.clients.api import NexusApi
from byre.clients.client import NexusClient
from byre.commands.config import GlobalConfig
from byre.utils import cast


_logger = logging.getLogger("byre.setup")
_info = _logger.info


def _prompt_nexus_credentials(
    client: typing.Type[NexusClient],
    api: typing.Type[NexusApi],
    directory: pathlib.Path,
    required=True,
):
    if not required:
        if (
            click.prompt(f"是否启用{api.name()}帐号", type=click.Choice(("yes", "no")))
            != "yes"
        ):
            return "", "", ""
    while True:
        username = click.prompt(f"请输入{api.name()}用户名", type=str)
        password = click.prompt("请输入用户密码", type=str, hide_input=True)
        try:
            cookie_file = str(directory.joinpath(f"{api.site()}.cookies"))
            c = client(username, password, cookie_file)
            c.login(cache=False)
            user = api(c).user_info()
            click.echo(f"用户名：{user.username}，用户 ID：{user.user_id}，验证成功")
            return username, password, cookie_file
        except ConnectionError:
            click.echo("登录错误，也许是用户名与密码错误？")


def _prompt_qbittorrent():
    while True:
        username = click.prompt("请输入 qBittorrent Web UI 用户名", type=str)
        password = click.prompt("请输入用户密码", type=str, hide_input=True)
        host = click.prompt(
            "请输入 qBittorrent Web UI 所在地址", default="localhost", type=str
        )
        port = click.prompt(
            "请输入 qBittorrent Web UI 所在端口", default=8080, type=int
        )
        proto = (
            "https"
            if click.prompt("是否使用 HTTPS", default=False, type=bool)
            else "http"
        )
        download = (
            click.prompt(
                "是否自动下载并配置 qBittorrent", type=click.Choice(("yes", "no"))
            )
            == "yes"
        )
        url = f"{proto}://{username}:{password}@{host}:{port}"
        if not download:
            try:
                BtClient(url).list_torrents([])
            except Exception as e:
                click.echo(f"qBittorrent 连接失败，请检查并重试\n{e}")
                continue
        return url, download


def _prompt_partitions():
    partitions = []
    _info(
        "下面的下载路径指的是实际文件的下载路径（如 MKV, MP4 等）。"
        "脚本不直接保存种子 .torrent 文件。"
        "若需要获取 .torrent 文件，可以进入 qBittorrent Web UI 右键下载。"
    )
    while True:
        download_dir = click.prompt(
            f"请输入第 {len(partitions) + 1} 个下载位置的路径（直接回车以结束）",
            default="",
            type=str,
        )
        if download_dir == "":
            if len(partitions) == 0:
                click.echo("应至少有一个下载路径")
                continue
            else:
                return partitions
        partitions.append(
            {
                "download_dir": download_dir,
                "max_download_size": "0 GiB",
                "max_total_size": "0 GiB",
            }
        )


def _prompt_scoring():
    click.echo(
        "种子的“回本”天数阈值：程序会预估种子下载之后能够达到的分享率，"
        "从而计算出种子分享率达到 1.0 所需要的天数。"
        "程序不会下载对所需天数过高的种子。"
    )
    cost_recovery_days = click.prompt(
        "请输入预期所需天数的阈值",
        default=7.0,
        type=click.FloatRange(0.0, min_open=True),
    )
    click.echo(
        "如果新的热门种子需要的空间不够，程序会自动删除变得冷门的种子来腾出空间。"
        "因为热门程度会有波动，为了避免频繁进行种子的下载和删除并提高点种子留存率，"
        "我们建议设定一个“豁免期”，在种子下载后的这段时间内，种子不会被删除。"
    )
    removal_exemption_days = click.prompt(
        "请输入种子的豁免期天数", default=15.0, type=click.FloatRange(0.0)
    )
    return cost_recovery_days, removal_exemption_days


def interactive_configure(cache_dir: pathlib.Path, config_path: pathlib.Path):
    config = {}
    # Sites
    for site, api in SITES.items():
        client = CLIENTS[site]
        (
            config[f"{site}_username"],
            config[f"{site}_password"],
            config[f"{site}_cookies"],
        ) = _prompt_nexus_credentials(client, api, cache_dir, required=site == "byr")
    # qBittorrent
    config["qbt_url"], download = _prompt_qbittorrent()
    config["cache_db"] = os.path.join(cache_dir, "byre.db")
    # Downloads
    config["partitions"] = _prompt_partitions()
    config.update(config["partitions"][0])
    config["extra_partitions"] = "多个硬盘配置：\n" + "\n".join(
        f"""
        [planning.partition_{i + 1}]
        max_total_size = "{partition['max_total_size']}"
        max_download_size = "{partition['max_download_size']}"
        download_dir = "{partition['download_dir']}"
        """
        for i, partition in enumerate(config["partitions"][1:])
    )
    config["cost_recovery_days"], config["removal_exemption_days"] = _prompt_scoring()

    os.makedirs(config_path.parent, exist_ok=True)
    with importlib.resources.files(cast(str, __package__)).joinpath(
        "byre.example.toml"
    ).open() as tmpl:
        with config_path.open("w") as c:
            c.write(tmpl.read().format_map(config))
            c.flush()
    return GlobalConfig().load(str(config_path)), download
