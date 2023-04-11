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
import os.path
import shutil
import tempfile
import unittest

import requests

from byre import storage


class StorageTestCase(unittest.TestCase):
    def test_migration(self):
        path = tempfile.mkdtemp()
        store = storage.TorrentStore(os.path.join(path, "test.db"))
        store.migrate()
        self.assertTrue(os.path.exists(os.path.join(path, "test.db")))
        self.assertEqual(0, len(store.list_torrents()))
        store.close()
        shutil.rmtree(path)

    def test_path_hash(self):
        path = tempfile.mkdtemp()
        store = storage.TorrentStore(os.path.join(path, "test.db"))
        self.assertEqual(store.hash_paths({"a": 1, "b": 2}), store.hash_paths({"b": 2, "a": 1}))
        self.assertNotEqual(store.hash_paths({"a": 1, "b": 2}), store.hash_paths({"b": 1, "a": 2}))
        self.assertEqual(
            store.hash_paths({"a/a": 1, "a/b": 2}),
            store.hash_paths({"a\\b": 2, "a\\a": 1})
        )
        store.close()
        shutil.rmtree(path)

    def test_duplicate_torrents(self):
        path = tempfile.mkdtemp()
        store = storage.TorrentStore(os.path.join(path, "test.db"))
        torrent = storage.TorrentDO("hash", "name", "path_hash", "site_A", 1234)
        self.assertTrue(store.save_torrent(torrent))
        self.assertFalse(store.save_torrent(torrent))
        self.assertEqual(torrent, store.list_torrents()[0])
        self.assertTrue(store.save_torrent(
            storage.TorrentDO("a", "b", "c", "d", 1234)
        ))
        self.assertEqual(len(store.list_torrents()), 2)
        store.close()
        shutil.rmtree(path)

    def test_info_hash(self):
        info_hash, files = storage.TorrentStore.decode_torrent_file(
            requests.get("https://archlinux.org/releng/releases/2023.04.01/torrent/").content
        )
        self.assertEqual(info_hash, "6df99344a488592ba3f71ffaef964a1dbfe0c8ed")
        self.assertEqual(len(files), 1)
        self.assertEqual(files, {"archlinux-2023.04.01-x86_64.iso": 848637952})


if __name__ == '__main__':
    unittest.main()
