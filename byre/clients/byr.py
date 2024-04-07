# Copyright (C) 2023 Yesh
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""提供北邮人 PT 站的部分读取 API 接口。"""
import datetime
import logging
import typing
from urllib.parse import quote

import bs4
from overrides import override

from byre.clients.api import NexusApi, NexusSortableField
from byre.clients.client import NexusClient
from byre.clients.data import TorrentInfo, TorrentPromotion, TorrentTag

_logger = logging.getLogger("byre.clients.byr")
_debug, _warning = _logger.debug, _logger.warning


class ByrClient(NexusClient):
    """封装了 `requests.Session`，负责登录、管理会话、发起请求。"""

    def __init__(
            self,
            username: str,
            password: str,
            cookie_file: str,
            proxies: typing.Optional[dict[str, str]] = None
    ) -> None:
        super().__init__(username, password, cookie_file, proxies)
        #: 验证码自动识别模块（采用懒加载所以没有附上类型信息）。
        self._decaptcha = None

    @classmethod
    @override
    def get_url(cls, path: str) -> str:
        return "https://byr.pt/" + path

    @override
    def _authorize_session(self) -> None:
        """进行登录请求，更新 `self._session`。"""
        self._session.cookies.clear()

        _debug("正在发起登录请求")
        self._rate_limit()
        login_res = self._session.post(
            self.get_url("takelogin.php"),
            data={
                "logintype": "username",
                "userinput": self.username,
                "password": self.password,
                "autologin":"yes",
            },
            allow_redirects=False,
        )

        if login_res.status_code == 302:
            return

        raise ConnectionError("登录请求失败，因为北邮人有封 IP 机制，请谨慎使用")


class ByrApi(NexusApi):
    """北邮人 PT 站爬虫，提供站点部分信息的读取 API。"""

    @classmethod
    @override
    def name(cls) -> str:
        return "北邮人 PT 站"

    @classmethod
    @override
    def site(cls) -> str:
        return "byr"

    @classmethod
    @override
    def _rearrange_table_cells(cls, cells):
        if cells[0].select_one("a[href^=\"upload.php\"]") is not None:
            return cells[1:]
        else:
            return cells

    @classmethod
    @override
    def _extract_category(cls, cell: bs4.Tag) -> str:
        link = cell.select_one(".cat-link")
        return super()._extract_category(cell) if link is None else link.get_text(strip=True)

    @classmethod
    @override
    def _extract_updated_at(cls, cells: bs4.element.ResultSet[bs4.Tag],
                            live_time_cell: typing.Optional[int]) -> datetime.datetime:
        if live_time_cell is None:
            return datetime.datetime.now()
        text = cells[live_time_cell].get_text(strip=True)
        return datetime.datetime.fromisoformat(f"{text[:10]} {text[10:]}")

    @classmethod
    @override
    def _extract_page_upload_time(cls, page: bs4.Tag) -> datetime.datetime:
        node = page.select_one("table #outer table tr")
        now = datetime.datetime.now()
        if node is None:
            return now
        prefix = "发布于"
        text = node.get_text(strip=True)
        if prefix not in text:
            return now
        time = datetime.datetime.fromisoformat(text[text.find(prefix) + len(prefix):].strip())
        return min(time, now)

    @override
    def list_torrents(self, /, page: int = 0,
                      sorted_by: NexusSortableField = NexusSortableField.ID,
                      desc: bool = True, fav: bool = False, search: typing.Optional[str] = None,
                      promotion: TorrentPromotion = TorrentPromotion.ANY,
                      tag: TorrentTag = TorrentTag.ANY,
                      **kwargs) -> list[TorrentInfo]:
        """从 torrents.php 页面提取信息。"""
        if len(kwargs) > 0:
            _warning("不支持的参数：%s", kwargs.keys())
        order = "desc" if desc else "asc"
        page_element = self.client.get_soup(
            f"torrents.php?page={page}&spstate={promotion.get_int()}"
            f"&pktype={tag.value}&sort={sorted_by.value}&type={order}&inclbookmarked={int(fav)}"
            + ("" if search is None else f"&search={quote(search)}")
        )
        return self._extract_torrent_table(page_element.select("table.torrents > tr")[1:])
