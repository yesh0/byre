# Modified from decaptcha @ https://github.com/bumzy/decaptcha
#
# Copyright (C) 2018 bumzy
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

import importlib.resources
import typing
from pickle import loads

import sklearn
from PIL import Image
from sklearn import svm

from byre.utils import cast


class DeCaptcha:
    def __init__(self, length: int = 6) -> None:
        self.__clf = svm.NuSVC()
        self.__length = length
        self.__is_active = False
        self.__BIN_TABLE = [0] * 140 + [1] * 116

    def __points_collect(
        self,
        bin_image: Image.Image,
        visited: list[list[int]],
        x: int,
        y: int,
        points: list[tuple[int, int]],
    ) -> None:
        for step_x in range(-1, 2):
            for step_y in range(-1, 2):
                i = x + step_x
                j = y + step_y
                if 0 <= i < bin_image.width and 0 <= j < bin_image.height:
                    if visited[i][j] == 0 and bin_image.getpixel((i, j)) == 0:
                        visited[i][j] = 1
                        points.append((i, j))
                        self.__points_collect(bin_image, visited, i, j, points)

    def __remove_noise_point(self, bin_image: Image.Image) -> None:
        width = bin_image.width
        height = bin_image.height
        visited = [[0 for _ in range(height)] for _ in range(width)]
        for i in range(width):
            bin_image.putpixel((i, 0), 1)
            bin_image.putpixel((i, height - 1), 1)
        for j in range(height):
            bin_image.putpixel((0, j), 1)
            bin_image.putpixel((width - 1, j), 1)
        for i in range(width):
            for j in range(height):
                if visited[i][j] == 0 and bin_image.getpixel((i, j)) == 0:
                    points: list[tuple[int, int]] = []
                    self.__points_collect(bin_image, visited, i, j, points)
                    if 1 <= len(points) <= 3:
                        for point in points:
                            bin_image.putpixel(point, 1)

    def __get_char_images(self, image: Image.Image) -> list[Image.Image]:
        char_images = []
        for i in range(self.__length):
            x = 25 + i * (8 + 10)
            y = 15
            child_img = image.crop((x, y, x + 8, y + 10))
            char_images.append(child_img)
        return char_images

    def __preprocess(self, image: Image.Image) -> Image.Image:
        gray_image = image.convert("L")
        bin_image = gray_image.point(self.__BIN_TABLE, "1")
        self.__remove_noise_point(bin_image)
        return bin_image

    @staticmethod
    def __get_feature(image: Image.Image) -> list[int]:
        width, height = image.size
        pixel_cnt_list = []
        for y in range(height):
            pix_cnt_x = 0
            for x in range(width):
                if image.getpixel((x, y)) == 0:
                    pix_cnt_x += 1
            pixel_cnt_list.append(pix_cnt_x)
        for x in range(width):
            pix_cnt_y = 0
            for y in range(height):
                if image.getpixel((x, y)) == 0:
                    pix_cnt_y += 1
            pixel_cnt_list.append(pix_cnt_y)
        return pixel_cnt_list

    def decode(self, image: Image.Image) -> str:
        if not isinstance(image, Image.Image):
            raise TypeError("image must be instance of Image.Image in PIL!")
        if not self.__is_active:
            raise RuntimeError("train or load_model first!")
        image = self.__preprocess(image)
        char_images = self.__get_char_images(image)
        features = []
        for i in range(self.__length):
            features.append(self.__get_feature(char_images[i]))
        result = self.__clf.predict(typing.cast(typing.Any, features))
        text = "".join(result)
        return text

    def load_model(self) -> None:
        self.__clf = loads(_model_bytes())
        if not isinstance(self.__clf, svm.NuSVC):
            raise TypeError("model file messed up!")
        self.__is_active = True


def _model_bytes() -> bytes:
    version = "1.2.2"
    if version != sklearn.__version__:
        import logging

        logging.getLogger("byre.decaptcha").warning(
            "当前 sklearn 版本与验证码模型训练版本有差别"
        )
    return (
        importlib.resources.files(cast(str, __package__))
        .joinpath(f"captcha_classifier.{version}.pkl")
        .read_bytes()
    )
