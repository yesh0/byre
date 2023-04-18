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

import logging
import typing
from urllib.parse import quote

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
        # 懒加载验证码（模型以及大块的依赖）。
        import io
        from PIL import Image
        import byre.decaptcha as decaptcha
        if self._decaptcha is None:
            # 重用对象，避免重复创建。
            self._decaptcha = decaptcha.DeCaptcha()
            self._decaptcha.load_model()

        self._session.cookies.clear()

        login_page = self.get_soup("login.php")
        img_url = self.get_url(
            login_page.select("#nav_block > form > table > tr:nth-of-type(3) img")[0].attrs["src"]
        )
        captcha_text = self._decaptcha.decode(Image.open(io.BytesIO(self._session.get(img_url).content)))
        _debug("验证码解析结果：%s", captcha_text)

        _debug("正在发起登录请求")
        self._rate_limit()
        login_res = self._session.post(
            self.get_url("takelogin.php"),
            data={
                "username": self.username,
                "password": self.password,
                "imagestring": captcha_text,
                "imagehash": img_url.split("=")[-1],
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
        page = self.client.get_soup(
            f"torrents.php?page={page}&spstate={promotion.get_int()}"
            f"&pktype={tag.value}&sort={sorted_by.value}&type={order}&inclbookmarked={int(fav)}"
            + ("" if search is None else f"&search={quote(search)}")
        )
        return self._extract_torrent_table(page.select("table.torrents > tr")[1:])
