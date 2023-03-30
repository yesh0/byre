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

from overrides import override

from byre.clients.api import NexusApi, NexusSortableField
from byre.clients.client import NexusClient
from byre.clients.data import TorrentInfo, TorrentPromotion, TorrentTag, UserTorrentKind

_logger = logging.getLogger("byre.clients.byr")
_debug, _info, _warning = _logger.debug, _logger.info, _logger.warning


class ByrClient(NexusClient):
    """封装了 `requests.Session`，负责登录、管理会话、发起请求。"""

    _decaptcha = None
    """验证码自动识别模块（采用懒加载所以没有附上类型信息）。"""

    @override
    def _get_url(self, path: str) -> str:
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
        img_url = self._get_url(
            login_page.select("#nav_block > form > table > tr:nth-of-type(3) img")[0].attrs["src"]
        )
        captcha_text = self._decaptcha.decode(Image.open(io.BytesIO(self._session.get(img_url).content)))
        _debug("验证码解析结果：%s", captcha_text)

        _debug("正在发起登录请求")
        login_res = self._session.post(
            self._get_url("takelogin.php"),
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

    @override
    def list_torrents(self, page: int = 0,
                      sorted_by: NexusSortableField = NexusSortableField.ID,
                      desc: bool = True,
                      /,
                      promotion: TorrentPromotion = TorrentPromotion.ANY,
                      tag: TorrentTag = TorrentTag.ANY,
                      **kwargs) -> list[TorrentInfo]:
        """从 torrents.php 页面提取信息。"""
        order = "desc" if desc else "asc"
        page = self.client.get_soup(
            f"torrents.php?page={page}&spstate={promotion.get_int()}"
            f"&pktype={tag.value}&sort={sorted_by.value}&type={order}"
        )
        return self._extract_torrent_table(page.select("table.torrents > form > tr")[1:])

    def list_user_torrents(self, kind: UserTorrentKind = UserTorrentKind.SEEDING) -> list[TorrentInfo]:
        """从 Ajax API 获取用户正在上传的种子列表。"""
        # noinspection SpellCheckingInspection
        page = self.client.get_soup(
            f"getusertorrentlistajax.php?userid={self.current_user_id()}&type={kind.name.lower()}")
        if kind != UserTorrentKind.SEEDING:
            # 其它表格基本只有类型和标题两列信息有用
            return self._extract_torrent_table(page.select("table > tr")[1:], *([None] * 10))
        # 上传种子表格的格式：
        #   0     1     2      3       4       5       6       7
        # 类型、题目、大小、做种数、下载数、上传量、下载量、分享率
        return self._extract_torrent_table(
            page.select("table > tr")[1:],
            comment_cell=None,
            live_time_cell=None,
            size_cell=2,
            seeder_cell=3,
            leecher_cell=4,
            finished_cell=None,
            uploader_cell=None,
            uploaded_cell=5,
            downloaded_cell=6,
            ratio_cell=7,
        )

    def download_torrent(self, seed_id: int) -> bytes:
        res = self.client.get(f"download.php?id={seed_id}")
        return res.content
