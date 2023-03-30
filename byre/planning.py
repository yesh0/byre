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
             ) -> tuple[list[LocalTorrent], list[TorrentInfo]]:
        remaining = self.max_total_size - self._compute_used_space(local_torrents)
        i = 0
        removable, downloadable = [], []
        downloaded = 0.
        for candidate, score in remote:
            if downloaded + candidate.file_size > self.max_download_size:
                continue
            if candidate.file_size < remaining:
                remaining -= candidate.file_size
                downloadable.append(candidate)
                downloaded += candidate.file_size
                continue
            removable_size = 0
            j = i
            for j, (torrent, torrent_score) in enumerate(local[i:]):
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
        return removable, downloadable

    def estimate(self, local_torrents: list[LocalTorrent], removable: list[LocalTorrent],
                 downloadable: list[TorrentInfo]) -> SpaceChange:
        used = self._compute_used_space(local_torrents)
        deleted = sum(t.torrent.size for t in removable) / 1000 ** 3
        downloaded = sum(t.file_size for t in downloadable)
        return SpaceChange(
            before=used,
            to_be_deleted=deleted,
            to_be_downloaded=downloaded,
            after=used - deleted + downloaded,
        )

    @staticmethod
    def _compute_used_space(local_torrents: list[LocalTorrent]) -> float:
        return sum(t.torrent.size for t in local_torrents) / 1000 ** 3
