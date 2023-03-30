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

import logging
import math
import re
import time
import typing

import click
from overrides import override

from byre import scoring, planning
from byre.clients.api import NexusSortableField
from byre.clients.data import UserTorrentKind, TorrentInfo, LocalTorrent, TorrentPromotion, PROMOTION_FREE
from byre.commands import pretty
from byre.commands.bt import BtCommand
from byre.commands.config import GlobalConfig, ConfigurableGroup
from byre.commands.nexus import ByrCommand

_logger = logging.getLogger("byre.commands.main")
_debug, _info = _logger.debug, _logger.info


class MainCommand(ConfigurableGroup):
    def __init__(self, bt: BtCommand, byr: ByrCommand):
        super().__init__(
            name="do",
            help="综合 PT 站点与本地的命令，主要功能所在。",
            no_args_is_help=True,
        )
        self.bt = bt
        self.byr = byr
        self.config: typing.Optional[GlobalConfig] = None
        self.planner: typing.Optional[planning.Planner] = None
        self.scorer: typing.Optional[scoring.Scorer] = None

    @override
    def configure(self, config: GlobalConfig):
        self.scorer = scoring.Scorer(
            free_weight=config.optional(float, 1., "scoring", "free_weight"),
            cost_recovery_days=config.optional(float, 7., "scoring", "cost_recovery_days"),
            removal_exemption_days=config.optional(float, 15., "scoring", "removal_exemption_days"),
        )
        max_total_size = config.require(float, "planning", "max_total_size")
        self.planner = planning.Planner(
            max_total_size=max_total_size,
            max_download_size=config.optional(float, max_total_size / 50, "planning", "max_download_size"),
        )
        self.config = config
        self.bt.configure(config)
        self.byr.configure(config)

    @click.command
    @click.option("-d", "--dry-run", is_flag=True, help="计算种子选择结果，但不添加种子到本地")
    @click.option("-p", "--print", "print_scores", is_flag=True, help="显示新种子评分以及最终选择结果")
    @click.option("-f", "--free-only", is_flag=True, help="只会下载免费促销的种子")
    def main(self, dry_run: bool, print_scores: bool, free_only: bool):
        """自动选择北邮人种子并在本地开始下载。"""
        self.download(None, dry_run, print_scores, free_only)

    @click.command
    @click.option("-d", "--dry-run", is_flag=True, help="获取重命名列表，但不重命名")
    def fix(self, dry_run: bool):
        """
        尝试修复 qBittorrent 中的任务名（也即给名称加上 ``[byr-北邮人ID]`` 的前缀）。

        暂时只支持北邮人。
        """
        pending = [t for t in self.bt.api.list_torrents([], wants_all=True, site="byr") if t.seed_id == 0]
        if len(pending) == 0:
            _info("所有种子均已经正确命名")
            return
        for kind in [UserTorrentKind.SEEDING, UserTorrentKind.COMPLETED, UserTorrentKind.LEECHING,
                     UserTorrentKind.INCOMPLETE]:
            self._match_against_remote(pending, self.byr.api.list_user_torrents(kind))
            if all(t.seed_id != 0 for t in pending):
                break
            time.sleep(0.5)
        rename_actions = pretty.pretty_rename(pending)
        _info(f"重命名结果：\n%s", rename_actions)
        if dry_run:
            _info("以上计划未被实际运行；若想实际重命名，请去除命令行 -d / --dry-run 选项")
        else:
            for torrent in pending:
                if torrent.seed_id != 0:
                    _debug("正在重命名 %s", torrent.info.title)
                    self.bt.api.rename_torrent(torrent, torrent.info)

    @click.command(name="download")
    @click.argument("seed", type=click.STRING, metavar="<北邮人链接或是种子 ID>")
    @click.option("-d", "--dry-run", is_flag=True, help="计算种子调整结果，但不添加种子到本地")
    @click.option("-p", "--paused", is_flag=True, help="使种子在添加后被暂停")
    @click.option("-e", "--exists", is_flag=True, help="告诉 qBittorrent 文件已经下载完毕并让其跳过哈希检查")
    def download_one(self, seed: str, dry_run: bool, paused: bool, exists: bool):
        """下载特定种子，可能会删除其它种子腾出空间来满足下载需求。"""
        seed_id = pretty.parse_url_id(seed)
        self.download(self.byr.torrent(seed_id), dry_run, paused=paused, exists=exists)

    def download(self, target: typing.Optional[TorrentInfo] = None, dry_run=False, print_scores=False, free_only=False,
                 paused=False, exists=False):
        local, scored_local, local_dict = self._gather_local_info()
        if target is None:
            candidates = self._fetch_candidates(scored_local, local_dict, free_only=free_only)
        else:
            _info("准备下载指定种子，将种子的价值设为无穷，去除单次下载量上限")
            candidates = [(target, math.inf)]
            self.planner.max_download_size = self.planner.max_total_size
        if print_scores:
            pretty.pretty_scored_torrents(candidates[:10])

        _info("正在计算最终种子选择")
        removable, downloadable = self.planner.plan(local, scored_local, candidates)
        estimates = self.planner.estimate(local, removable, downloadable)
        summary = "\n".join((
            "更改总结：",
            f"最大允许空间占用 {self.planner.max_total_size:.2f} GB，"
            f"本次最大下载量为 {self.planner.max_download_size:.2f} GB",
            f"目前总空间占用 {estimates.before:.2f} GB，"
            f"最后预期总占用 {estimates.after:.2f} GB",
            f"将会删除 {len(removable)} 项内容（共计 {estimates.to_be_deleted:.2f} GB），"
            f"将会下载 {len(downloadable)} 项内容（共计 {estimates.to_be_downloaded:.2f} GB）",
            pretty.pretty_changes(removable, downloadable)
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
                self.bt.api.remove_torrent(t)
                time.sleep(0.5)
            for t in downloadable:
                _info("正在添加下载：[byr-%d]%s", t.seed_id, t.title)
                torrent = self.byr.api.download_torrent(t.seed_id)
                self.bt.api.add_torrent(torrent, t, paused=paused, exists=exists)
                time.sleep(0.5)

    @staticmethod
    def _merge_torrent_list(*lists: list[TorrentInfo]):
        result = {}
        for torrents in lists:
            for torrent in torrents:
                if torrent.seed_id not in result:
                    result[torrent.seed_id] = torrent
        return list(result.values())

    def _match_against_remote(self, pending: list[LocalTorrent], remote: list[TorrentInfo]):
        for local in pending:
            if local.seed_id != 0:
                continue
            for torrent in remote:
                if not self._match_words(torrent.title, local.torrent.name):
                    continue
                info = self.byr.api.torrent(torrent.seed_id)
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

    def _gather_local_info(self):
        _info("正在合并远端种子列表和本地种子列表信息")
        remote = self.byr.api.list_user_torrents()
        local = self.bt.api.list_torrents(remote)
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
        lists.append(self.byr.api.list_torrents(0))
        time.sleep(0.5)
        lists.append(self.byr.api.list_torrents(0, sorted_by=NexusSortableField.LEECHER_COUNT))
        time.sleep(0.5)
        lists.append(self.byr.api.list_torrents(0, promotion=TorrentPromotion.FREE))
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
