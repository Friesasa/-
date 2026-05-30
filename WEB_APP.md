# 小红书媒介自动填表网站

这是在原本 Excel 自动生成工具上新增的 Web 版 MVP。

## 本地启动

安装依赖：

```powershell
py -m pip install -r requirements.txt
```

启动网站：

```powershell
py -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

也可以双击：

```text
启动网站.bat
```

浏览器打开：

```text
http://127.0.0.1:8000
```

## 使用流程

1. 上传最新刊例或蒲公英导出表，生成达人库。
2. 上传品牌给的 Excel 表格，创建填写任务。
3. 在任务表中选择当前行，输入达人昵称、小红书号、博主 ID 或主页链接，点击“补齐当前行刊例信息”。
4. 粘贴该达人的二询文字，点击“解析二询并填入当前行”。
5. 黄色单元格和“待补充”标签表示缺失项，需要人工确认或补充。
6. 在线编辑后保存，最后导出品牌 Excel。

## 大模型配置

默认没有 `OPENAI_API_KEY` 时，会使用本地关键词规则解析二询文字。要启用大模型解析，在环境变量中配置：

```powershell
$env:OPENAI_API_KEY="你的 API Key"
$env:OPENAI_BASE_URL="https://api.openai.com/v1"
$env:OPENAI_MODEL="gpt-4.1-mini"
```

如果使用兼容 OpenAI 接口的模型服务，把 `OPENAI_BASE_URL` 和 `OPENAI_MODEL` 改成对应值即可。

## 多人账号

Web 版已支持注册、登录和按账号隔离数据。每个账号只能看到自己的刊例库、品牌任务、上传文件和导出文件。

建议线上配置：

```text
SECRET_KEY=一串足够长的随机字符串
REGISTER_INVITE_CODE=可选的邀请码
```

如果设置了 `REGISTER_INVITE_CODE`，新用户注册时必须填写对应邀请码；不设置则允许公开注册。

## 已针对样例支持的二询字段

- 报备图文报价
- 返点比例
- 5.31 档期是否 OK
- 可否免费分发其他平台
- 免费授权信息流 6 个月
- 是否 8 折改价接单
- 可否自行投薯条或具体金额
- 二询备注

## 云端部署提示

本地默认使用 SQLite，适合单机开发和快速试用。线上多人长期使用时，建议：

- 使用 PostgreSQL，配置 `DATABASE_URL`。
- 把 `uploads/`、`exports/` 放到对象存储或持久化磁盘，并配置 `STORAGE_DIR`。
- 给 FastAPI 加登录鉴权和 HTTPS 反向代理。
- 把 API Key 放到服务器环境变量，不要写入代码。

## Docker 部署

```powershell
docker build -t xiaohongshu-ratecard .
docker run -p 8000:8000 -e OPENAI_API_KEY="你的 API Key" xiaohongshu-ratecard
```

## Render 部署

仓库里已提供 `render.yaml`，在 Render 新建 Blueprint 时选择该仓库即可。部署后需要在 Render 控制台补充：

```text
OPENAI_API_KEY=你的 API Key
REGISTER_INVITE_CODE=可选的邀请码
```

当前 `render.yaml` 使用免绑卡配置，只创建 Web Service，并使用本地 SQLite 和本地文件目录先跑通流程。免费实例的本地文件不保证永久保存；长期正式使用时，再把 `DATABASE_URL` 配成 PostgreSQL，并增加持久磁盘或对象存储。

