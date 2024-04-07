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

import logging
import typing

import click
from overrides import override

import byre.clients
from byre.bt import BtClient
from byre.commands import pretty
from byre.commands.config import GlobalConfig, ConfigurableGroup
from byre.commands.nexus import NexusCommand


_warning = logging.getLogger("byre.commands.bt").warning


class BtCommand(ConfigurableGroup):
    def __init__(self, *remotes: NexusCommand):
        self.config: typing.Optional[GlobalConfig] = None
        self.api: typing.Optional[BtClient] = None
        super().__init__(
            name="qbt",
            help="访问 qBittorrent 信息。",
            no_args_is_help=True,
        )
        self.sites = dict((api.api_cls.site(), api) for api in remotes)

    @override
    def configure(self, config: GlobalConfig):
        self.api = BtClient(config.require(str, "qbittorrent", "url", password=True))
        self.api.load_config(config)
        self.config = config

    @click.command
    @click.option("-a", "--all", "wants_all", is_flag=True, help="显示所有种子，包括不是由脚本添加的种子")
    @click.option("-s", "--speed", is_flag=True, help="只显示有上传或下载速度的种子")
    @click.option("-p", "--pt", default="", type=click.Choice(list(byre.clients.SITES.keys()) + [""]),
                  help="只显示某个 PT 站点的种子")
    def list(self, wants_all: bool, speed: bool, pt: str):
        """列出本地所有相关种子。"""
        if pt:
            site = self.sites[pt]
            site.configure(self.config)
            remote = site.api.list_user_torrents()
        else:
            remote = []
            for site in self.sites.values():
                site.configure(self.config)
                remote.extend(site.api.list_user_torrents())
        torrents = self.api.list_torrents(remote, wants_all=wants_all, site=pt if pt else None)
        if speed:
            torrents = [t for t in torrents if t.torrent.dlspeed + t.torrent.upspeed > 0]
            torrents.sort(key=lambda t: t.torrent.dlspeed + t.torrent.upspeed, reverse=True)
        else:
            torrents.sort(key=lambda t: t.torrent.last_activity, reverse=True)
        if len(torrents) == 0:
            _warning("本地无相关种子")
            return
        pretty.pretty_local_torrents(torrents, speed)
