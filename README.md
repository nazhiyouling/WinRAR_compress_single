功能：压缩拖入的文件/文件夹（支持跨文件/文件夹），检查跨磁盘、缺失文件等。  
适用场景：需要压缩零散文件/文件夹，且需验证压缩完整性。  
注意：需提前安装WinRAR，且脚本仅支持Windows系统。  

python环境安装  
www.python.org/downloads/windows/



当前版本（v20260502）的参数如下：  
    "add": "a",                  # 核心指令：添加文件到压缩包  
    "recursive": None,           # 递归处理子目录 -r（None=不递归）  
    "delete_source": "-df",       # 压缩完成后删除源文件 -df  
    "recovery_record": "-rr10",  # 添加10%恢复记录，None=不添加  
    "compress_level": "-m3",     # 压缩级别：-m0~-m5，None=默认  
    "dict_size": "-md32m",       # 字典大小：32MB，None=不指定  
    "encrypt_filename": "-hp",   # 加密压缩包内文件名，None=不加密文件名（仍需密码时只加密数据）  
    "exclude_base_path": "-ep1", # 排除压缩包内的基本路径，None=保留完整路径  
    "progress_percent": "-idp",   # 显示压缩进度百分比，None=不显示百分比  
    "progress_detail": "-idv",    # 显示详细的压缩进度信息，None=不显示详情  
  
    其他配置：  
    延迟重试配置（文件系统刷新延迟）  
         RETRY_MAX = 0       # 最大重试次数（0=不重试）  
         RETRY_DELAY = 1.0   # 重试间隔时间（秒）  
