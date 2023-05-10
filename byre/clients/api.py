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
import enum
import logging
import re
import typing
from abc import ABCMeta, abstractmethod
from urllib.parse import parse_qs, urlparse

import bs4

from byre import utils
from byre.clients.client import NexusClient
from byre.clients.data import NexusUser, TorrentInfo, TorrentPromotion, TorrentTag, UserTorrentKind

_logger = logging.getLogger("byre.clients.api")
_debug, _info, _warning = _logger.debug, _logger.info, _logger.warning


class NexusSortableField(enum.Enum):
    """
    NexusPHP 中种子列表页面允许的排序，数字为页面的 sort 参数。

    这个北邮人和北洋园是一致的。
    """

    ID = 0
    TITLE = 1
    FILE_COUNT = 2
    COMMENT_COUNT = 3
    LIVE_TIME = 4
    SIZE = 5
    FINISHED_COUNT = 6
    SEEDER_COUNT = 7
    LEECHER_COUNT = 8
    UPLOADER = 9


_LEVEL = "等级"
_MANA = "魔力值"
_INVITATIONS = "邀请"
_TRANSFER = "传输"
_UPLOADED = "上传量"


class NexusApi(metaclass=ABCMeta):
    """
    基于 NexusPHP 的站点的共通 API。

    尽量把不同站点可以自定义的地方都给提取出单独的函数了，但说不准。
    """

    @classmethod
    @abstractmethod
    def site(cls) -> str:
        """返回 NexusPHP 站点标签。"""

    @classmethod
    @abstractmethod
    def name(cls) -> str:
        """返回可读的站点名字。"""

    def __init__(self, client: NexusClient) -> None:
        #: 登录的会话。
        self.client = client
        #: 当前登录用户 ID。
        self._user_id = 0

    def close(self) -> None:
        """关闭所用的资源。"""
        self.client.close()

    @abstractmethod
    def list_torrents(self, /, page: int = 0, sorted_by: NexusSortableField = NexusSortableField.ID, desc: bool = True,
                      fav: bool = False, search: typing.Optional[str] = None, **kwargs) -> list[TorrentInfo]:
        """从 torrents.php 页面提取信息。"""

    def current_user_id(self) -> int:
        """获取当前用户 ID。"""
        if self._user_id != 0:
            return self._user_id
        page = self.client.get_soup("")
        user_id = self.extract_url_id(page.select_one("a[href^=userdetails]").attrs["href"])
        _debug("提取的用户 ID 为：%d", user_id)
        self._user_id = user_id
        return user_id

    @classmethod
    def extract_url_id(cls, href: str) -> int:
        return int(parse_qs(urlparse(href).query)["id"][0])

    @classmethod
    def _extract_info_bar_ranking(cls, page: bs4.Tag) -> int:
        """
        从页面的用户信息栏提取一些信息（就不重复提取 `_extract_user_info` 能提取的了）。

        排名部分北邮人是 `font.color_bonus` + “上传排行”，北洋园是 `span.color_active` + “上传排名”……
        没想好怎么比较好地兼容不同的站点，总之这里写的是北邮人的版本，有需要的重载吧。
        """
        ranking_tag = next(tag for tag in page.select("#info_block .color_bonus") if "上传排行" in tag.text)
        ranking = ranking_tag.next_sibling.text.strip()
        return utils.int_or(ranking)

    @classmethod
    def _extract_info_bar(cls, user: NexusUser, page: bs4.Tag) -> None:
        user.ranking = cls._extract_info_bar_ranking(page)

        up_arrow = page.select_one("#info_block .arrowup")
        seeding = str("0" if up_arrow is None else up_arrow.next).strip()
        if seeding.isdigit():
            user.seeding = utils.int_or(seeding)

        down_arrow = page.select_one("#info_block .arrowdown")
        downloading = str("0" if down_arrow is None else down_arrow.next).strip()
        if downloading.isdigit():
            user.downloading = utils.int_or(downloading)

        connectable = page.select_one("#info_block font[color=green]")
        user.connectable = connectable is not None and "是" in connectable.text

    def user_info(self, user_id: int = 0) -> NexusUser:
        """获取用户信息。"""
        if user_id == 0:
            user_id = self.current_user_id()

        page = self.client.get_soup(f"userdetails.php?id={user_id}")
        name = page.find("h1")
        user = NexusUser(self.site(), user_id=user_id, username="" if name is None else name.get_text(strip=True))

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

    @classmethod
    def _extract_user_info(cls, user: NexusUser, info: dict[str, bs4.Tag]) -> None:
        """从 `userdetails.php` 的最大的那个表格提取用户信息。"""
        if _LEVEL in info:
            level_img = info[_LEVEL].select_one("img")
            if level_img is not None:
                user.level = level_img.attrs.get("title", "")

        if _MANA in info:
            # 北洋园这里在数字后面跟了一个链接，总之能跑就行。
            user.mana = utils.float_or(
                "".join(c for c in info[_MANA].get_text(strip=True) if c == "." or c.isdigit())
            )

        if _INVITATIONS in info:
            invitations = info[_INVITATIONS].get_text(strip=True)
            if "没有邀请资格" not in invitations:
                user.invitations = utils.int_or(invitations)

        if _TRANSFER in info:
            # 北邮人应该是原来的 NexusPHP 吧。
            transferred = info[_TRANSFER]
            for cell in transferred.select("td"):
                text = cell.get_text(strip=True)
                if ":" not in text:
                    continue
                field, value = [s.strip() for s in text.split(":", 1)]
                if field == "分享率":
                    user.ratio = utils.float_or(value)
                elif field == "上传量":
                    user.uploaded = utils.convert_iec_size(value)
                elif field == "下载量":
                    user.downloaded = utils.convert_iec_size(value)

        if _UPLOADED in info:
            # 北洋园只有上传量。
            user.uploaded = utils.convert_iec_size(info[_UPLOADED].get_text(strip=True))

    def torrent(self, seed_id: int) -> TorrentInfo:
        """获取种子详情。"""
        page = self.client.get_soup(f"details.php?id={seed_id}&hit=1")
        title_tag = page.find("h1", recursive=True)
        if title_tag is None:
            raise ValueError("种子不存在")
        title = next(iter(title_tag.children)).text.strip()
        subtitle = self._extract_page_subtitle(page)
        cat, sec_cat = self._extract_page_categories(page)
        size = self._extract_page_size(page)
        promotions = self._extract_promotion_info(title_tag)
        tag = self._extract_tag(title_tag)
        uploaded_at = self._extract_page_upload_time(page)
        live_time = (datetime.datetime.now() - uploaded_at).total_seconds() / (24 * 60 * 60)

        peers = page.select_one("div#peercount").get_text(strip=True)
        seeder_re = re.compile("(\\d+)个做种者")
        leecher_re = re.compile("(\\d+)个下载者")
        seeders = utils.int_or(seeder_re.search(peers).group(1))
        leechers = utils.int_or(leecher_re.search(peers).group(1))
        finished = utils.int_or(page.select_one("a[href^=viewsnatches] > b").text)

        user = self._extract_user_from_a(page.select_one("h1 + table tr"))

        hash_field = [tag for tag in page.select("h1 + table b") if "Hash码" in tag.text]
        if len(hash_field) == 0:
            hs = ""
        else:
            hs = hash_field[0].next_sibling.text.strip() if hash_field[0].next_sibling is not None else ""

        return TorrentInfo(
            site=self.site(),
            title=title,
            sub_title=subtitle,
            seed_id=seed_id,
            cat=cat,
            category=TorrentInfo.convert_byr_category(cat),
            second_category=sec_cat,
            promotions=promotions,
            tag=tag,
            file_size=size,
            live_time=live_time,
            seeders=seeders,
            leechers=leechers,
            finished=finished,
            comments=0,
            uploader=user,
            uploaded=0.,
            downloaded=0.,
            ratio=0.,
            hash=hs,
        )

    def download_torrent(self, seed_id: int) -> bytes:
        res = self.client.get(f"download.php?id={seed_id}")
        return res.content

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

    @classmethod
    def _extract_promotion_info(cls, title_cell: bs4.Tag) -> TorrentPromotion:
        """
        提取表格中的促销/折扣信息。

        因为有很多种折扣信息的格式，总之暂时直接枚举。
        """
        # noinspection SpellCheckingInspection
        selectors = {
            # 促销种子：高亮显示
            "tr.free_bg": TorrentPromotion.FREE,
            "tr.twoup_bg": TorrentPromotion.X2,
            "tr.twoupfree_bg": TorrentPromotion.FREE_X2,
            "tr.halfdown_bg": TorrentPromotion.HALF_OFF,
            "tr.twouphalfdown_bg": TorrentPromotion.HALF_OFF_X2,
            "tr.thirtypercentdown_bg": TorrentPromotion.THIRTY_PERCENT,
            # 促销种子：添加标记，如'2X免费'
            "font.free": TorrentPromotion.FREE,
            "font.twoup": TorrentPromotion.X2,
            "font.twoupfree": TorrentPromotion.FREE_X2,
            "font.halfdown": TorrentPromotion.HALF_OFF,
            "font.twouphalfdown": TorrentPromotion.HALF_OFF_X2,
            "font.thirtypercent": TorrentPromotion.THIRTY_PERCENT,
            # 促销种子：添加图标
            "img.pro_free": TorrentPromotion.FREE,
            "img.pro_2up": TorrentPromotion.X2,
            "img.pro_free2up": TorrentPromotion.FREE_X2,
            "img.pro_50pctdown": TorrentPromotion.HALF_OFF,
            "img.pro_50pctdown2up": TorrentPromotion.HALF_OFF_X2,
            "img.pro_30pctdown": TorrentPromotion.THIRTY_PERCENT,
            # 促销种子：无标记 - 真的没办法
        }
        for selector, promotions in selectors.items():
            if title_cell.select_one(selector) is not None:
                return promotions
        return TorrentPromotion.NONE

    @classmethod
    def _extract_tag(cls, title_cell: bs4.Tag) -> TorrentTag:
        """提取站点对种子打的标签。"""
        selectors = {
            "font.hot": TorrentTag.TRENDING,
            "font.classic": TorrentTag.CLASSIC,
            "font.recommended": TorrentTag.RECOMMENDED,
        }
        for selector, tag in selectors.items():
            if title_cell.select_one(selector) is not None:
                return tag
        return TorrentTag.ANY

    @classmethod
    def _extract_user_from_a(cls, cell: bs4.Tag) -> NexusUser:
        user = NexusUser(cls.site())
        user_cell = cell.select_one("a[href^=userdetails]")
        if user_cell is not None:
            user.user_id, user.username = (
                cls.extract_url_id(user_cell.attrs["href"]),
                user_cell.get_text(strip=True),
            )
        else:
            user.username = "匿名"
        return user

    @classmethod
    def _extract_page_subtitle(cls, page: bs4.Tag) -> str:
        return page.select_one("#subtitle").get_text(strip=True)

    @classmethod
    def _extract_page_categories(cls, page: bs4.Tag) -> tuple[str, str]:
        cat = page.select_one("span#type").text.strip()
        sec_type = page.select_one("span#sec_type")
        sec_cat = sec_type.text.strip() if sec_type is not None else "其它"
        return cat, sec_cat

    @classmethod
    def _extract_page_size(cls, page: bs4.Tag) -> float:
        return utils.convert_iec_size(page.select_one("span#type").parent.find(text=re.compile("\\d")).text)

    @classmethod
    def _extract_page_upload_time(cls, page: bs4.Tag) -> datetime.datetime:
        return datetime.datetime.fromisoformat(page.select_one("span[title]").attrs["title"])

    @classmethod
    def _rearrange_table_cells(cls, cells):
        """
        留点表格变化的空间。

        例如北邮人给表格前面添了一列，后面的所有格子都乱了。
        """
        return cells

    def _extract_torrent_table(self, rows: bs4.element.ResultSet[bs4.Tag],
                               comment_cell: typing.Optional[int] = 2,
                               live_time_cell: typing.Optional[int] = 3,
                               size_cell: typing.Optional[int] = 4,
                               seeder_cell: typing.Optional[int] = 5,
                               leecher_cell: typing.Optional[int] = 6,
                               finished_cell: typing.Optional[int] = 7,
                               uploader_cell: typing.Optional[int] = 8,
                               uploaded_cell: typing.Optional[int] = None,
                               downloaded_cell: typing.Optional[int] = None,
                               ratio_cell: typing.Optional[int] = None,
                               details: bool = False) -> list[TorrentInfo]:
        """
        从 torrents.php 页面的种子表格中提取信息。

        提取二级分类、hash 等详情需要每个种子抓取一个页面，对服务器不太厚道。默认关闭。
        """
        torrents = []
        for row in rows:
            cells: bs4.element.ResultSet[bs4.Tag] = row.find_all("td", recursive=False)
            cells = self._rearrange_table_cells(cells)
            # cells 里依次是：
            #   0     1      2        3       4      5       6      7        8
            # 类型、题目、评论数、存活时间、大小、做种数、下载数、完成数、发布者

            cat = cells[0].select_one("img").attrs["title"]
            comments = utils.int_or(cells[comment_cell].get_text(strip=True), 0) if comment_cell is not None else 0
            uploaded_at = self._extract_updated_at(cells, live_time_cell)
            size = utils.convert_iec_size(cells[size_cell].get_text(strip=True)) if size_cell is not None else 0.
            seeders = utils.int_or(cells[seeder_cell].get_text(strip=True)) if seeder_cell is not None else 0
            leechers = utils.int_or(cells[leecher_cell].get_text(strip=True)) if leecher_cell is not None else 0
            finished = utils.int_or(cells[finished_cell].get_text(strip=True)) if finished_cell is not None else 0
            uploaded = utils.convert_iec_size(
                cells[uploaded_cell].get_text(strip=True)) if uploaded_cell is not None else 0
            downloaded = utils.convert_iec_size(
                cells[downloaded_cell].get_text(strip=True)) if downloaded_cell is not None else 0
            ratio = utils.float_or(cells[ratio_cell].get_text(strip=True)) if ratio_cell is not None else 0.
            if uploader_cell is not None:
                user = self._extract_user_from_a(cells[uploader_cell])
            else:
                user = NexusUser(self.site())

            # 标题需要一点特殊处理。
            title_cell = cells[1]
            torrent_link = title_cell.select_one("a[href^=details]")
            if "title" in torrent_link.attrs:
                title = torrent_link.attrs["title"]
            else:
                title = torrent_link.get_text(strip=True)
            byr_id = self.extract_url_id(torrent_link.attrs["href"])
            subtitle_newline = torrent_link.find_parent("td").find("br")
            if subtitle_newline is not None:
                subtitle_node = subtitle_newline.next_sibling
                subtitle = subtitle_node.get_text() if isinstance(subtitle_node, bs4.element.NavigableString) else ""
            else:
                subtitle = ""
            promotions = self._extract_promotion_info(title_cell)
            tag = self._extract_tag(title_cell)

            if details:
                remote = self.torrent(byr_id)
                second = remote.second_category
                hs = remote.hash
            else:
                second = ""
                hs = ""

            torrents.append(TorrentInfo(
                site=self.site(),
                title=title,
                sub_title=subtitle,
                seed_id=byr_id,
                cat=cat,
                category=TorrentInfo.convert_byr_category(cat),
                second_category=second,
                promotions=promotions,
                tag=tag,
                file_size=size,
                live_time=(datetime.datetime.now() - uploaded_at).total_seconds() / (60 * 60 * 24),
                seeders=seeders,
                leechers=leechers,
                finished=finished,
                comments=comments,
                uploader=user,
                uploaded=uploaded,
                downloaded=downloaded,
                ratio=ratio,
                hash=hs,
            ))
        return torrents

    @classmethod
    def _extract_updated_at(cls, cells: bs4.element.ResultSet[bs4.Tag],
                            live_time_cell: typing.Optional[int]) -> datetime.datetime:
        return (
            datetime.datetime.fromisoformat(cells[live_time_cell].select_one("span").attrs["title"])
            if live_time_cell is not None else datetime.datetime.now()
        )
