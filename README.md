# byre - 一款北邮人/北洋园 PT 命令行操作软件

（示例图片用的 asciinema 的中文渲染有问题，将就着看吧。）

[![asciicast](https://asciinema.org/a/570391.svg)](https://asciinema.org/a/570391)

- **命令行访问站点**：可以在命令行查看北邮人/北洋园站点的种子列表、用户信息、种子信息等等。

- **qBittorrent 种子管理**：可以将本地的种子与北邮人/北洋园的种子关联起来，以列表展示。

- **种子自动下载**：

  - **下载特定种子**：给定一个种子 ID，自动下载 `.torrent` 文件，开始 qBittorrent 下载，
    重命名为容易识别的下载任务名称，并打上对应站点的标签（`byr` 或 `tju`）以方便管理。

    这边建议是先稍微手动下载一些热门免费种子保证有一定的上传量先，不然落到 Peasant 的话，
    很多站点都会有强制的告示之类的，程序肯定会出错。 
    （或者也可以用 `--free-only` 让自动下载只下载免费的种子，以免程序操盘失误。投资有风险！）

    用 `byre do download --help` 查看用法。

  - **共同种子识别**：

    - **手动**：对于用户指定的一个本地下载完成的种子和一个其它 PT 站点的种子，
      如果两个种子对应的文件完全相同，则可以跳过后者的下载、校验，直接开始做种。

      用 `byre do download --help` 查看用法，使用 `--same` 选项。

    - **自动**：自动抓取 PT 站点的热门种子，与本地已有的种子对比，
      如果有种子相同且来源的 PT 站不同，则自动开始做另外的 PT 站的种。
  
      因为感觉上搜索还是挺耗服务器性能的，所以这里不进行搜索而是直接在种子列表看运气。

      用 `byre do hitchhike --help` 查看用法。

  - **种子自动下载刷流**：

    **（试验性）**自动选取北邮人站点上相对热门的种子进行下载，在存储空间不足的情况下，
    自动识别本地的冷门种子进行删除。

    用 `byre do main --help` 查看用法。

## 使用方法

### 安装

```console
$ git clone https://github.com/yesh0/byre.git
$ pip3 install --use-pep517 ./byre
$ byre
Usage: byre [OPTIONS] COMMAND [ARGS]...

  北邮人命令行操作以及 BT 软件整合实现。

  软件主要通过 qBittorrent 的标签功能来标记北邮人 PT 的种子， 再在种子名称前加入 ``[byr-北邮人ID]`` 来建立本地种子与
  北邮人种子的关联。

  详细的使用说明请见代码仓库的 README 文件：

      https://github.com/yesh0/byre

选项:
  -c, --config 配置文件路径  TOML 格式配置文件
  -v, --verbose        输出详细信息
  --help               显示此消息并退出。

命令:
  bt   BT 客户端（暂只支持 qBittorrent）接口。
  byr  访问北邮人 PT。
  do   综合北邮人与本地的命令，主要功能所在。
  fix  尝试修复 qBittorrent 中的任务名（也即给名称加上 ``[byr-北邮人ID]`` 的前缀）。
```

1. 启动 qBittorrent，开启 Web UI
2. 设置配置文件
3. 试试 `byre do main --dry-run --print` 吧。

### 配置文件

请见 [byre.example.toml](byre/commands/byre.example.toml)，里面有比较详细的注释说明。总之需要填写：
- 北邮人用户名、密码
- qBittorrent 用户名、密码、端口等
- 下载位置
- 最大允许的占用空间上限、一次下载量上限

不使用北洋园或者 `hitchhike` 命令的话理论上不需要配置北洋园相关的东西。

### 自动刷流配置

我个人用的比较多的是 `byre do main --free-only && byre do hitchhike` 。

### FAQ

1. 北洋园站点无法下载？

   北洋园在第一次下载种子时会跳转到一个“第一次下载提示”页面，你需要手动去下载一个种子然后勾选“下次不再提示”。

2. 北洋园还是无法下载？

   有可能站点发公告了，不手动点击“已读”的话是没法进行任何操作的。请登录站点读公告。

## 愿望清单

- [X] 自动创建 / 打开配置文件并打开编辑器（click 有相关功能）：

  如何更新配置是个问题。

  - [ ] 当缺失配置时至少提示一个配置文件路径（毕竟后台 `crontab` 运行的时候弹编辑器不太好）。
    （可以识别 TTY，但懒。）

- [X] 自动下载 qBittorrent，根据配置文件配置好。

  目前状态：不适合对 Linux 经验不太多的人使用（也就是说可能有各种小 bug 以及需要用户手动配置一些东西）。

- [X] 支持多个 NexusPHP 站点

  - 其实不同站点（北邮人、北洋园等）的种子其实有一些是内容相同的，能合并同时做种岂不美哉？
  - 需要实现的：
    - [X] 每个站点，毕竟都有自己的改动，都需要一套爬虫代码。
    - [X] 内容相同种子合并机制：软链接、硬链接等等，另外 qBittorrent 还可以跳过 hash 检验。
      - [X] 相同种子识别机制（目前指向同一个 `10 G` 文件的两个种子总大小会被计算为 `20 G`。
      - [X] 相同种子删除机制，避免删除的时候删掉一个种子，文件删掉了，而另外一个种子还在。
      - [ ] 现在本地种子列表还只会列北邮人的。
    - [ ] 跨站点种子评分机制……说不定还是需要用户指定一个主站（而例如北洋园还有额外的机制）。
      目前是北邮人为主，其它站点纯粹用北邮人下载的内容来做种。
      （就算这样，我这边 15 个北邮人种子也有 12 个能在北洋园找到，虽然要人工找。）
- [ ] 让用户可以更轻松地指定最大可用空间（例如自动计算硬盘剩余空间）。
- [ ] 多块硬盘的支持（其实多个 `Planner` 应该就可以了）。等我找到地方放某块吵死人不敢用的硬盘先吧。

## 为什么要自己造轮子？

1. 个人对[没有空格的代码](https://github.com/WhymustIhaveaname/ByrBtAutoDownloader/blob/main/byrbt.py)过敏，
   症状包括且不限于浑身发痒、拳头发硬等等。
2. 个人用的是 [qBittorrent](https://www.qbittorrent.org/) 所以想把北邮人 API 部分和种子管理部分好好分离开来。
3. 谁知道呢？说不定只是手痒想写写代码罢了。

## 许可证相关

- [byre/decaptcha](./byre/decaptcha) 里的代码基本是照搬 [bumzy/decaptcha](https://github.com/bumzy/decaptcha) 的。
- [byre/scoring.py](./byre/scoring.py) 里的种子评分的计算方法基本按照
  [WhymustIhaveaname/ByrBtAutoDownloader](https://github.com/WhymustIhaveaname/ByrBtAutoDownloader) 的来。
- [byre/locales](./byre/locales) 里放了一些我对 [click](https://github.com/pallets/click) 的翻译。
