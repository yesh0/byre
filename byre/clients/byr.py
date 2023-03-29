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
import enum
import logging
import re
import time
import typing

import bs4
from overrides import override

from byre import utils
from byre.clients.api import NexusApi
from byre.clients.client import NexusClient
from byre.data import ByrUser, TorrentInfo, TorrentPromotion, TorrentTag, UserTorrentKind

_logger = logging.getLogger("byre.api")
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


class ByrSortableField(enum.Enum):
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


class ByrApi(NexusApi):
    """北邮人 PT 站爬虫，提供站点部分信息的读取 API。"""

    def list_torrents(self, page: int = 0, promotion: TorrentPromotion = TorrentPromotion.ANY,
                      tag: TorrentTag = TorrentTag.ANY,
                      sorted_by: ByrSortableField = ByrSortableField.ID,
                      desc: bool = True) -> list[TorrentInfo]:
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

    def torrent(self, seed_id: int) -> TorrentInfo:
        """获取种子详情。"""
        page = self.client.get_soup(f"details.php?id={seed_id}&hit=1")
        title_tag = page.find("h1", recursive=True)
        if title_tag is None:
            raise ValueError("种子不存在")
        title = next(iter(title_tag.children)).text.strip()
        subtitle = page.select_one("#subtitle").get_text(strip=True)
        cat = page.select_one("span#type").text.strip()
        sec_type = page.select_one("span#sec_type")
        sec_cat = sec_type.text.strip() if sec_type is not None else "其它"
        size = utils.convert_nexus_size(page.select_one("span#type").parent.find(text=re.compile("\\d")).text)
        promotions = self._extract_promotion_info(title_tag)
        tag = self._extract_tag(title_tag)
        uploaded_at = datetime.datetime.fromisoformat(page.select_one("span[title]").attrs["title"])
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
            # cells 里依次是：
            #   0     1      2        3       4      5       6      7        8
            # 类型、题目、评论数、存活时间、大小、做种数、下载数、完成数、发布者

            cat = cells[0].select_one("img").attrs["title"]
            comments = utils.int_or(cells[comment_cell].get_text(strip=True), 0) if comment_cell is not None else 0
            uploaded_at = (
                datetime.datetime.fromisoformat(cells[live_time_cell].select_one("span").attrs["title"])
                if live_time_cell is not None else datetime.datetime.now()
            )
            size = utils.convert_nexus_size(cells[size_cell].get_text(strip=True)) if size_cell is not None else 0.
            seeders = utils.int_or(cells[seeder_cell].get_text(strip=True)) if seeder_cell is not None else 0
            leechers = utils.int_or(cells[leecher_cell].get_text(strip=True)) if leecher_cell is not None else 0
            finished = utils.int_or(cells[finished_cell].get_text(strip=True)) if finished_cell is not None else 0
            uploaded = utils.convert_nexus_size(
                cells[uploaded_cell].get_text(strip=True)) if uploaded_cell is not None else 0
            downloaded = utils.convert_nexus_size(
                cells[downloaded_cell].get_text(strip=True)) if downloaded_cell is not None else 0
            ratio = utils.float_or(cells[ratio_cell].get_text(strip=True)) if ratio_cell is not None else 0.
            if uploader_cell is not None:
                user = self._extract_user_from_a(cells[uploader_cell])
            else:
                user = ByrUser()

            # 标题需要一点特殊处理。
            title_cell = cells[1]
            torrent_link = title_cell.select_one("a[href^=details]")
            title = torrent_link.attrs["title"]
            byr_id = ByrApi.extract_url_id(torrent_link.attrs["href"])
            subtitle_newline = torrent_link.find_parent("td").find("br")
            if subtitle_newline is not None:
                subtitle_node = subtitle_newline.next_sibling
                subtitle = subtitle_node.get_text() if isinstance(subtitle_node, bs4.element.NavigableString) else ""
            else:
                subtitle = ""
            promotions = ByrApi._extract_promotion_info(title_cell)
            tag = ByrApi._extract_tag(title_cell)

            if details:
                time.sleep(0.5)
                remote = self.torrent(byr_id)
                second = remote.second_category
                hs = remote.hash
            else:
                second = ""
                hs = ""

            torrents.append(TorrentInfo(
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

    @staticmethod
    def _extract_promotion_info(title_cell: bs4.Tag) -> TorrentPromotion:
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

    @staticmethod
    def _extract_tag(title_cell: bs4.Tag) -> TorrentTag:
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

    @staticmethod
    def _extract_user_from_a(cell: bs4.Tag) -> ByrUser:
        user = ByrUser()
        user_cell = cell.select_one("a[href^=userdetails]")
        if user_cell is not None:
            user.user_id, user.username = (
                ByrApi.extract_url_id(user_cell.attrs["href"]),
                user_cell.get_text(strip=True),
            )
        else:
            user.username = "匿名"
        return user
