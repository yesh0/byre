#  Copyright (C) 2022 WhymustIhaveaname/ByrBtAutoDownloader
#  Copyright (C) 2023 Yesh
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""给种子评分的模块。"""

import math
import time
from dataclasses import dataclass

from byre.data import TorrentInfo, PROMOTION_TWO_UP, PROMOTION_FREE, PROMOTION_HALF_DOWN, PROMOTION_THIRTY_DOWN, \
    LocalTorrent


def _piecewise_linear(points: list[tuple[float, float]], x: float):
    """分段线性函数。"""

    if len(points) == 0:
        raise ValueError("至少需要一个点")

    if x < points[0][0]:
        return points[0][1]

    for left, right in zip(points, points[1:]):
        x1, y1 = left
        x2, y2 = right
        if x1 > x2:
            raise Exception("X 坐标应该单调递增")

        if x1 <= x < x2:
            return (y2 - y1) / (x2 - x1) * (x - x1) + y1

    return points[-1][1]


def _sigmoid(x: float):
    try:
        return 1 / (1 + math.exp(-x))
    except OverflowError:
        return 0.


@dataclass
class Scorer:
    """给种子评分判断一个种子值不值得下载做种/删除腾空。"""

    free_weight: float
    """免费种子所能额外给予的权重（半价等的权重由此算出）。"""

    cost_recovery_days: float
    """滤过几天内难以到达 1.0 分享率的种子。"""

    removal_exemption_days: float
    """不会移除才刚刚下下来几天的种子。"""

    file_size_weights = [(0., 0.1), (2., 1.0), (15., 1.0), (60., 0.1), (500., 0.01)]
    """按文件大小来计算的评分系数，由点指定的分段线性函数。"""

    leecher_weights = [(0., 0.1), (2., 0.6), (6., 0.9), (10., 1.0)]
    """按下载者数量来计算的评分系数，主要用来表示太少人下载时的风险程度。"""

    def score_downloading(self, torrent: TorrentInfo, recovery=True):
        """为某个种子的下载价值评分，输出是下载完成后每天预期的分享率。"""
        if torrent.seeders <= 0:
            # 没法下。
            return 0.
        if torrent.leechers <= 0:
            # 就贪心。
            return 0.

        finished_ratio = 0.5 * _sigmoid(-torrent.live_time + 30) + 0.5
        value = (
                ((finished_ratio * torrent.finished + torrent.leechers * 1.5)
                 / (torrent.live_time + 2) + torrent.leechers)
                / (torrent.seeders + torrent.leechers + 1)
        )
        value *= _piecewise_linear(self.leecher_weights, torrent.leechers)

        if PROMOTION_TWO_UP in torrent.promotions:
            value *= 2

        discounts = {
            PROMOTION_FREE: 1.,
            PROMOTION_HALF_DOWN: 0.5,
            PROMOTION_THIRTY_DOWN: 0.7,
        }
        for promotion, discount in discounts.items():
            if promotion in torrent.promotions:
                value *= 1 + self.free_weight * discount
                break

        size_ratio = _sigmoid((finished_ratio + torrent.finished) / (torrent.live_time + 1) - 20)
        value *= (1 - size_ratio) * _piecewise_linear(self.file_size_weights, torrent.file_size) + size_ratio

        if recovery and value < 1 / self.cost_recovery_days:
            return 0.

        return value

    def score_uploading(self, torrent: LocalTorrent):
        """为某个正在上传的种子的价值评分，输出是每天预期的分享率。负分不应被删除。"""
        if torrent.torrent.upspeed > 5 * 1024:
            return -1.
        if torrent.torrent.amount_left > 0:
            return -1.
        if torrent.torrent.completion_on + (self.removal_exemption_days * 24 * 60 * 60) > time.time():
            return -1.
        info = torrent.estimate_info()
        if info.seeders <= 1:
            return -1.
        return self.score_downloading(info, recovery=False)
