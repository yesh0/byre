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

import os
import shutil
import tempfile
import unittest

from byre import CATEGORIES, ByrApi, TorrentPromotion, NexusSortableField
from byre.bt import BtClient
# noinspection PyUnresolvedReferences
import context
import test_client


class BtClientTestCase(unittest.TestCase):
    def test_qbittorrent_connection(self):
        path = tempfile.mkdtemp()
        client = BtClient(os.environ.get("QB_URL", ""), path)
        client.remove_categories(CATEGORIES.values())
        client.init_categories(CATEGORIES.values())
        for category in CATEGORIES.values():
            self.assertTrue(os.path.exists(os.path.join(path, category)))
            self.assertTrue(os.path.exists(os.path.join(path, "Torrents", category)))
        client.remove_categories(CATEGORIES.values())
        shutil.rmtree(path)

    def test_tag_init(self):
        path = tempfile.mkdtemp()
        client = BtClient(os.environ.get("QB_URL", ""), path)
        client.init_tags()
        self.assertIn("byr", client.client.torrents_tags())
        client.init_tags(reset=True)
        self.assertNotIn("byr", client.client.torrents_tags())
        shutil.rmtree(path)

    def test_add_torrent(self):
        path = tempfile.mkdtemp()
        client = BtClient(os.environ.get("QB_URL", ""), path)
        client.init_tags()
        client.init_categories(["Others"])
        byr = ByrApi(test_client.login(path))
        torrent = byr.list_torrents(page=0, promotion=TorrentPromotion.NONE,
                                    sorted_by=NexusSortableField.LIVE_TIME, desc=False)[0]

        torrent.category = "Others"
        client.add_torrent(byr.download_torrent(torrent.seed_id), torrent, paused=True)
        local = [t for t in client.list_torrents([]) if torrent.title in t.torrent.name]
        self.assertEqual(1, len(local))
        client.remove_torrent(local[0])
        local = [t for t in client.list_torrents([]) if torrent.title in t.torrent.name]
        self.assertEqual(0, len(local))

        client.init_tags(reset=True)
        client.remove_categories(["Others"])
        shutil.rmtree(path)


if __name__ == '__main__':
    unittest.main()
