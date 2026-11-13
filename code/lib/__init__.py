"""lib —— 实现层（按领域拆分，不含流程编排）。

config.py    路径与参数默认值
logger.py    双写日志
cli.py       命令行解析
browser.py   Chrome CDP 接管
session.py   会话状态（端口 / 浏览器 / 标签页）
auth.py      登录检测
listener.py  GraphQL 监听（GraphQLRecorder）
scroll.py    滚动动作
utils.py     输入清单 / 切片 / 停顿
"""
