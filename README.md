# byre - 一款北邮人 PT 命令行操作软件

（示例图片用的 asciinema 的中文渲染有问题，将就着看吧。）

[![asciicast](https://asciinema.org/a/570391.svg)](https://asciinema.org/a/570391)

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

请见 [byre.example.toml](byre/byre.example.toml)，里面有比较详细的注释说明。总之需要填写：
- 北邮人用户名、密码
- qBittorrent 用户名、密码、端口等
- 下载位置
- 最大允许的占用空间上限、一次下载量上限

## 愿望清单

- [ ] 自动创建 / 打开配置文件并打开编辑器（click 有相关功能）。

- [ ] 自动下载 qBittorrent，根据配置文件配置好。

- [ ] 支持多个 NexusPHP 站点

  - 其实不同站点（北邮人、北洋园等）的种子其实有一些是内容相同的，能合并同时做种岂不美哉？
  - 需要实现的：
    - [ ] 每个站点，毕竟都有自己的改动，都需要一套爬虫代码。
    - [ ] 内容相同种子合并机制：软链接、硬链接等等，另外 qBittorrent 还可以跳过 hash 检验。
    - [ ] 跨站点种子评分机制……说不定还是需要用户指定一个主站（而例如北洋园还有额外的机制）。

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
