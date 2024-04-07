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

"""使用 SQLite 来储存种子的额外信息。"""

import hashlib
import logging
import sqlite3
import typing
from dataclasses import dataclass

import bencoder

from byre.clients.data import LocalTorrent, TorrentInfo
from byre.utils import cast

_logger = logging.getLogger("byre.storage")
_warning = _logger.warning


@dataclass
class TorrentDO:
    hash: str
    """哈希（v1）值（字母小写）。"""

    name: str
    """种子标题。"""

    path_hash: str
    """种子的目录、文件结构的哈希值，用于碰运气判断种子是否一致（字母小写）。"""

    site: str
    """种子来源网站。"""

    seed_id: int
    """种子来源网站上的种子 ID。"""


@dataclass
class PathDO:
    path_hash: str
    """种子的目录、文件结构的哈希值。"""

    root: str
    """种子的目录名，或者是单文件种子的文件名。"""


class TorrentStore:
    """
    管理种子数据的数据库并包装起数据操作接口。

    主要是用来检查各站点的种子有没有重复的，如果有的话，可以被用来自动做种。
    另外，在计算空间占用的时候重复种子不应该重复累计。

    因为看起来 NexusPHP 系列都会把种子的 info 给改掉（加上网站链接之类的），
    所以这里不考虑 info hash 重合的问题，重合就是运气不好，程序会忽略掉。

    数据库的 ``torrent`` 表的解释见 ``TorrentDO`` 。
    """

    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.cursor = self.db.cursor()
        self.migrate()

    def migrate(self):
        """初始化数据库，大概可以重复调用。"""
        statements = [
            "CREATE TABLE IF NOT EXISTS torrent"
            " (hash TEXT PRIMARY KEY, name TEXT, path_hash TEXT, site TEXT, seed_id INTEGER)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uk_path_hash ON torrent (path_hash, site)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uk_site_seed_id ON torrent (site, seed_id)",
        ]
        for statement in statements:
            self.cursor.execute(statement)
        self.db.commit()

    def close(self):
        self.db.commit()
        self.cursor.close()
        self.db.close()

    def save_extra_torrents(self, local: list[LocalTorrent]) -> list[TorrentDO]:
        """尝试将本地还没有写入数据库的种子的信息写入数据库。"""
        torrents: list[typing.Optional[TorrentDO]] = [None] * len(local)
        for i, chunk in enumerate(local[i: i + 100] for i in range(0, len(local), 100)):
            hash_index = dict((t.torrent.hash.lower(), j) for j, t in enumerate(chunk))
            existing = self.list_torrents(
                f"WHERE hash IN ({','.join('?' * len(hash_index))})",
                tuple(hash_index.keys()),
            )
            missing = hash_index.keys() - set(t.hash for t in existing)
            for t in existing:
                torrents[i * 100 + hash_index[t.hash]] = t
            for h in missing:
                torrents[i * 100 + hash_index[h]] = self.save_local_torrent(chunk[hash_index[h]])
        assert all(t is not None for t in torrents)
        return typing.cast(list[TorrentDO], torrents)

    def save_fetched_torrents(self, remote: list[TorrentInfo],
                              torrent_fetcher: typing.Callable[[TorrentInfo], bytes]):
        missing = []
        for torrent in remote:
            self.cursor.execute("SELECT 1 FROM torrent WHERE site = ? AND seed_id = ?", (torrent.site, torrent.seed_id))
            if self.cursor.rowcount == 0:
                missing.append(torrent)
        for torrent in missing:
            content = torrent_fetcher(torrent)
            info_hash, paths = self.decode_torrent_file(content)
            path_hash = self.hash_paths(paths)
            self.save_torrent(TorrentDO(info_hash, torrent.title, path_hash, torrent.site, torrent.seed_id))

    def save_local_torrent(self, torrent: LocalTorrent) -> TorrentDO:
        path_hash = self.hash_local_path(torrent)
        info = TorrentDO(torrent.torrent.hash.lower(), torrent.torrent.name, path_hash, torrent.site, torrent.seed_id)
        self.save_torrent(info)
        self.db.commit()
        return info

    def save_torrent(self, torrent: TorrentDO) -> bool:
        """将种子信息保存到数据库，成功则返回 ``True`` 。"""
        try:
            self.cursor.execute(
                "INSERT INTO torrent VALUES (?, ?, ?, ?, ?)",
                (torrent.hash, torrent.name, torrent.path_hash, torrent.site, torrent.seed_id),
            )
            self.db.commit()
            return True
        except sqlite3.DatabaseError as e:
            _warning("数据库保存“[%s-%d]%s”出错", torrent.site, torrent.seed_id, torrent.name, exc_info=e)
            self.db.rollback()
            return False

    def list_torrents(self, clause="", parameters=()) -> list[TorrentDO]:
        """列出所有数据库中有的（也不一定下载了的）种子。"""
        torrents = []
        results = self.cursor.execute(
            "SELECT hash, name, path_hash, site, seed_id FROM torrent" + (" " + clause if clause else ""),
            parameters,
        ).fetchall()
        for h, name, path_hash, site, seed_id in results:
            torrents.append(TorrentDO(h, name, path_hash, site, seed_id))
        return torrents

    def list_similar_torrents(self, torrent: LocalTorrent) -> list[TorrentDO]:
        return self.list_torrents("WHERE path_hash = ?", (self.hash_local_path(torrent),))

    @classmethod
    def decode_torrent_file(cls, content: bytes) -> tuple[str, dict[str, int]]:
        torrent = bencoder.bdecode(content)
        info = torrent[b"info"]
        root = cast(bytes, info[b"name"]).decode()
        if b"files" not in info:
            paths = {root: info[b"length"]}
        else:
            paths = dict(("/".join((root, *(segment.decode() for segment in file[b"path"]))), file[b"length"])
                         for file in info[b"files"])
        return cls.hash_info(info), paths

    @classmethod
    def hash_info(cls, info: bencoder.OrderedDict) -> str:
        return hashlib.sha1(bencoder.bencode(info)).hexdigest().lower()

    @classmethod
    def hash_paths(cls, paths: dict[str, int]) -> str:
        def no_backslash(s: str) -> str:
            return s.replace("\\", "/")

        return hashlib.sha256(
            b"\0".join(sorted(f"{no_backslash(path)} {size}".encode("utf-8") for path, size in paths.items()))
        ).hexdigest().lower()

    @classmethod
    def hash_local_path(cls, torrent: LocalTorrent) -> str:
        local_files = dict((cast(str, file.name), cast(int, file.size)) for file in torrent.torrent.files)
        return cls.hash_paths(local_files)
