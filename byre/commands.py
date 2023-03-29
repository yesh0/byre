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
import importlib.resources
import logging
import math
import os.path
import pathlib
import re
import time
import typing

import click
import tabulate
import tomli

import byre.setup
from byre import ByrApi, BtClient, ByrClient, TorrentPromotion, TorrentInfo, ByrSortableField, UserTorrentKind, \
    LocalTorrent, planning, scoring, PROMOTION_FREE, CATEGORIES

_logger = logging.getLogger("byre.commands")
_debug, _info, _warning = _logger.debug, _logger.info, _logger.warning


class GlobalConfig(click.ParamType):
    """配置信息以及各种命令。"""

    name = "配置文件路径"

    config: dict[str, typing.Any] = None

    byr_credentials = ("", "", "")

    byr_proxy = ""

    qbittorrent_url = ""

    download_dir = ""

    free_weight = 0.

    cost_recovery_days = 0.

    removal_exemption_days = 0.

    max_total_size = 0.

    max_download_size = 0.

    byr: ByrApi = None
    bt: BtClient = None
    planner: planning.Planner = None
    scorer: scoring.Scorer = None

    def convert(self, value: str, param, ctx):
        if not value:
            default_path = pathlib.Path.home().joinpath(".config", "byre", "byre.toml")
            for f in ["byre.toml", str(default_path), "/etc/byre.toml",
                      "/etc/byre/byre.toml"]:
                if os.path.exists(f):
                    _info("默认选定配置文件：%s", pathlib.Path(f))
                    value = f
                    break
            else:
                _warning("找不到配置文件“byre.toml”，如果已有配置文件，请尝试使用 -c / --config 选项")
                if click.prompt("是否创建配置文件？",
                                type=click.Choice(["yes", "no"]), default="no", prompt_suffix=" ") == "yes":
                    _info("默认配置文件位置：%s", default_path)
                    with importlib.resources.files(__package__).joinpath("byre.example.toml").open() as tmpl:
                        with default_path.open("w") as config:
                            config.write(tmpl.read())
                            config.flush()
                    click.edit(filename=str(default_path))
                else:
                    raise FileNotFoundError("找不到配置文件")
        with open(value, "rb") as file:
            self.config = tomli.load(file)

        self.byr_credentials = (
            self._require(str, "byr", "username"),
            self._require(str, "byr", "password", password=True),
            self._optional(str, "byr.cookies", "byr", "cookie_cache")
        )
        self.byr_proxy = self._optional(str, "", "byr", "http_proxy")
        self.qbittorrent_url, self.download_dir = (
            self._require(str, "qbittorrent", "url", password=True),
            self._require(str, "qbittorrent", "download_dir"),
        )
        self.free_weight = self._optional(float, 1., "scoring", "free_weight")
        self.cost_recovery_days = self._optional(float, 7., "scoring", "cost_recovery_days")
        self.removal_exemption_days = self._optional(float, 15., "scoring", "removal_exemption_days")
        self.max_total_size = self._require(float, "planning", "max_total_size")
        self.max_download_size = self._optional(float, self.max_total_size / 50, "planning", "max_download_size")
        return self

    def init(self, bt=False, byr=False, planner=False, scorer=False):
        """初始化北邮人客户端等。"""
        if byr and self.byr is None:
            self.byr = ByrApi(ByrClient(
                *self.byr_credentials,
                proxies={
                    "http": self.byr_proxy,
                    "https": self.byr_proxy,
                } if self.byr_proxy else None,
            ))
            time.sleep(0.5)
        if bt and self.bt is None:
            self.bt = BtClient(self.qbittorrent_url, self.download_dir)
            self.bt.init_tags()
            self.bt.init_categories(CATEGORIES.values())
        if scorer and self.scorer is None:
            self.scorer = scoring.Scorer(
                self.free_weight,
                self.cost_recovery_days,
                self.removal_exemption_days,
            )
        if planner and self.planner is None:
            self.planner = planning.Planner(max_total_size=self.max_total_size,
                                            max_download_size=self.max_download_size)

    def setup(self):
        byre.setup.setup(self.qbittorrent_url)

    def display_torrent_info(self, seed: str):
        seed_id = self._parse_seed_id(seed)
        self.init(byr=True)
        torrent = self.byr.torrent(seed_id)
        click.echo(tabulate.tabulate([
            ("标题", click.style(torrent.title, bold=True)),
            ("副标题", click.style(torrent.sub_title, dim=True)),
            ("链接", click.style(f"https://byr.pt/details.php?id={torrent.seed_id}", underline=True)),
            ("类型", click.style(f"{torrent.cat} - {torrent.second_category}", fg="bright_red")),
            ("促销", click.style(str(torrent.promotions), fg="bright_yellow")),
            ("大小", click.style(f"{torrent.file_size:.2f} GB", fg="cyan")),
            ("存活时间", click.style(f"{torrent.live_time:.2f} 天", fg="bright_green")),
            ("做种人数", f"{torrent.seeders}"),
            ("下载人数", click.style(f"{torrent.leechers}", fg="bright_magenta")),
            ("上传用户", f"{torrent.uploader.username} " +
             (click.style(f"<https://byr.pt/userdetails.php?id={torrent.uploader.user_id}>", underline=True)
              if torrent.uploader.user_id != 0 else "")
             ),
        ], maxcolwidths=[2, 10, 70], showindex=True, disable_numparse=True))

    def display_user_info(self, user_id=0):
        self.init(byr=True)
        user = self.byr.user_info(user_id)
        if user.user_id != self.byr.current_user_id():
            _warning("查询的用户并非当前登录用户，限于权限，信息可能不准确")
        click.echo(tabulate.tabulate([
            ("用户名", click.style(user.username, bold=True)),
            ("链接", click.style(f"https://byr.pt/details.php?id={user.user_id}", underline=True)),
            ("等级", click.style(user.level, fg="bright_yellow")),
            ("魔力值", click.style(f"{user.mana}", fg="bright_magenta")),
            ("可连接", click.style("是", fg="bright_green") if user.connectable else click.style("否", dim=True)),
            ("下载量", click.style(f"{user.downloaded:.2f} GB", fg="yellow")),
            ("上传量", click.style(f"{user.uploaded:.2f} GB", fg="bright_blue")),
            ("分享率", click.style(f"{user.ratio:.2f}", fg="cyan")),
            ("当前活动", f"{user.seeding}↑ {user.downloading}↓"),
            ("上传排行", click.style(f"{user.ranking}", dim=True)),
        ], showindex=True, disable_numparse=True))

    def list_torrents(self, page=0, promotions=TorrentPromotion.ANY, sorted_by=ByrSortableField.ID):
        self.init(byr=True)
        torrents = self.byr.list_torrents(page, promotion=promotions, sorted_by=sorted_by)
        self._display_torrents(torrents)

    def list_user_torrents(self, kind: UserTorrentKind):
        self.init(byr=True)
        torrents = self.byr.list_user_torrents(kind)
        if len(torrents) == 0:
            _warning("种子列表为空")
            return
        if kind != UserTorrentKind.SEEDING:
            _warning("用户做种列表的信息最完善，其它列表会有信息缺失")
        self._display_torrents(torrents)

    def list_bt_torrents(self, wants_all=False, speed=False):
        self.init(bt=True, byr=True)
        remote = self.byr.list_user_torrents()
        torrents = self.bt.list_torrents(remote, wants_all=wants_all)
        if speed:
            torrents = [t for t in torrents if t.torrent.dlspeed + t.torrent.upspeed > 0]
            torrents.sort(key=lambda t: t.torrent.dlspeed + t.torrent.upspeed, reverse=True)
        else:
            torrents.sort(key=lambda t: t.torrent.last_activity, reverse=True)
        if len(torrents) == 0:
            _warning("本地无相关种子")
            return
        self._display_local_torrents(torrents, speed)

    def download_one(self, seed: str, dry_run: bool):
        seed_id = self._parse_seed_id(seed)
        self.init(byr=True)
        self.download(self.byr.torrent(seed_id), dry_run)

    def fix(self, dry_run: bool):
        self.init(bt=True, byr=True)
        pending = [t for t in self.bt.list_torrents([], wants_all=True) if t.seed_id == 0]
        if len(pending) == 0:
            _info("所有种子均已经正确命名")
            return
        for kind in [UserTorrentKind.SEEDING, UserTorrentKind.COMPLETED, UserTorrentKind.LEECHING,
                     UserTorrentKind.INCOMPLETE]:
            self._match_against_remote(pending, self.byr.list_user_torrents(kind))
            if all(t.seed_id != 0 for t in pending):
                break
            time.sleep(0.5)

        failed = []
        found = []
        arrow = click.style("=>", dim=True)
        for t in pending:
            if t.seed_id == 0:
                failed.append((
                    click.style("!!", fg="bright_red"),
                    click.style(t.torrent.name, fg="bright_red"),
                    f"{t.torrent.size / 1000 ** 3:.2f} gb",
                    t.torrent.hash[:7],
                ))
                failed.append((
                    arrow,
                    click.style("未能找到匹配", fg="yellow"),
                    "", "",
                ))
            else:
                found.append((
                    click.style("✓", fg="bright_green"),
                    click.style(t.torrent.name, fg="cyan"),
                    f"{t.torrent.size / 1000 ** 3:.2f} GB",
                    t.torrent.hash[:7]
                ))
                found.append((
                    arrow,
                    click.style(t.info.title, fg="bright_green"),
                    f"{t.info.file_size:.2f} GB",
                    t.info.hash[:7],
                ))
        _info(
            "重命名结果：\n" +
            tabulate.tabulate((*failed, *found), maxcolwidths=[2, 60, 10, 10], disable_numparse=True)
        )
        if dry_run:
            _info("以上计划未被实际运行；若想实际重命名，请去除命令行 -d / --dry-run 选项")
        else:
            for torrent in pending:
                if torrent.seed_id != 0:
                    _debug("正在重命名 %s", torrent.info.title)
                    self.bt.rename_torrent(torrent, torrent.info)

    def download(self, target: typing.Optional[TorrentInfo] = None, dry_run=False, print_scores=False, free_only=False):
        self.init(bt=True, byr=True, planner=True, scorer=True)
        local, scored_local, local_dict = self._gather_local_info()
        if target is None:
            candidates = self._fetch_candidates(scored_local, local_dict, free_only=free_only)
        else:
            _info("准备下载指定种子，将种子的价值设为无穷，去除单次下载量上限")
            candidates = [(target, math.inf)]
            self.planner.max_download_size = self.planner.max_total_size
        if print_scores:
            self._display_scored_torrents(candidates[:10])

        _info("正在计算最终种子选择")
        removable, downloadable = self.planner.plan(local, scored_local, candidates)
        estimates = self.planner.estimate(local, removable, downloadable)
        summary = "\n".join((
            "更改总结：",
            f"最大允许空间占用 {self.max_total_size:.2f} GB，本次最大下载量为 {self.max_download_size:.2f} GB",
            f"目前总空间占用 {estimates.before:.2f} GB，"
            f"最后预期总占用 {estimates.after:.2f} GB",
            f"将会删除 {len(removable)} 项内容（共计 {estimates.to_be_deleted:.2f} GB），"
            f"将会下载 {len(downloadable)} 项内容（共计 {estimates.to_be_downloaded:.2f} GB）",
            tabulate.tabulate((
                *((
                    click.style("删", fg="bright_red"),
                    click.style(f"{t.seed_id}", dim=True),
                    click.style(t.torrent.name, dim=True),
                    click.style(f"-{t.torrent.size / 1000 ** 3:.2f} GB", fg="light_green"),
                    "",
                ) for t in removable),
                *((
                    click.style("新", fg="bright_cyan"),
                    click.style(f"{t.seed_id}", dim=True),
                    click.style(t.title, bold=True),
                    click.style(f"+{t.file_size:.2f} GB", fg="yellow"),
                    click.style(str(t.promotions), fg="yellow"),
                ) for t in downloadable),
            ), maxcolwidths=[2, 8, 60, 10, 10], disable_numparse=True)
        ))
        if print_scores:
            click.echo_via_pager(summary)
        else:
            _info(summary)
        if dry_run:
            _info("以上计划未被实际运行；若想开始下载，请去除命令行 -d / --dry-run 选项")
        else:
            for t in removable:
                _info("正在删除：%s", t.torrent.name)
                self.bt.remove_torrent(t)
                time.sleep(0.5)
            for t in downloadable:
                _info("正在添加下载：[byr-%d]%s", t.seed_id, t.title)
                torrent = self.byr.download_torrent(t.seed_id)
                self.bt.add_torrent(torrent, t)
                time.sleep(0.5)

    def _require(self, typer: typing.Callable, *args, password=False):
        config = self.config
        for arg in args:
            if arg not in config:
                if password:
                    config = click.prompt(f"请输入 {'.'.join(args)} 配置：", hide_input=True)
                    break
                raise ValueError(f"缺失 {'.'.join(args)} 配置参数")
            config = config[arg]
        try:
            return typer(config)
        except ValueError as e:
            raise ValueError(f"配置项 {'.'.join(args)} 的值 {config} 无效：{e}")

    def _optional(self, typer: typing.Callable, default: typing.Any, *args):
        try:
            return self._require(typer, *args)
        except ValueError:
            return default

    @staticmethod
    def _display_torrents(torrents: list[TorrentInfo]):
        table = []
        header = ["ID", "标题", ""]
        limits = [8, 60, 10]
        for t in torrents:
            table.append((
                t.seed_id,
                click.style(t.title, bold=True),
                click.style(f"{t.file_size:.2f} GB", fg="bright_yellow"),
            ))
            table.append((
                "",
                click.style(t.sub_title, dim=True)
                + " (" + click.style(f"{t.seeders}↑", fg="bright_green")
                + " " + click.style(f"{t.leechers}↓", fg="cyan") + " )",
                click.style(f"{t.live_time:.2f} 天", fg="bright_magenta"),
            ))
        click.echo_via_pager(tabulate.tabulate(table, headers=header, maxcolwidths=limits, disable_numparse=True))

    @staticmethod
    def _display_local_torrents(torrents: list[LocalTorrent], speed=False):
        table = []
        header = ["最后活跃", "标题", "速度" if speed else "累计", "分享率"]
        limits = [8, 60, 10, 10]
        for t in torrents:
            days = (time.time() - t.torrent.last_activity) / (24 * 60 * 60)
            table.append((
                click.style(f"{days:.2f} 天", fg="yellow"),
                click.style(t.torrent.name, bold=True),
                click.style(f"{t.torrent.upspeed / 1000 ** 2:.2f} MB/s↑" if speed
                            else f"{t.torrent.uploaded / 1000 ** 3:.2f} GB↑", fg="bright_green"),
                click.style(f"{t.torrent.ratio:.2f}", fg="bright_yellow"),
            ))
            table.append((
                "",
                click.style(t.torrent.hash, dim=True)
                + " (" + click.style(f"{t.torrent.num_complete}↑", fg="bright_green")
                + " " + click.style(f"{t.torrent.num_incomplete}↓", fg="cyan") + " )",
                click.style(f"{t.torrent.dlspeed / 1000 ** 3:.2f} MB/s↓" if speed
                            else f"{t.torrent.downloaded / 1000 ** 3:.2f} GB↓", fg="cyan"),
                click.style(f"/ {t.torrent.size / 1000 ** 3:.2f} GB", dim=True)
            ))
        click.echo_via_pager(tabulate.tabulate(table, headers=header, maxcolwidths=limits, disable_numparse=True))

    @staticmethod
    def _merge_torrent_list(*lists: list[TorrentInfo]):
        result = {}
        for torrents in lists:
            for torrent in torrents:
                if torrent.seed_id not in result:
                    result[torrent.seed_id] = torrent
        return list(result.values())

    @staticmethod
    def _display_scored_torrents(torrents: list[tuple[TorrentInfo, float]]):
        table = []
        header = ["评分", "标题", ""]
        limits = [8, 60, 10]
        for t, score in torrents:
            table.append((
                click.style(f"{score:.2f}", fg="bright_yellow"),
                click.style(t.title, bold=True),
                click.style(f"{t.file_size:.2f} GB", fg="yellow"),
            ))
            table.append((
                "",
                click.style(t.sub_title, dim=True)
                + " (" + click.style(f"{t.seeders}↑", fg="bright_green")
                + " " + click.style(f"{t.leechers}↓", fg="cyan")
                + " " + click.style(f"{t.finished}✓", fg="yellow") + " )",
                click.style(f"{t.live_time:.2f} 天", fg="bright_magenta"),
            ))
        click.echo_via_pager(tabulate.tabulate(table, headers=header, maxcolwidths=limits, disable_numparse=True))

    def _match_against_remote(self, pending: list[LocalTorrent], remote: list[TorrentInfo]):
        for local in pending:
            if local.seed_id != 0:
                continue
            for torrent in remote:
                if not self._match_words(torrent.title, local.torrent.name):
                    continue
                info = self.byr.torrent(torrent.seed_id)
                torrent_hash = info.hash
                time.sleep(0.5)
                if local.torrent.hash == torrent_hash:
                    local.seed_id = torrent.seed_id
                    local.info = info
                    break

    @staticmethod
    def _match_words(a: str, b: str):
        separator = re.compile("[\\d -@\\[-`{-~]")
        matches = (set(s.lower() for s in separator.split(a) if len(s) > 3)
                   & set(s.lower() for s in separator.split(b) if len(s) > 3))
        if len(matches) != 0:
            _debug("尝试匹配 %s 与 %s：%s", a, b, matches)
        return len(matches) != 0

    @staticmethod
    def _parse_seed_id(s: str):
        if s.isdigit():
            return int(s)
        else:
            return ByrApi.extract_url_id(s)

    def _gather_local_info(self):
        _info("正在合并远端种子列表和本地种子列表信息")
        remote = self.byr.list_user_torrents()
        local = self.bt.list_torrents(remote)
        local_dict = dict((t.seed_id, -1) for t in local)

        _info("正在对本地种子评分")
        scored_local = list(filter(lambda t: t[1] >= 0, ((t, self.scorer.score_uploading(t)) for t in local)))
        scored_local.sort(key=lambda t: t[1])
        local_dict.update((t[0].seed_id, i) for i, t in enumerate(scored_local))

        return local, scored_local, local_dict

    def _fetch_candidates(self, scored_local: list[tuple[LocalTorrent, float]], local_dict: dict[int, int],
                          free_only: bool):
        _info("正在抓取新种子")
        lists = []
        time.sleep(0.5)
        lists.append(self.byr.list_torrents(0))
        time.sleep(0.5)
        lists.append(self.byr.list_torrents(0, sorted_by=ByrSortableField.LEECHER_COUNT))
        time.sleep(0.5)
        lists.append(self.byr.list_torrents(0, promotion=TorrentPromotion.FREE))
        time.sleep(0.5)
        fetched = []
        _debug("正在将已下载的种子从新种子列表中除去")
        for torrent in self._merge_torrent_list(*lists):
            if torrent.seed_id in local_dict:
                i = local_dict[torrent.seed_id]
                if i != -1:
                    scored_local[i][0].info = torrent
            else:
                fetched.append(torrent)

        if free_only:
            _debug("正在筛选免费促销的种子")
            fetched = [t for t in fetched if PROMOTION_FREE in t.promotions]

        _info("正在对新种子评分")
        candidates = [(t, self.scorer.score_downloading(t)) for t in fetched]
        candidates.sort(key=lambda t: t[1], reverse=True)
        return candidates
