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

import datetime
import typing

import bs4
from overrides import override

from byre import utils
from byre.clients.api import NexusApi
from byre.clients.byr import NexusSortableField, TorrentInfo
from byre.clients.client import NexusClient


class TjuPtClient(NexusClient):
    """北洋园登录及会话管理。"""

    @classmethod
    @override
    def get_url(cls, path: str) -> str:
        return f"https://tjupt.org/{path}"

    def _authorize_session(self):
        self._session.cookies.clear()

        login_res = self._session.post(
            self.get_url("takelogin.php"),
            data={
                "username": self.username,
                "password": self.password,
                "logout": "7days",
            },
            allow_redirects=False,
        )

        if login_res.status_code == 302:
            return

        raise ConnectionError("登录请求失败，因为北洋园有封 IP 机制，请谨慎使用")


class TjuPtApi(NexusApi):
    """北洋园 API。"""

    @classmethod
    @override
    def name(cls) -> str:
        return "北洋园 PT 站"

    @classmethod
    @override
    def site(cls) -> str:
        return "tju"

    @override
    def list_torrents(self, page: int = 0,
                      sorted_by: NexusSortableField = NexusSortableField.ID,
                      desc: bool = True,
                      /, **kwargs) -> list[TorrentInfo]:
        """从 torrents.php 页面提取信息。"""
        order = "desc" if desc else "asc"
        page = self.client.get_soup(f"torrents.php?page={page}&sort={sorted_by.value}&type={order}")
        return self._extract_torrent_table(page.select("table.torrents > tr")[1:])

    @classmethod
    @override
    def _extract_updated_at(cls, cells: bs4.element.ResultSet[bs4.Tag],
                            live_time_cell: typing.Optional[int]) -> datetime.datetime:
        return (
            datetime.datetime.fromisoformat(cells[live_time_cell].get_text(separator=" ", strip=False))
            if live_time_cell is not None else datetime.datetime.now()
        )

    @classmethod
    @override
    def _extract_info_bar_ranking(cls, page: bs4.Tag) -> int:
        tag = [tag for tag in page.select("#info_block span.color_active") if "上传排名" in tag.text][0]
        return int(tag.find_next_sibling(name="a").text.strip())

    @classmethod
    @override
    def _extract_page_subtitle(cls, page: bs4.Tag) -> str:
        tag = [tag for tag in page.select(".embedded table tr td") if "副标题" in tag.text][0]
        return tag.next_sibling.text.strip()

    @classmethod
    def _extract_basic_info_row(cls, page: bs4.Tag) -> dict[str, str]:
        row = [tag for tag in page.select(".embedded table tr td") if "基本信息" in tag.text][0]
        info = {}
        for tag in row.find_next("td").find_all("b", recursive=False):
            info[tag.get_text(strip=True)] = tag.next_sibling.text.strip()
        return info

    @classmethod
    @override
    def _extract_page_categories(cls, page: bs4.Tag) -> tuple[str, str]:
        info = cls._extract_basic_info_row(page)
        # 二级分类不想提取了，每个一级分类类别都的二级分类标识都在不同地方……
        return info["类型:"], "北洋园"

    @classmethod
    @override
    def _extract_page_size(cls, page: bs4.Tag) -> float:
        return utils.convert_nexus_size(cls._extract_basic_info_row(page)["大小:"])

    @classmethod
    @override
    def _extract_page_upload_time(cls, page: bs4.Tag) -> datetime.datetime:
        row = [tag for tag in page.select(".embedded table tr td") if "种子名称" in tag.text][0]
        text = row.find_next("td").find(string=lambda s: "发布于" in s).text
        i = text.index("发布于")
        return datetime.datetime.fromisoformat(text[i + 3:].strip())
