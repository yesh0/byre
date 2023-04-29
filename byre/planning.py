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

"""根据评分给出种子选择结果。"""

import logging
import os
import typing
from dataclasses import dataclass

import psutil

from byre.clients.data import LocalTorrent, TorrentInfo
from byre.storage import TorrentStore, TorrentDO

_logger = logging.getLogger("byre.planning")
_debug, _warning = _logger.debug, _logger.warning


@dataclass
class SpaceChange:
    before: float
    to_be_deleted: float
    to_be_downloaded: float
    after: float


@dataclass
class PlannerConfig:
    """储存位置的配置。"""

    max_total_size: float
    """种子总大小上限字节数。"""

    max_download_size: float
    """单次下载大小上限字节数。"""

    download_dir: str
    """下载目录，用于计算剩余空间上限。"""

    remaining: float = 0.
    """剩余空间，用于计算过程中的临时储存。"""

    def get_disk_remaining(self):
        """下载目录剩余空间。"""
        remaining = psutil.disk_usage(self.download_dir).free
        return remaining

    def clamp(self, used: float):
        """
        如果用户设置的大小上限超过可用空间，则进行调整；如果用户设为了 0，则设为最大。

        因为有可能存在正在下载的种子，已用空间的估计不一定正确，所以需要提供 used 参数。
        """
        disk_remaining = self.get_disk_remaining()
        # 会有误差，所以可能会可用空间出现差一点点的情况……
        max_total_size = used + disk_remaining
        if self.max_total_size > 0:
            max_total_size = min(max_total_size, self.max_total_size)
        self.max_total_size = max_total_size

    def is_under_current_dir(self, torrent: LocalTorrent):
        """判断种子是否属于当前下载路径。"""
        parent = os.path.realpath(torrent.torrent.save_path)
        while os.path.dirname(parent) != parent:
            parent = os.path.dirname(parent)
            try:
                if os.path.samefile(parent, self.download_dir):
                    # 暂时不支持嵌套树状结构（如 disk1 在 /mnt/disk1，disk2 在 /mnt/disk1/disk2）。
                    return True
            except FileNotFoundError:
                pass
        else:
            return False

    def downloader(self, remaining: float, scored_local: list[tuple[LocalTorrent, float]],
                   removable_hashes: dict[str, float], duplicates: dict[str, list[LocalTorrent]]):
        downloaded = 0.
        i = 0
        # 以北邮人种子为主。
        scored_local = [t for t in scored_local if t[0].site == "byr"]

        def try_download(candidate: TorrentInfo,
                         score: float,
                         exists: bool
                         ) -> typing.Optional[tuple[float, list[tuple[LocalTorrent, float]]]]:
            nonlocal downloaded, i, remaining, scored_local, self
            if downloaded + candidate.file_size > self.max_download_size:
                return None
            if score == 0.:
                return None
            # 能下载就直接下载。
            if candidate.file_size < self.remaining or exists:
                if not exists:
                    self.remaining -= candidate.file_size
                    downloaded += candidate.file_size
                return 0, []
            # 否则尝试移除分数相对低的本地种子。
            removable_size = 0
            removable = []
            for j, (torrent, torrent_score) in enumerate(scored_local[i:]):
                # 分数小于零的意味着不可移除（正在下载或上传中等等）。
                if torrent_score >= score or torrent_score < 0:
                    continue
                if any(removable_hashes[t.torrent.hash] < 0 for t in duplicates[torrent.torrent.hash]):
                    continue
                torrent_score += sum(removable_hashes[t.torrent.hash] for t in duplicates[torrent.torrent.hash])
                # 我们以北邮人为主，其它站点说实话感觉不太活跃，分数不会太高。
                if torrent_score >= score:
                    return None
                removable_size += torrent.torrent.size
                removable.append((torrent, torrent_score))
                if candidate.file_size < removable_size + remaining:
                    break
            else:
                return None
            remaining = remaining + removable_size - candidate.file_size
            downloaded += candidate.file_size
            i = j + 1
            return candidate.file_size, removable

        return try_download


class Planner:
    """贪心选择种子。"""

    def __init__(self, configs: list[PlannerConfig]):
        self.configs = configs

    def plan(self,
             scored_local: list[tuple[LocalTorrent, float]],
             remote: list[tuple[TorrentInfo, float]],
             cache: TorrentStore,
             exists=False,
             ) -> tuple[list[tuple[LocalTorrent, str]], list[tuple[TorrentInfo, str]], dict[str, list[LocalTorrent]]]:
        # duplicates 用于检查共用文件的种子。
        used_spaces, local, duplicates = self.merge_torrent_info(scored_local, cache)
        # removable_hashes 用于检查共用文件的种子是否可以移除，以及它们共享分数。
        removable_hashes: dict[str, float] = {}
        for config in self.configs:
            removable_hashes.update(dict((t.torrent.hash, score) for t, score in local[config.download_dir] or []))

        planners = {}
        for config in self.configs:
            used_space = used_spaces.get(config.download_dir, 0.)
            config.clamp(used_space)
            planners[config.download_dir] = config.downloader(
                config.max_total_size - used_space,
                local.get(config.download_dir, []),
                removable_hashes,
                duplicates,
            )

        removable, downloadable = [], []
        for candidate, score in remote:
            plans = {}
            for config in self.configs:
                plan = planners[config.download_dir](candidate, score, exists)
                if plan is not None:
                    plans[config.download_dir] = plan
            if len(plans) == 0:
                continue
            _, _, directory = sorted([
                (to_be_downloaded, sum(score for _, score in rm_list), directory)
                for directory, (to_be_downloaded, rm_list) in plans.items()
            ])[0]
            removable.extend((torrent, directory) for torrent, _ in plans[directory][1])
            downloadable.append((candidate, directory))
        return removable, downloadable, duplicates

    def estimate(self, local_torrents: list[tuple[LocalTorrent, float]], removable: list[tuple[LocalTorrent, str]],
                 downloadable: list[tuple[TorrentInfo, str]], cache: TorrentStore, exists=False,
                 ) -> tuple[dict[str, SpaceChange], dict[str, tuple[list[TorrentInfo], list[LocalTorrent]]]]:
        used, _, _ = self.merge_torrent_info(local_torrents, cache)
        stats = {}
        grouped = {}
        for config in self.configs:
            used_space = used.get(config.download_dir, 0.)
            deleted = [t for t, directory in removable if config.is_under_current_dir(t)]
            downloaded = [] if exists else [t for t, directory in downloadable
                                            if directory == config.download_dir]
            downloaded_size = sum(t.file_size for t in downloaded)
            deleted_size = sum(t.torrent.size for t in deleted)
            stats[config.download_dir] = SpaceChange(
                before=used_space,
                to_be_deleted=deleted_size,
                to_be_downloaded=downloaded_size,
                after=used_space - deleted_size + downloaded_size,
            )
            grouped[config.download_dir] = (
                downloaded,
                deleted,
            )
        return stats, grouped

    def merge_torrent_info(self, local_torrents: list[tuple[LocalTorrent, float]],
                           cache: TorrentStore):
        total = {}
        local = {}
        path_torrents = {}
        cached = cache.save_extra_torrents([t for t, _ in local_torrents])
        torrent: LocalTorrent
        info: TorrentDO
        for (torrent, score), info in zip(local_torrents, cached):
            for config in self.configs:
                if config.is_under_current_dir(torrent):
                    if info.path_hash in path_torrents:
                        path_torrents[info.path_hash].append(torrent)
                    else:
                        path_torrents[info.path_hash] = [torrent]
                        if config.download_dir in total:
                            total[config.download_dir] += torrent.torrent.size
                        else:
                            total[config.download_dir] = torrent.torrent.size
                    if config.download_dir not in local:
                        local[config.download_dir] = []
                    local[config.download_dir].append((torrent, score))
                    break
            else:
                _warning("跳过不属于任何下载目录的种子：%s", torrent.torrent.name)

        duplicates: dict[str, list[LocalTorrent]] = {}
        for _, same_torrents in path_torrents.items():
            if len(same_torrents) > 1:
                hashes = dict((t.torrent.hash, t) for t in same_torrents)
                _debug("共享相同文件的种子：\n%s", "\n".join(
                    f"{t.torrent.hash} {t.torrent.name}" for t in same_torrents))
                for torrent in same_torrents:
                    duplicates[torrent.torrent.hash] = [hashes[h] for h in (hashes.keys() - {torrent.torrent.hash})]
            else:
                duplicates[same_torrents[0].torrent.hash] = []
        return total, local, duplicates
