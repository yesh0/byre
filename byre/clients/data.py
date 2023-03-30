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

"""北邮人 PT 站的用户、种子等信息。"""

import enum
import time
import typing
from dataclasses import dataclass

import qbittorrentapi


@dataclass
class NexusUser:
    """一位 NexusPHP 站点用户。"""

    user_id: int = 0
    """用户 ID。"""

    username: str = ""

    level: str = ""
    """用户等级。"""

    mana: float = 0.
    """魔力值。"""

    invitations: int = 0
    """邀请数量。"""

    ranking: int = 0
    """上传排行。"""

    ratio: float = -1.
    """分享率。"""

    uploaded: float = 0.
    """上传量（GB）。"""

    downloaded: float = 0.
    """下载量（GB）。"""

    seeding: int = 0
    """当前活动上传数。"""

    downloading: int = 0
    """当前活动下载数。"""

    connectable: bool = False
    """用户客户端可连接状态。"""


CATEGORIES = {
    "电影": "Movies",
    "剧集": "TVSeries",
    "动漫": "Anime",
    "音乐": "Music",
    "综艺": "VarietyShows",
    "游戏": "Games",
    "软件": "Software",
    "资料": "Documents",
    "体育": "Sports",
    "纪录": "Documentaries",
    # 北洋园特有类别。
    "移动视频": "iPad",
}

PROMOTION_THIRTY_DOWN = "thirty_down"

PROMOTION_HALF_DOWN = "half_down"

PROMOTION_TWO_UP = "two_up"

PROMOTION_FREE = "free"


class TorrentPromotion(enum.Enum):
    """
    种子促销种类。

    前面是人类看得懂的描述，后面的数字是北邮人上对应的数字 spstate，用于查询。
    """
    ANY = (), 0
    NONE = (), 1
    FREE = (PROMOTION_FREE,), 2
    X2 = (PROMOTION_TWO_UP,), 3
    FREE_X2 = (PROMOTION_FREE, PROMOTION_TWO_UP), 4
    HALF_OFF = (PROMOTION_HALF_DOWN,), 5
    HALF_OFF_X2 = (PROMOTION_HALF_DOWN, PROMOTION_TWO_UP), 6
    THIRTY_PERCENT = (PROMOTION_THIRTY_DOWN,), 7

    def __contains__(self, item) -> bool:
        if self == TorrentPromotion.ANY:
            return True
        return item in self.get_promotions()

    def get_promotions(self) -> typing.Iterable[str]:
        return self.value[0]

    def get_int(self) -> int:
        return self.value[1]

    def __str__(self) -> str:
        texts = {
            PROMOTION_FREE: "免费",
            PROMOTION_TWO_UP: "2x上传",
            PROMOTION_HALF_DOWN: "50%下载",
            PROMOTION_THIRTY_DOWN: "30%下载",
        }
        return ", ".join(texts[p] for p in self.get_promotions()) or "无"


class TorrentTag(enum.Enum):
    """
    站点管理员给种子打的标签，如热门、经典、推荐等等。

    数字是北邮人上对应的数字 pktype。
    """
    ANY = 0
    TRENDING = 1
    CLASSIC = 2
    RECOMMENDED = 3


class UserTorrentKind(enum.Enum):
    """
    与用户相关的种子的类型，用于 getusertorrentlistajax.php 端点。

    后面的数字值没有任何意义。
    """
    UPLOADED = 1
    SEEDING = 2
    LEECHING = 3
    COMPLETED = 4
    INCOMPLETE = 5


@dataclass
class TorrentInfo:
    """从北邮人上抓取来的种子信息。"""

    title: str
    """种子标题。"""

    sub_title: str
    """种子副标题。"""

    seed_id: int
    """种子 id，最好不要与 transmission 的种子 id 混淆。"""

    cat: str
    """分类（“电影”、“软件”这种）。"""

    category: str
    """英文分类（变成了“Movies”、“Software”这种）。"""

    second_category: str
    """二级分类（“北美”“动画”这种，只有中文了，希望路径不会出问题）。"""

    promotions: TorrentPromotion
    """打折标签（免费、2x上传这种，提取成为“free”“two_up”等）。"""

    tag: TorrentTag
    """站点推荐（热门、经典、推荐这种）。"""

    file_size: float
    """种子总大小（GB 或是 1000 ** 3 字节）。"""

    live_time: float
    """存活时间（天）。"""

    seeders: int
    """上传者人数。"""

    leechers: int
    """下载者人数。"""

    finished: int
    """已完成的下载数。"""

    comments: int
    """评论数。"""

    uploader: NexusUser
    """上传者。"""

    uploaded: float
    """当前用户上传量。"""

    downloaded: float
    """当前用户下载量（GB）。"""

    ratio: float
    """当前用户分享率。"""

    hash: str
    """种子的 hash 值。"""

    @staticmethod
    def convert_byr_category(cat: str) -> str:
        return CATEGORIES.get(cat, "Others")


@dataclass
class LocalTorrent:
    torrent: qbittorrentapi.TorrentDictionary
    """本地 qBittorrent 管理的种子。"""

    seed_id: int
    """对应的北邮人种子 ID。"""

    info: typing.Optional[TorrentInfo]
    """种子在北邮人上的信息。"""

    def estimate_info(self) -> TorrentInfo:
        """从本地信息估计种子信息。"""
        if self.info is not None:
            return self.info
        return TorrentInfo(
            title=self.torrent.name,
            sub_title="",
            seed_id=self.seed_id,
            cat="",
            category=self.torrent.category,
            second_category="",
            promotions=TorrentPromotion.NONE,
            tag=TorrentTag.ANY,
            file_size=self.torrent.size / 1000 ** 3,
            live_time=(time.time() - self.torrent.last_activity) / (24 * 60 * 60),
            seeders=self.torrent.num_complete,
            leechers=self.torrent.num_incomplete,
            finished=0,
            comments=0,
            uploader=NexusUser(),
            uploaded=self.torrent.uploaded / 1000 ** 3,
            downloaded=self.torrent.downloaded / 1000 ** 3,
            ratio=self.torrent.ratio,
            hash=self.torrent.hash,
        )
