# !/usr/bin/env python3
# -*- coding: utf-8 -*-
# 功能：压缩拖入的文件/文件夹（支持跨文件/文件夹），检查跨磁盘、缺失文件等
# 适用场景：需要压缩零散文件/文件夹，且需验证压缩完整性
# 注意：需提前安装WinRAR，且脚本仅支持Windows系统

# ===================== 屏蔽无关警告（新增：解决libpng警告） =====================
import warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message="libpng warning:*")
# ==========================================================================

# ===================== 统一可配置参数（方便后期调整） =====================
# WinRAR 压缩命令核心参数配置（对应WinRAR官方命令行参数）
# 将对应值设为 None 即可临时禁用该参数，例如 "delete_source": None 则不删除源文件
WINRAR_CMD_PARAMS = {
    "add": "a",                  # 核心指令：添加文件到压缩包（不可禁）
    "recursive": None,           # 递归处理子目录 -r（None=不递归）
    "delete_source": "-df",       # 压缩完成后删除源文件 -df（None=不删除）
    "recovery_record": "-rr10",  # 添加10%恢复记录，None=不添加
    "compress_level": "-m3",     # 压缩级别：-m0~-m5，None=默认
    "dict_size": "-md32m",       # 字典大小：32MB，None=不指定
    "encrypt_filename": "-hp",   # 加密压缩包内文件名，None=不加密文件名（仍需密码时只加密数据）
    "exclude_base_path": "-ep1", # 排除压缩包内的基本路径，None=保留完整路径
    "progress_percent": "-idp",   # 显示压缩进度百分比，None=不显示百分比
    "progress_detail": "-idv",    # 显示详细的压缩进度信息，None=不显示详情
}

# 压缩包密码（建议定期修改，避免泄露）
# 设为 None 或 "" 可取消密码加密
COMPRESS_PASSWORD = ""

# 延迟重试配置（文件系统刷新延迟）
RETRY_MAX = 0       # 最大重试次数（0=不重试）
RETRY_DELAY = 1.0   # 重试间隔时间（秒）
# ==========================================================================

# 导入标准库模块（按字母顺序排列，便于维护）
import ctypes
import datetime
import glob
import math
import os
import subprocess
import sys
import time
from pathlib import Path

def print_compress_summary(item_count, save_path, archive_name, total_size, vol_str, cmd):
    """
    打印统一格式的压缩参数摘要（根据当前配置动态显示）
    """
    cmd_masked = ' '.join(cmd).replace(f"-p{COMPRESS_PASSWORD}", "-p******") if COMPRESS_PASSWORD else ' '.join(cmd)
    size_mb = total_size / (1024*1024)
    size_gb = total_size / (1024**3)
    
    print("\n" + "="*60)
    print("压缩参数摘要:")
    print(f"- 目标项目: {item_count} 个")
    print("==================================================")
    print(f"- 保存位置: {save_path}")
    print(f"- 压缩名称: {archive_name}.rar")
    print(f"- 原始大小: {size_mb:.2f} MB / {size_gb:.2f} GB")
    print(f"- 分卷策略: {vol_str}")
    print("==================================================")
    # 动态显示可选参数状态
    if WINRAR_CMD_PARAMS.get("recovery_record"):
        print(f"- 恢复记录: 10%")
    if COMPRESS_PASSWORD:
        print(f"- 密码保护: 启用")
    if WINRAR_CMD_PARAMS.get("encrypt_filename") and COMPRESS_PASSWORD:
        print(f"- 加密文件名: 是")
    print("==================================================")
    print(f"开始压缩...")
    print(f"命令: {cmd_masked}")
    print("="*60 + "\n")

def setup_console_buffer():
    """
    设置Windows控制台缓冲区大小，避免输出内容被截断
    """
    try:
        if sys.platform == "win32":
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            kernel32.SetConsoleScreenBufferSize(handle, ctypes.c_long(150 + 3000 * 65536))
    except Exception:
        pass

def get_winrar_path():
    """
    自动查找WinRAR可执行文件路径（兼容32/64位系统）
    """
    winrar_paths = [
        os.path.join(os.environ.get("ProgramFiles", ""), "WinRAR", "WinRAR.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "WinRAR", "WinRAR.exe"),
        os.path.join(os.environ.get("ProgramW6432", ""), "WinRAR", "WinRAR.exe")
    ]
    winrar_paths = [p for p in winrar_paths if p.strip()]
    for path in winrar_paths:
        if os.path.isfile(path):
            return path
    return None

def get_rar_path():
    """
    自动查找Rar.exe（控制台版本）路径，用于lb命令列出压缩包文件
    """
    rar_paths = [
        os.path.join(os.environ.get("ProgramFiles", ""), "WinRAR", "Rar.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "WinRAR", "Rar.exe"),
        os.path.join(os.environ.get("ProgramW6432", ""), "WinRAR", "Rar.exe")
    ]
    rar_paths = [p for p in rar_paths if p.strip()]
    for path in rar_paths:
        if os.path.isfile(path):
            return path
    return None

def calculate_total_size(paths):
    """
    计算文件/文件夹的总大小（字节）
    """
    total_size = 0
    for path in paths:
        try:
            if os.path.isfile(path):
                total_size += os.path.getsize(path)
            else:
                for root, dirs, files in os.walk(path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        total_size += os.path.getsize(file_path)
        except (PermissionError, FileNotFoundError):
            continue
    return total_size

def format_file_size(size_bytes):
    """
    将字节数转换为易读的文件大小格式
    """
    if size_bytes == 0:
        return "0 B"
    size_names = ["B", "KB", "MB", "GB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.2f} {size_names[i]}"

def calculate_volume_size(total_size):
    """
    分卷压缩规则计算（FAT32兼容，无漏洞分卷算法）
    """
    KB = 1024
    MB = 1024 * KB
    FAT32_MAX_SIZE = 4095 * MB

    if total_size < KB:
        return [], "不分卷"
    elif total_size < FAT32_MAX_SIZE:
        first_volume_size_kb = math.ceil(total_size * 0.7 / KB)
        if first_volume_size_kb < 1024:
            vol_param = [f"-v{first_volume_size_kb}k"]
            vol_str = f"第一个分卷: {first_volume_size_kb}KB (70%)，第二个为剩余大小"
        else:
            first_volume_size_mb = math.ceil(first_volume_size_kb / 1024)
            vol_param = [f"-v{first_volume_size_mb}m"]
            vol_str = f"第一个分卷: {first_volume_size_mb}MB (70%)，第二个为剩余大小"
        vol_param.append("-v0")
        return vol_param, vol_str
    else:
        volume_count = math.ceil(total_size / FAT32_MAX_SIZE)
        return ["-v4095m"], f"FAT32兼容分卷：4095MB/卷，共{volume_count}卷"

def verify_archive(rar_path, archive_path, source_base, source_items):
    """
    使用Rar.exe lb命令校验压缩包文件完整性，返回缺失文件列表
    仅在启用 -ep1 时检测，否则跳过
    """
    if not WINRAR_CMD_PARAMS.get("exclude_base_path"):
        print("⚠️  未启用 -ep1，跳过压缩包完整性检测")
        return []
    
    # 生成源文件相对路径集合（基于source_base，排除基本路径）
    source_files = set()
    for item in source_items:
        abs_item = os.path.abspath(item)
        try:
            if os.path.isfile(abs_item):
                rel = os.path.relpath(abs_item, source_base)
                source_files.add(rel)
            elif os.path.isdir(abs_item):
                for root, dirs, files in os.walk(abs_item):
                    for f in files:
                        full = os.path.join(root, f)
                        rel = os.path.relpath(full, source_base)
                        source_files.add(rel)
        except Exception:
            pass
    if not source_files:
        return []

    # 构建 lb 命令
    cmd = [rar_path, 'lb']
    if COMPRESS_PASSWORD and WINRAR_CMD_PARAMS.get("encrypt_filename"):
        # 加密文件名，需用 -hp 提供密码
        cmd.append(f'-hp{COMPRESS_PASSWORD}')
    # 如果仅加密数据未加密文件名，lb 不需要密码也能列出文件名
    cmd.append(archive_path)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding='gbk', errors='replace')
        if proc.returncode != 0:
            print(f"⚠️  Rar.exe lb 执行失败，无法检测完整性")
            return []
        archive_files = set()
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line:
                archive_files.add(line)
        missing = sorted(source_files - archive_files)
        return missing
    except Exception as e:
        print(f"⚠️  完整性检测异常: {e}")
        return []

def display_compressed_files(archive_path):
    """
    显示生成的压缩文件列表（含大小统计）
    """
    print("\n📦 生成的压缩文件:")
    all_found_files = []
    patterns = [
        f"{archive_path}*.rar",
        f"{archive_path}.part*.rar",
        f"{archive_path}*.r0*",
        f"{archive_path}*.r[0-9][0-9]",
        f"{archive_path}.rar"
    ]
    retry_count = 0
    while retry_count <= RETRY_MAX and not all_found_files:
        if retry_count > 0:
            print(f"🔄 重试查找压缩文件 {retry_count}/{RETRY_MAX}")
            time.sleep(RETRY_DELAY)
        all_found_files = []
        for pattern in patterns:
            try:
                found = glob.glob(pattern)
                if found:
                    all_found_files.extend(found)
            except Exception:
                continue
        all_found_files = sorted(list(set(all_found_files)))
        retry_count += 1
    
    if all_found_files:
        print(f"找到 {len(all_found_files)} 个压缩文件:")
        print("-" * 60)
        total_size = 0
        for i, file_path in enumerate(all_found_files, 1):
            try:
                size = os.path.getsize(file_path)
                total_size += size
                print(f"{i:2d}. {os.path.basename(file_path)} 【{format_file_size(size)}】")
            except:
                print(f"{i:2d}. {os.path.basename(file_path)}（无法读取大小）")
        print("-" * 60)
        print(f"📊 总计：{len(all_found_files)} 个文件，总大小 {format_file_size(total_size)}")
    else:
        print("❌ 未找到任何压缩文件")

def main():
    """
    程序主入口
    """
    # 设置控制台缓冲区
    setup_console_buffer()
    # 设置标准输出编码为UTF-8
    if sys.stdout.encoding != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except:
            pass
    
    # 解析拖入的文件/文件夹
    dropped_items = sys.argv[1:]
    if not dropped_items:
        print("❌ 未检测到拖入的文件/文件夹，请将文件/文件夹拖放到此脚本上运行")
        os.system("pause")
        return
    
    # 新增：检查所有拖入项是否在同一个文件夹内
    first_parent = os.path.dirname(os.path.abspath(dropped_items[0]))
    for item in dropped_items[1:]:
        if os.path.dirname(os.path.abspath(item)) != first_parent:
            print("❌ 所有拖入的项必须位于同一个文件夹内！检测到不同父文件夹，操作取消。")
            os.system("pause")
            return
    common_parent = first_parent  # 即A文件夹
    
    # 检查WinRAR是否存在
    winrar = get_winrar_path()
    if not winrar:
        print("❌ 错误：未找到WinRAR程序，请确认已安装WinRAR并配置正确路径")
        os.system("pause")
        return
    
    # 命名规则调整
    if len(dropped_items) == 1 and os.path.isdir(dropped_items[0]):
        # 单一文件夹，使用该文件夹名称
        base_name = os.path.basename(dropped_items[0])
    else:
        # 其他情况（多文件、文件+文件夹混合、多文件夹）使用父文件夹名称
        base_name = os.path.basename(common_parent)
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"{base_name}_{timestamp}"
    archive_path = os.path.join(common_parent, archive_name)
    
    # 计算总大小
    total_size = calculate_total_size(dropped_items)
    vol_param, vol_str = calculate_volume_size(total_size)
    
    # 构建WinRAR命令行（根据配置灵活添加参数）
    cmd = [winrar, WINRAR_CMD_PARAMS["add"]]
    if WINRAR_CMD_PARAMS.get("recursive"): cmd.append(WINRAR_CMD_PARAMS["recursive"])
    if WINRAR_CMD_PARAMS.get("delete_source"): cmd.append(WINRAR_CMD_PARAMS["delete_source"])
    if WINRAR_CMD_PARAMS.get("recovery_record"): cmd.append(WINRAR_CMD_PARAMS["recovery_record"])
    if WINRAR_CMD_PARAMS.get("compress_level"): cmd.append(WINRAR_CMD_PARAMS["compress_level"])
    if WINRAR_CMD_PARAMS.get("dict_size"): cmd.append(WINRAR_CMD_PARAMS["dict_size"])
    if COMPRESS_PASSWORD:
        cmd.append(f"-p{COMPRESS_PASSWORD}")
        if WINRAR_CMD_PARAMS.get("encrypt_filename"):
            cmd.append(WINRAR_CMD_PARAMS["encrypt_filename"])
    if WINRAR_CMD_PARAMS.get("exclude_base_path"): cmd.append(WINRAR_CMD_PARAMS["exclude_base_path"])
    if WINRAR_CMD_PARAMS.get("progress_percent"): cmd.append(WINRAR_CMD_PARAMS["progress_percent"])
    if WINRAR_CMD_PARAMS.get("progress_detail"): cmd.append(WINRAR_CMD_PARAMS["progress_detail"])
    cmd.append(f"{archive_path}.rar")
    if vol_param:
        cmd.extend(vol_param)
    cmd.extend(dropped_items)
    
    print_compress_summary(len(dropped_items), common_parent, archive_name, total_size, vol_str, cmd)
    
    # 执行压缩
    try:
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='gbk', errors='replace'
        )
        while True:
            line = process.stdout.readline()
            if line == "" and process.poll() is not None:
                break
            if line:
                print(line.strip(), end='\r')
        
        returncode = process.returncode
        if returncode == 0:
            print("\n\n✅ 压缩命令执行成功！")
            # 缺失文件检测
            rar_exe = get_rar_path()
            if rar_exe:
                missing = verify_archive(rar_exe, f"{archive_path}.rar", common_parent, dropped_items)
                if missing:
                    print(f"\n⚠️  缺失文件检测：发现 {len(missing)} 个文件未在压缩包中：")
                    for f in missing:
                        print(f"  - {f}")
                else:
                    print("✅ 完整性检测通过，无缺失文件。")
            else:
                print("⚠️  未找到 Rar.exe，跳过压缩包完整性检测。")
        else:
            print(f"\n\n❌ 压缩命令执行失败，错误码：{returncode}")
        
        display_compressed_files(archive_path)
    except Exception as e:
        print(f"\n❌ 执行压缩时发生异常：{str(e)}")
    finally:
        print("\n" + "="*50)
        os.system("pause")

if __name__ == "__main__":
    main()