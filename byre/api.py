# Copyright (C) 2023 yesh
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
import os
import pickle
import time
import typing
from urllib.parse import parse_qs, urlparse

import bs4
import requests

from byre import utils
from byre.data import ByrUser

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
        _info("第 %d 次请求失败，正在重试（%s）", i+1, path)
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

  def _authorize_session(self, retries=5):
    """进行登录请求，更新 `self._session`。"""
    # 加载时间挺长的，懒加载验证码这部分。
    import ddddocr  # pylint: disable=import-outside-toplevel
    if self._decaptcha is None:
      # 重用对象，避免重复创建。
      self._decaptcha = ddddocr.DdddOcr(show_ad=False)

    self._session.cookies.clear()

    for i in range(retries):
      login_page = self.get_soup("login.php")
      img_url = self._get_url(
        login_page.select("#nav_block > form > table > tr:nth-of-type(3) img")[0].attrs["src"]
      )
      captcha_text = self._decaptcha.classification(self._session.get(img_url).content)
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
      if i != retries - 1:
        _info("第 %d 次登录请求失败，正在进行重试", i+1)
        time.sleep(self._retry_delay)
    raise ConnectionError(f"所有 {retries} 次登录请求均失败")

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

_LEVEL = "等级"
_MANA = "魔力值"
_INVITATIONS = "邀请"
_TRANSFER = "传输"

class ByrApi:
  """北邮人 PT 站爬虫，提供站点部分信息的读取 API。"""

  client: ByrClient

  _user_id=0
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
    user_id = int(
      parse_qs(urlparse(page.select("a[class=User_Name]")[0].attrs["href"]).query)["id"][0]
    )
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
      cells: bs4.ResultSet[bs4.Tag] = entry.find_all("td", recursive=False)
      if len(cells) != 2:
        continue
      info[cells[0].get_text(strip=True)] = cells[1]

    self._extract_user_info(user, info)
    if user_id == self.current_user_id():
      self._extract_info_bar(user, page)
    return user

  def _extract_user_info(self, user: ByrUser, info: dict[str, bs4.Tag]):
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

  def _extract_info_bar(self, user: ByrUser, page: bs4.Tag):
    """从页面的用户信息栏提取一些信息（就不重复提取 `_extract_user_info` 能提取的了）。"""
    ranking_tag = next(
      tag for tag in page.select("#info_block font.color_bonus") if "上传排行" in tag.text
    )
    ranking = str(ranking_tag.next).strip()
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

    connectability = page.select_one("#info_block font[color=green]")
    user.connectable = connectability is not None and "是" in connectability.text
