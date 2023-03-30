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
import time
import typing

import click
from overrides import override

from byre.clients.api import NexusApi, NexusSortableField
from byre.clients.client import NexusClient
from byre.clients.data import UserTorrentKind, TorrentPromotion
from byre.commands import pretty
from byre.commands.config import GlobalConfig, ConfigurableGroup

_logger = logging.getLogger("byre.commands")
_warning = _logger.warning


class NexusCommand(ConfigurableGroup):
    """NexusPHP 站点的查询命令。"""

    def __init__(self, client_cls: typing.Type[NexusClient], api_cls: typing.Type[NexusApi]):
        #: 对应的站点 client。
        self.client_cls = client_cls
        #: 对应的站点 API。
        self.api_cls = api_cls
        self.api: typing.Optional[NexusApi] = None
        super().__init__(
            name=api_cls.site(),
            help=f"访问{api_cls.name()}。",
            no_args_is_help=True,
        )

    @override
    def configure(self, config: GlobalConfig):
        site = self.api_cls.site()
        proxy = config.optional(str, "", site, "http_proxy")
        self.api = self.api_cls(self.client_cls(
            config.require(str, site, "username"),
            config.require(str, site, "password", password=True),
            config.optional(str, "byr.cookies", site, "cookie_cache"),
            proxies={
                "http": proxy,
                "https": proxy,
            } if proxy else None,
        ))
        time.sleep(0.5)

    @click.command
    @click.argument("seed", type=click.STRING, metavar="<站点种子链接或是种子 ID>")
    def torrent(self, seed: str):
        """显示种子信息。"""
        pretty.pretty_torrent_info(self.api.torrent(pretty.parse_url_id(seed)))

    @click.command
    @click.argument("user", type=click.STRING, default="0", metavar="[站点用户链接或是用户 ID]")
    def user(self, user_id: str):
        """显示用户信息。"""
        u = self.api.user_info(pretty.parse_url_id(user_id))
        if u.user_id != self.api.current_user_id():
            _warning("查询的用户并非当前登录用户，限于权限，信息可能不准确")
        pretty.pretty_user_info(u)

    @click.command
    @click.option("-k", "--kind", type=click.Choice([p.name.lower() for p in UserTorrentKind], case_sensitive=False),
                  default="seeding", help="用户种子列表")
    def mine(self, kind: str):
        """显示用户的种子列表（如正在做种、正在下载等列表）。"""
        torrents = self.api.list_user_torrents(UserTorrentKind[kind.upper()])
        if len(torrents) == 0:
            _warning("种子列表为空")
            return
        if kind != "seeding":
            _warning("用户做种列表的信息最完善，其它列表会有信息缺失")
        pretty.pretty_torrent_list(torrents)

    @click.command
    @click.argument("page", type=click.INT, default=0, metavar="[种子页面页码]")
    @click.option("-o", "--order",
                  type=click.Choice([p.name.lower() for p in NexusSortableField], case_sensitive=False),
                  default="id", help="排序类型")
    def list(self, page: int, order: str):
        """显示种子列表（页码从零开始）。"""
        torrents = self.api.list_torrents(page, sorted_by=NexusSortableField[order.upper()])
        pretty.pretty_torrent_list(torrents)


class ByrCommand(NexusCommand):
    @click.command
    @click.argument("page", type=click.INT, default=0, metavar="[种子页面页码]")
    @click.option("-p", "--promotion",
                  type=click.Choice([p.name.lower() for p in TorrentPromotion], case_sensitive=False),
                  default="any", help="促销类型")
    @click.option("-o", "--order",
                  type=click.Choice([p.name.lower() for p in NexusSortableField], case_sensitive=False),
                  default="id", help="排序类型")
    def list(self, page: int, promotion: str, order: str):
        """显示北邮人种子列表（页码从零开始）。"""
        torrents = self.api.list_torrents(page, sorted_by=NexusSortableField[order.upper()],
                                          promotion=TorrentPromotion[promotion.upper()])
        pretty.pretty_torrent_list(torrents)
