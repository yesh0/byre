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
import os
import pickle
import time
import typing
from abc import ABCMeta, abstractmethod

import bs4
import requests

_logger = logging.getLogger("byre.clients.client")
_debug, _info, _warning = _logger.debug, _logger.info, _logger.warning


class NexusClient(metaclass=ABCMeta):
    """
    所有基于 NexusPHP 的站点的基础认证接口。

    包括了管理 Cookies、会话以及发起请求的功能，
    登录并获取 Cookies 部分不同站点需要不同实现。
    """

    def __init__(
        self,
        username: str,
        password: str,
        cookie_file: str,
        proxies: typing.Optional[dict[str, str]] = None,
        request_frequency=2.0,
    ) -> None:
        #: 站点登录用户名。
        self.username = username
        #: 站点登录密码。
        self.password = password
        #: 登录会话的 Cookies 缓存文件。
        self._cookie_file = cookie_file
        #: 最后一次请求的时间（秒），用于全局限流。
        self._last_requested_at = 0.0
        #: 最大请求频率。
        self._request_freq = request_frequency
        #: 会话。
        self._session = requests.Session()
        #: 用户 ID。
        self.user_id = None
        if proxies is not None:
            self._session.proxies.update(proxies)
        self._session.headers.update(
            {
                "User-Agent": " ".join(
                    [
                        "Mozilla/5.0 (X11; Linux x86_64)",
                        "AppleWebKit/537.36 (KHTML, like Gecko)",
                        "Chrome/103.0.9999.0",
                        "Safari/537.36",
                    ]
                ),
            }
        )
        self._update_session_from_cache()

    @classmethod
    @abstractmethod
    def get_url(cls, path: str) -> str:
        """把路径补充为完整的 URL。"""
        pass

    @abstractmethod
    def _authorize_session(self):
        """进行登录请求，更新 `self._session`。"""
        pass

    def login(self, cache: bool = True) -> None:
        """登录，获取 Cookies。"""
        if cache and self._update_session_from_cache():
            _info("成功从缓存中获取会话")
            return

        self._rate_limit()
        self._authorize_session()
        self._request_finished()
        _info("成功登录")
        self._cache_session()

    def get(self, path: str, retries: int = 3, allow_redirects: bool = False):
        """使用当前会话发起请求，返回 `requests.Response`。"""
        _debug("正在请求 %s", path or "/")
        for i in range(retries):
            self._rate_limit()
            res = self._session.get(self.get_url(path), allow_redirects=allow_redirects)
            self._request_finished()

            if res.status_code == 200:
                # 未登录的话大多时候会是重定向。
                return res
            if retries > 1 and i == 0 and not self.is_logged_in():
                self.login(cache=False)
            if i != retries - 1:
                _info("第 %d 次请求失败，正在重试（%s）", i + 1, path)
                _debug(
                    "%d: 失败请求 %d (%s)",
                    i + 1,
                    res.status_code,
                    res.headers.get('location', res.headers.get('content-type')),
                )
        raise ConnectionError(f"所有 {retries} 次请求均失败")

    def get_soup(self, path: str, retries: int = 3):
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

    def close(self) -> None:
        """关闭 `requests.Session` 资源。"""
        self._session.close()

    def _update_session_from_cache(self) -> bool:
        """从缓存文件里获取 Cookies，如果登录信息有效则返回 `True`。"""
        if os.path.exists(self._cookie_file):
            with open(self._cookie_file, "rb") as file:
                cookies = pickle.load(file)
                if not isinstance(cookies, dict) or any(
                    key not in cookies for key in ["username", "cookies"]
                ):
                    _warning("缓存文件格式错误")
                    return False
                if cookies.get("username", "") != self.username:
                    _debug("前登录用户与当前用户不符")
                    return False
                self._session.cookies.clear()
                self._session.cookies.update(cookies["cookies"])
                return True
        return False

    def _cache_session(self) -> None:
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

    def _rate_limit(self):
        passed = time.time() - self._last_requested_at
        if passed < 1.0 / self._request_freq:
            time.sleep(1.0 / self._request_freq - passed)

    def _request_finished(self):
        self._last_requested_at = time.time()
