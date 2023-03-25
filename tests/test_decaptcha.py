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
import unittest

from PIL import Image

from byre.decaptcha import DeCaptcha, model_file


class DecaptchaTestCase(unittest.TestCase):
    def test_decaptcha(self):
        print(os.getcwd())
        dc = DeCaptcha()
        dc.load_model(model_file())
        captcha_list = []
        folder = os.path.join(os.path.dirname(os.path.realpath(__file__)), "decap", "captcha")
        with open(os.path.join(folder, "captcha_text")) as f:
            for i in range(100):
                answer = f.readline().strip()
                file = os.path.join(folder, f"{i}.png")
                captcha_list.append((file, answer))

        for file, answer in captcha_list:
            image = Image.open(file)
            self.assertEqual(answer, dc.decode(image))


if __name__ == '__main__':
    unittest.main()
