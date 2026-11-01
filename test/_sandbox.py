"""测试用的数据目录隔离。

`paths.data_dir()` / `store.data_dir()` 都是每次调用现读环境变量
LOCALAPPDATA，所以只要在 import core 之前把它指到临时目录，
测试写出来的 config.json / tasks.json 就落不到用户真实的那份里。

以前是「测试开始备份、结束还原」，一旦中途崩了（比如截图那步抛异常）
还原就跑不到，用户的配置直接没了。隔离之后不存在这个风险。
"""

import atexit
import os
import shutil
import tempfile


def isolate() -> str:
    d = tempfile.mkdtemp(prefix="qingti-test-")
    os.environ["LOCALAPPDATA"] = d
    atexit.register(shutil.rmtree, d, True)
    return os.path.join(d, "轻提")
