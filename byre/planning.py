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

from dataclasses import dataclass

from byre.clients.data import LocalTorrent, TorrentInfo
from byre.storage import TorrentStore


@dataclass
class SpaceChange:
    before: float
    to_be_deleted: float
    to_be_downloaded: float
    after: float


@dataclass
class Planner:
    """贪心选择种子。"""

    max_total_size: float
    """GB 计的种子总大小上限。"""

    max_download_size: float
    """GB 计的单次下载大小上限。"""

    def plan(self,
             local_torrents: list[LocalTorrent],
             local: list[tuple[LocalTorrent, float]],
             remote: list[tuple[TorrentInfo, float]],
             cache: TorrentStore,
             ) -> tuple[list[LocalTorrent], list[TorrentInfo], dict[str, set[str]]]:
        # duplicates 用于检查共用文件的种子。
        used, duplicates = self.merge_torrent_info(local_torrents, cache)
        # removable_hashes 用于检查共用文件的种子是否可以移除，以及它们共享分数。
        removable_hashes = dict((t.torrent.hash, score) for t, score in local)

        remaining = self.max_total_size - used
        i = 0
        removable, downloadable = [], []
        downloaded = 0.
        for candidate, score in remote:
            if downloaded + candidate.file_size > self.max_download_size:
                continue
            # 能下载就直接下载。
            if candidate.file_size < remaining:
                remaining -= candidate.file_size
                downloadable.append(candidate)
                downloaded += candidate.file_size
                continue
            # 否则尝试移除分数相对低的本地种子。
            removable_size = 0
            j = i
            for j, (torrent, torrent_score) in enumerate(local[i:]):
                if torrent_score >= score:
                    break
                torrent_score += sum(removable_hashes[t] for t in duplicates[torrent.torrent.hash])
                # 我们以北邮人为主，其它站点说实话感觉不太活跃，分数不会太高。
                if torrent_score >= score:
                    break
                removable_size += torrent.torrent.size / 1000 ** 3
                if candidate.file_size < removable_size + remaining:
                    break
            if candidate.file_size < removable_size + remaining:
                remaining = remaining + removable_size - candidate.file_size
                removable.extend(t for t, _ in local[i:j + 1])
                i = j + 1
                downloadable.append(candidate)
                downloaded += candidate.file_size
                continue
        return removable, downloadable, duplicates

    def estimate(self, local_torrents: list[LocalTorrent], removable: list[LocalTorrent],
                 downloadable: list[TorrentInfo], cache: TorrentStore) -> SpaceChange:
        used, _ = self.merge_torrent_info(local_torrents, cache)
        deleted = sum(t.torrent.size for t in removable) / 1000 ** 3
        downloaded = sum(t.file_size for t in downloadable)
        return SpaceChange(
            before=used,
            to_be_deleted=deleted,
            to_be_downloaded=downloaded,
            after=used - deleted + downloaded,
        )

    @classmethod
    def merge_torrent_info(cls, local_torrents: list[LocalTorrent],
                           cache: TorrentStore) -> tuple[float, dict[str, set[str]]]:
        total = 0.
        path_torrents = {}
        cached = cache.save_extra_torrents(local_torrents)
        for torrent, info in zip(local_torrents, cached):
            if info.path_hash in path_torrents:
                path_torrents[info.path_hash].append(torrent)
            else:
                path_torrents[info.path_hash] = [torrent]
                total += torrent.torrent.size
        duplicates = {}
        for _, same_torrents in path_torrents.items():
            hashes = set(t.torrent.hash for t in same_torrents)
            for torrent in same_torrents:
                duplicates[torrent.torrent.hash] = hashes - {torrent.torrent.hash}
        return total / 1000 ** 3, duplicates
