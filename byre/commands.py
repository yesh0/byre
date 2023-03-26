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

import typing

import click
import tabulate
import tomli

from byre import ByrApi, BtClient, ByrClient


class GlobalConfig(click.ParamType):
    """配置信息以及各种命令。"""

    name = "配置文件路径"

    config: dict[str, typing.Any] = None

    byr_credentials = ("", "", "")

    qbittorrent_url = ""

    download_dir = ""

    size_limit = ""

    free_weight = 0.

    cost_recovery_days = 0.

    removal_exemption_days = 0.

    byr: ByrApi = None
    bt: BtClient = None

    def convert(self, value: str, param, ctx):
        with open(value, "rb") as file:
            self.config = tomli.load(file)

        self.byr_credentials = (
            self._require(str, "byr", "username"),
            self._require(str, "byr", "password"),
            self._optional(str, "byr.cookies", "byr", "cookie_cache")
        )
        self.qbittorrent_url, self.download_dir, self.size_limit = (
            self._require(str, "qbittorrent", "url"),
            self._require(str, "qbittorrent", "download_dir"),
            self._require(float, "qbittorrent", "size_limit"),
        )
        self.free_weight = self._optional(float, 1., "scoring", "free_weight")
        self.cost_recovery_days = self._optional(float, 7., "scoring", "cost_recovery_days")
        self.removal_exemption_days = self._optional(float, 15., "scoring", "removal_exemption_days")
        return self

    def init(self, byr=False, bt=False):
        """初始化北邮人客户端等。"""
        if byr:
            self.byr = ByrApi(ByrClient(*self.byr_credentials))
        if bt:
            self.bt = BtClient(self.qbittorrent_url, self.download_dir)

    def display_torrent_info(self, seed: str):
        if seed.isdigit():
            seed_id = int(seed)
        else:
            seed_id = ByrApi.extract_url_id(seed)
        self.init(byr=True)
        torrent = self.byr.torrent(seed_id)
        click.echo(tabulate.tabulate([
            ("标题", torrent.title),
            ("副标题", torrent.sub_title),
            ("链接", f"https://byr.pt/details.php?id={torrent.seed_id}"),
            ("类型", f"{torrent.cat} - {torrent.second_category}"),
            ("促销", str(torrent.promotions)),
            ("大小", f"{torrent.file_size:.2f} GB"),
            ("存活时间", f"{torrent.live_time:.2f} 天"),
            ("做种人数", torrent.seeders),
            ("下载人数", torrent.leechers),
            ("上传用户", f"{torrent.uploader.username}" +
             (f" https://byr.pt/userdetails.php?id={torrent.uploader.user_id}"
              if torrent.uploader.user_id != 0 else "")
             ),
        ], maxcolwidths=[2, 10, 70], showindex=True))

    def _require(self, typer: typing.Callable, *args):
        config = self.config
        for arg in args:
            if arg not in config:
                raise ValueError(f"缺失 {'.'.join(args)} 配置参数")
            config = config[arg]
        try:
            return typer(config)
        except ValueError as e:
            raise ValueError(f"配置项 {'.'.join(args)} 的值 {config} 无效：{e}")

    def _optional(self, typer: typing.Callable, default: typing.Any, *args):
        try:
            return self._require(typer, *args)
        except ValueError:
            return default
