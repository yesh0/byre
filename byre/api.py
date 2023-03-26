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
import os
import pickle
import re
import time
import typing
from urllib.parse import parse_qs, urlparse

import bs4
import requests

from byre import utils
from byre.data import ByrUser, TorrentInfo, TorrentPromotion, TorrentTag

_logger = logging.getLogger("byre.api")
_debug, _info, _warning, _fatal = _logger.debug, _logger.info, _logger.warning, _logger.fatal


class ByrClient:
    """封装了 `requests.Session`，负责登录、管理会话、发起请求。"""

    username: str
    """北邮人 PT 站用户名。"""

    password: str
    """北邮人 PT 站账号密码。"""

    _cookie_file: str
    """登录会话的 Cookies 缓存文件。"""

    _retry_delay: float
    """请求重试的等待间隔（秒）。"""

    def __init__(
            self,
            username: str,
            password: str,
            cookie_file="byr.cookies",
            retry_delay=1.,
            proxies: typing.Union[dict[str, str], None] = None
    ) -> None:
        self.username = username
        self.password = password
        self._cookie_file = cookie_file
        self._retry_delay = retry_delay
        self._decaptcha = None
        self._session = requests.Session()
        if proxies is not None:
            self._session.proxies.update(proxies)
        self._session.headers.update({
            "User-Agent": " ".join([
                "Mozilla/5.0 (X11; Linux x86_64)",
                "AppleWebKit/537.36 (KHTML, like Gecko)",
                "Chrome/103.0.9999.0",
                "Safari/537.36",
            ]),
        })

    def login(self, cache=True):
        """登录，获取 Cookies。"""
        if cache and self._update_session_from_cache():
            _info("成功从缓存中获取会话")
            return

        self._authorize_session()
        _info("成功登录")
        self._cache_session()

    def get(self, path: str, retries=3, allow_redirects=False):
        """使用当前会话发起请求，返回 `requests.Response`。"""
        _debug("正在请求 %s", path)
        for i in range(retries):
            res = self._session.get(ByrClient._get_url(path), allow_redirects=allow_redirects)
            if res.status_code == 200:
                # 未登录的话大多时候会是重定向。
                return res
            if i != retries - 1:
                _info("第 %d 次请求失败，正在重试（%s）", i + 1, path)
                time.sleep(self._retry_delay)
        raise ConnectionError(f"所有 {retries} 次请求均失败")

    def get_soup(self, path: str, retries=3):
        """使用当前会话发起请求，返回 `bs4.BeautifulSoup`。"""
        res = self.get(path, retries=retries)
        return bs4.BeautifulSoup(res.content, "html.parser")

    def is_logged_in(self) -> bool:
        """随便发起一个请求看看会不会被重定向到登录页面。"""
        try:
            self.get("", retries=1)
            return True
        except ConnectionError:
            return False

    def close(self):
        """关闭 `requests.Session` 资源。"""
        self._session.close()

    def _update_session_from_cache(self):
        """从缓存文件里获取 Cookies，如果登录信息有效则返回 `True`。"""
        if os.path.exists(self._cookie_file):
            with open(self._cookie_file, "rb") as file:
                cookies = pickle.load(file)
                if (
                        not isinstance(cookies, dict)
                        or any(key not in cookies for key in ["username", "cookies"])
                ):
                    _warning("缓存文件格式错误")
                    return False
                if cookies.get("username", "") != self.username:
                    _debug("前登录用户与当前用户不符")
                    return False
                self._session.cookies.clear()
                self._session.cookies.update(cookies["cookies"])
                if not self.is_logged_in():
                    _debug("可能是缓存的登录信息过期了")
                    return False
                return True
        return False

    @staticmethod
    def _get_url(path: str) -> str:
        return "https://byr.pt/" + path

    def _authorize_session(self):
        """进行登录请求，更新 `self._session`。"""
        # 懒加载验证码（模型以及大块的依赖）。
        import io
        from PIL import Image
        import byre.decaptcha as decaptcha
        if self._decaptcha is None:
            # 重用对象，避免重复创建。
            self._decaptcha = decaptcha.DeCaptcha()
            self._decaptcha.load_model(decaptcha.model_file())

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

    def _cache_session(self):
        """保存 `self._session.cookies`。"""
        cookies = {
            "username": self.username,
            "cookies": self._session.cookies.get_dict(),
        }
        path = os.path.dirname(self._cookie_file) or os.path.curdir
        if not os.path.exists(path):
            os.makedirs(path)
        with open(self._cookie_file, "wb") as file:
            pickle.dump(cookies, file)


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


_LEVEL = "等级"
_MANA = "魔力值"
_INVITATIONS = "邀请"
_TRANSFER = "传输"


class ByrApi:
    """北邮人 PT 站爬虫，提供站点部分信息的读取 API。"""

    client: ByrClient

    _user_id = 0
    """当前用户 ID。"""

    def __init__(self, client: ByrClient) -> None:
        self.client = client
        if not client.is_logged_in():
            client.login()

    def close(self):
        """关闭所用的资源。"""
        self.client.close()

    def current_user_id(self):
        """获取当前用户 ID。"""
        if self._user_id != 0:
            return self._user_id
        page = self.client.get_soup("")
        # noinspection PyTypeChecker
        user_id = self.extract_url_id(page.select("a[class=User_Name]")[0].attrs["href"])
        _debug("提取的用户 ID 为：%d", user_id)
        self._user_id = user_id
        return user_id

    def user_info(self, user_id=0):
        """获取用户信息。"""
        if user_id == 0:
            user_id = self.current_user_id()

        page = self.client.get_soup(f"userdetails.php?id={user_id}")
        user = ByrUser()

        user.user_id = user_id

        name = page.find("h1")
        user.username = "" if name is None else name.get_text(strip=True)

        info_entries = page.select("td.embedded>table>tr")
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

    def list_torrents(self, page=0, promotion=TorrentPromotion.ANY, tag=TorrentTag.ANY, sorted_by=ByrSortableField.ID,
                      desc=True):
        """从 torrents.php 页面提取信息。"""
        order = "desc" if desc else "asc"
        page = self.client.get_soup(
            f"torrents.php?page={page}&spstate={promotion.get_int()}"
            f"&pktype={tag.value}&sort={sorted_by.value}&type={order}"
        )
        return self._extract_torrent_table(page.select("table.torrents > form > tr")[1:])

    def list_user_torrents(self, kind="seeding"):
        """从 Ajax API 获取用户正在上传的种子列表。"""
        # noinspection SpellCheckingInspection
        page = self.client.get_soup(f"getusertorrentlistajax.php?userid={self.current_user_id()}&type={kind}")
        # 表格的格式：
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

    def download_torrent(self, seed_id: int):
        res = self.client.get(f"download.php?id={seed_id}")
        return res.content

    def torrent_second_category(self, seed_id: int):
        """获取种子的二级类型，用于细分种子，毕竟谁知道最后会下多少种子呢。"""
        page = self.client.get_soup(f"details.php?id={seed_id}&hit=1")
        sec_type = page.select_one("span#sec_type")
        return sec_type.text if sec_type is not None else "其它"

    def torrent(self, seed_id: int):
        """获取种子详情。"""
        page = self.client.get_soup(f"details.php?id={seed_id}&hit=1")
        title_tag = page.find("h1", recursive=True)
        if title_tag is None:
            raise ValueError("种子不存在")
        title = next(iter(title_tag.children)).text.strip()
        subtitle = page.select_one("#subtitle").get_text(strip=True)
        cat = page.select_one("span#type").text.strip()
        sec_cat = page.select_one("span#sec_type").text.strip()
        size = utils.convert_byr_size(page.select_one("span#type").parent.find(text=re.compile("\\d")).text)
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
        )

    @staticmethod
    def extract_url_id(href: str):
        return int(parse_qs(urlparse(href).query)["id"][0])

    @staticmethod
    def _extract_user_info(user: ByrUser, info: dict[str, bs4.Tag]):
        """从 `userdetails.php` 的最大的那个表格提取用户信息。"""
        if _LEVEL in info:
            level_img = info[_LEVEL].select_one("img")
            if level_img is not None:
                user.level = level_img.attrs.get("title", "")

        if _MANA in info:
            user.mana = float(info[_MANA].get_text(strip=True))

        if _INVITATIONS in info:
            invitations = info[_INVITATIONS].get_text(strip=True)
            if "没有邀请资格" not in invitations:
                user.invitations = int(invitations)

        if _TRANSFER in info:
            transferred = info[_TRANSFER]
            for cell in transferred.select("td"):
                text = cell.get_text(strip=True)
                if ":" not in text:
                    continue
                field, value = [s.strip() for s in text.split(":", 1)]
                if field == "分享率":
                    user.ratio = float(value)
                elif field == "上传量":
                    user.uploaded = utils.convert_byr_size(value)
                elif field == "下载量":
                    user.downloaded = utils.convert_byr_size(value)

    @staticmethod
    def _extract_info_bar(user: ByrUser, page: bs4.Tag):
        """从页面的用户信息栏提取一些信息（就不重复提取 `_extract_user_info` 能提取的了）。"""
        ranking_tag = next(
            tag for tag in page.select("#info_block font.color_bonus") if "上传排行" in tag.text
        )
        ranking = str(ranking_tag.next_sibling).strip()
        if ranking.isdigit():
            user.ranking = int(ranking)

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

    def _extract_torrent_table(self, rows: bs4.element.ResultSet[bs4.Tag], comment_cell: typing.Optional[int] = 2,
                               live_time_cell: typing.Optional[int] = 3, size_cell=4,
                               seeder_cell=5, leecher_cell=6, finished_cell: typing.Optional[int] = 7,
                               uploader_cell: typing.Optional[int] = 8, uploaded_cell: typing.Optional[int] = None,
                               downloaded_cell: typing.Optional[int] = None, ratio_cell: typing.Optional[int] = None,
                               sec_type=False):
        """
        从 torrents.php 页面的种子表格中提取信息。

        提取二级分类需要每个种子抓取一个页面，对服务器不太厚道。默认关闭。
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
            size = utils.convert_byr_size(cells[size_cell].get_text(strip=True))
            seeders = utils.int_or(cells[seeder_cell].get_text(strip=True))
            leechers = utils.int_or(cells[leecher_cell].get_text(strip=True))
            finished = utils.int_or(cells[finished_cell].get_text(strip=True)) if finished_cell is not None else 0
            uploaded = utils.convert_byr_size(
                cells[uploaded_cell].get_text(strip=True)) if uploaded_cell is not None else 0
            downloaded = utils.convert_byr_size(
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

            if sec_type:
                time.sleep(0.5)
                second = self.torrent_second_category(byr_id)
            else:
                second = ""

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
    def _extract_user_from_a(cell: bs4.Tag):
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
