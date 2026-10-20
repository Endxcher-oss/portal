# portal

把本机若干个端口临时发布到公网，每个端口一个随机域名，用一条带 token 的链接访问，不用密码、不用开防火墙、不用买域名。

## 依赖

- Python 3.11+（用到标准库 `tomllib`，无第三方包）
- `cloudflared` 在 `PATH` 里

## 快速开始

```sh
~/portal/start.sh --port 3000 --port 7681
```

启动后会打印每个端口的域名、索引链接和一个二维码：

```
portal   2/2 个端口已上线
  3000    未命名        https://quiet-river-dawn.trycloudflare.com
  7681    未命名        https://silver-lake-mist.trycloudflare.com
索引     https://quiet-river-dawn.trycloudflare.com/_portal/?token=…
提示     链接即权限，谁拿到链接谁就能用；进程退出后链接和 token 一起失效。
```

用手机扫码或在浏览器打开索引链接，会看到所有端口，点哪个进哪个。`Ctrl-C` 关掉全部隧道。

## 配置文件

`--port` 只写端口，想给端口起名字就写 `config.toml`：

```toml
[[target]]
port = 7681
name = "webterm"

[[target]]
port = 3000
name = "dev server"
```

```sh
~/portal/start.sh                      # 自动读当前目录的 config.toml
~/portal/start.sh --config other.toml  # 指定文件
~/portal/start.sh --port 8080          # 和配置文件合并，按端口去重
```

## 访问是怎么走的

1. 打开链接，链接里的 `?token=` 只在你第一次打开时出现；服务端用它换一枚 30 天的 cookie，然后 303 跳到不带 token 的干净地址。
2. 之后每个请求都带 cookie，portal 把请求原样转给 `127.0.0.1:<端口>`。
3. 每个端口是独立的域名，浏览器把它们当成互不相干的站点——所以可以同时开着好几个端口，各自的登录状态互不干扰。

## 安全模型

- token 是 capability URL：链接本身就是权限，拿到链接的人就能访问，别往公开地方贴。
- token 每次启动重新随机生成（也可以用 `--token` 固定），进程一退出，旧链接和旧 cookie 一起失效。
- cookie 是 `HttpOnly` + `SameSite=Lax`，只在 HTTPS 下加 `Secure`。
- 隧道是 cloudflared 的出站连接，本机不需要开放任何入站端口。

## 限制

- 快速隧道的域名是随机的，每次重启都会变。
- 公网可达性依赖 Cloudflare，首次建立隧道要十几秒。
- 本地端口没有服务在监听时返回 503，并说明是哪个端口。
- 只做透明转发，不改写 `Host`：像 DSH 这种只信任 loopback `Host` 的应用，直接发布会被它自己拒绝。
- 已经自带登录页的应用（比如 webterm）发布后仍会让你先登它的页面，等于两层门。

## 目录

- `portal/` 源码
- `docs/design.md` 设计说明与取舍
