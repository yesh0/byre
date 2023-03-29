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
from urllib.parse import parse_qs, urlparse

import bs4

from byre import utils
from byre.data import ByrUser
from byre.clients.client import NexusClient


_logger = logging.getLogger("byre.clients.api")
_debug, _info, _warning = _logger.debug, _logger.info, _logger.warning


_LEVEL = "等级"
_MANA = "魔力值"
_INVITATIONS = "邀请"
_TRANSFER = "传输"
_UPLOADED = "上传量"


class NexusApi:
    """基于 NexusPHP 的站点的共通 API。"""

    client: NexusClient
    """登录的会话。"""

    _user_id = 0
    """当前登录用户 ID。"""

    def __init__(self, client: NexusClient) -> None:
        self.client = client
        if not client.is_logged_in():
            client.login()

    def close(self) -> None:
        """关闭所用的资源。"""
        self.client.close()

    def current_user_id(self) -> int:
        """获取当前用户 ID。"""
        if self._user_id != 0:
            return self._user_id
        page = self.client.get_soup("")
        user_id = self.extract_url_id(page.select_one("a[href^=userdetails]").attrs["href"])
        _debug("提取的用户 ID 为：%d", user_id)
        self._user_id = user_id
        return user_id

    @staticmethod
    def extract_url_id(href: str) -> int:
        return int(parse_qs(urlparse(href).query)["id"][0])

    @staticmethod
    def _extract_info_bar(user: ByrUser, page: bs4.Tag) -> None:
        """从页面的用户信息栏提取一些信息（就不重复提取 `_extract_user_info` 能提取的了）。"""
        # 北邮人是 `font.color_bonus` + “上传排行”，北洋园是 `span.color_active` + “上传排名”……
        # 没想好怎么比较好地兼容不同的站点，总之先这样。
        ranking_tag = next(tag for tag in page.select(f"#info_block *[class^=color_]") if "上传排" in tag.text)
        ranking = ranking_tag.find_next(string=str.isdigit)
        if ranking is not None:
            user.ranking = int(ranking.text)

        up_arrow = page.select_one("#info_block img.arrowup[title=当前做种]")
        seeding = str("0" if up_arrow is None else up_arrow.next).strip()
        if seeding.isdigit():
            user.seeding = int(seeding)

        down_arrow = page.select_one("#info_block img.arrowdown[title=当前下载]")
        downloading = str("0" if down_arrow is None else down_arrow.next).strip()
        if downloading.isdigit():
            user.downloading = int(downloading)

        connectable = page.select_one("#info_block font[color=green]")
        user.connectable = connectable is not None and "是" in connectable.text

    def user_info(self, user_id: int = 0) -> ByrUser:
        """获取用户信息。"""
        if user_id == 0:
            user_id = self.current_user_id()

        page = self.client.get_soup(f"userdetails.php?id={user_id}")
        user = ByrUser()

        user.user_id = user_id

        name = page.find("h1")
        user.username = "" if name is None else name.get_text(strip=True)

        info_entries = page.select("td.embedded>table>tr")
        # 页面上表格分两列，第一列数据名称，第二列数据；提取成 dict。
        info: dict[str, bs4.Tag] = {}
        for entry in info_entries:
            cells: bs4.element.ResultSet[bs4.Tag] = entry.find_all("td", recursive=False)
            if len(cells) != 2:
                continue
            info[cells[0].get_text(strip=True)] = cells[1]

        self._extract_user_info(user, info)
        if user_id == self.current_user_id():
            self._extract_info_bar(user, page)
        return user

    @staticmethod
    def _extract_user_info(user: ByrUser, info: dict[str, bs4.Tag]) -> None:
        """从 `userdetails.php` 的最大的那个表格提取用户信息。"""
        if _LEVEL in info:
            level_img = info[_LEVEL].select_one("img")
            if level_img is not None:
                user.level = level_img.attrs.get("title", "")

        if _MANA in info:
            # 北洋园这里在数字后面跟了一个链接，总之能跑就行。
            user.mana = float("".join(c for c in info[_MANA].get_text(strip=True) if c == "." or c.isdigit()))

        if _INVITATIONS in info:
            invitations = info[_INVITATIONS].get_text(strip=True)
            if "没有邀请资格" not in invitations:
                user.invitations = int(invitations)

        if _TRANSFER in info:
            # 北邮人应该是原来的 NexusPHP 吧。
            transferred = info[_TRANSFER]
            for cell in transferred.select("td"):
                text = cell.get_text(strip=True)
                if ":" not in text:
                    continue
                field, value = [s.strip() for s in text.split(":", 1)]
                if field == "分享率":
                    user.ratio = float(value)
                elif field == "上传量":
                    user.uploaded = utils.convert_nexus_size(value)
                elif field == "下载量":
                    user.downloaded = utils.convert_nexus_size(value)

        if _UPLOADED in info:
            # 北洋园只有上传量。
            user.uploaded = utils.convert_nexus_size(info[_UPLOADED].get_text(strip=True))
