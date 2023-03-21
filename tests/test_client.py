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

import logging
import os
import shutil
import sys
import tempfile
import unittest

import byre

from . import context as _

class TestByrClient(unittest.TestCase):
  def test_login(self):
    logging.basicConfig(stream=sys.stderr)
    logging.getLogger("byre").setLevel(logging.DEBUG)

    path = tempfile.mkdtemp()
    client = byre.ByrClient(os.environ.get("USERNAME", ""), os.environ.get("PASSWORD", ""),
      cookie_file=os.path.join(path, "dir", "byr.cookies"))
    self.assertFalse(client.is_logged_in())
    client.login(cache=False)
    self.assertTrue(client.is_logged_in())

    client = byre.ByrClient(os.environ.get("USERNAME", ""), "",
      cookie_file=os.path.join(path, "dir", "byr.cookies"))
    self.assertFalse(client.is_logged_in())
    client.login(cache=True)
    self.assertTrue(client.is_logged_in())

    shutil.rmtree(path)

if __name__ == "__main__":
  unittest.main()
