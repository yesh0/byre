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

# noinspection PyUnresolvedReferences
import context
from byre.clients.tju import TjuPtClient, TjuPtApi


def login(path):
    return TjuPtClient(os.environ.get("T_USERNAME", ""), os.environ.get("T_PASSWORD", ""),
                       cookie_file=os.path.join(path, "dir", "byr.cookies"))


class TjuPtClientTestCase(unittest.TestCase):
    def test_user_info(self):
        path = tempfile.mkdtemp()
        client = login(path)
        self.assertFalse(client.is_logged_in())
        client.login()
        self.assertTrue(client.is_logged_in())
        shutil.rmtree(path)

    def test_client(self):
        path = tempfile.mkdtemp()
        client = login(path)
        api = TjuPtApi(client)
        self.assertEqual(int(os.environ.get("T_USER_ID", "0")), api.current_user_id())
        user = api.user_info()
        self.assertEqual(client.username, user.username)
        self.assertNotEqual(0, user.ranking)
        self.assertNotEqual(0., user.mana)
        self.assertNotEqual("", user.level)
        self.assertNotEqual(0., user.uploaded)
        shutil.rmtree(path)

    def test_torrent_info(self):
        path = tempfile.mkdtemp()
        client = login(path)
        api = TjuPtApi(client)
        torrent = api.torrent(128676)
        self.assertTrue("2005.720p.BluRay.x264" in torrent.title)
        self.assertEqual("北洋园", torrent.second_category)
        self.assertEqual("Movies", torrent.category)
        self.assertEqual(128676, torrent.seed_id)
        self.assertAlmostEqual(4., torrent.file_size, delta=1)
        self.assertGreater(torrent.finished, 200)
        shutil.rmtree(path)

    def test_torrent_listing(self):
        path = tempfile.mkdtemp()
        client = login(path)
        api = TjuPtApi(client)
        torrents = api.list_torrents()
        self.assertNotEqual(0, len(torrents))
        self.assertTrue(any(0 < t.live_time < 3 for t in torrents))
        shutil.rmtree(path)


if __name__ == '__main__':
    unittest.main()
