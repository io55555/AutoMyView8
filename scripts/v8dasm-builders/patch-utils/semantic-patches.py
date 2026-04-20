#!/usr/bin/env python3
"""
semantic-patches.py - 语义化 Patch 应用脚本

针对简单的代码删除/替换使用正则表达式实现，避免对行号的依赖。
这是多级退避策略的第4级，当 git apply 和 wiggle 都失败时使用。

用法: semantic-patches.py <v8_dir> <log_file>

处理的文件:
1. src/objects/string.cc - 删除字符串截断逻辑
2. src/snapshot/deserializer.cc - 删除魔数检查
3. src/snapshot/code-serializer.cc - 绕过完整性检查
"""

import os
import re
import sys
from pathlib import Path


class SemanticPatcher:
    """语义化 Patch 应用器"""

    def __init__(self, v8_dir: str, log_file: str, verify_only: bool = False):
        self.v8_dir = Path(v8_dir)
        self.log_file = Path(log_file)
        self.verify_only = verify_only
        self.results: dict[str, str] = {}

    def log(self, message: str):
        print(message)
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(message + '\n')

    def record_result(self, name: str, status: str):
        self.results[name] = status
        self.log(f"[SEMANTIC] {name}: {status}")

    def patch_string_cc(self) -> str:
        file_path = self.v8_dir / 'src/objects/string.cc'
        target_marker = 'accumulator->Add("...<truncated>>")'
        pattern = r'\s*if\s*\(\s*len\s*>\s*kMaxShortPrintLength\s*\)\s*\{[^}]*\}\s*\n?'
        return self._apply_or_verify_block('string.cc', file_path, pattern, '\n', target_marker)

    def patch_deserializer_cc(self) -> str:
        file_path = self.v8_dir / 'src/snapshot/deserializer.cc'
        target_marker = 'CHECK_EQ(magic_number_, SerializedData::kMagicNumber);'
        pattern = r'\s*CHECK_EQ\s*\(\s*magic_number_\s*,\s*SerializedData::kMagicNumber\s*\)\s*;?\s*\n?'
        return self._apply_or_verify_block('deserializer.cc', file_path, pattern, '', target_marker)

    def patch_code_serializer_cc(self) -> str:
        file_path = self.v8_dir / 'src/snapshot/code-serializer.cc'
        target_marker = 'return SerializedCodeSanityCheckResult::kSuccess;'
        pattern = (
            r'(SerializedCodeSanityCheckResult\s+SerializedCodeData::SanityCheck\s*'
            r'\([^)]*\)\s*const\s*\{)\s*'
            r'SerializedCodeSanityCheckResult\s+result\s*=\s*SanityCheckWithoutSource\s*\(\s*\)\s*;\s*'
            r'if\s*\([^)]*\)\s*return\s+result\s*;\s*'
            r'return\s+SanityCheckJustSource\s*\([^)]*\)\s*;'
        )
        replacement = r'\1\n  return SerializedCodeSanityCheckResult::kSuccess;'
        return self._apply_or_verify_block('code-serializer.cc', file_path, pattern, replacement, target_marker, flags=re.DOTALL)

    def _apply_or_verify_block(self, name: str, file_path: Path, pattern: str, replacement: str, target_marker: str, flags: int = 0) -> str:
        if not file_path.exists():
            self.log(f"[SEMANTIC] ✗ 文件不存在: {file_path}")
            return 'failed'

        try:
            content = file_path.read_text(encoding='utf-8')
        except Exception as e:
            self.log(f"[SEMANTIC] ✗ 读取文件失败: {e}")
            return 'failed'

        has_pattern = re.search(pattern, content, flags) is not None
        has_target_state = target_marker not in content

        if self.verify_only:
            return 'already_target_state' if has_target_state else 'not_matched_unverified'

        if not has_pattern:
            return 'already_target_state' if has_target_state else 'not_matched_unverified'

        new_content = re.sub(pattern, replacement, content, flags=flags)
        if content == new_content:
            return 'not_matched_unverified'

        try:
            file_path.write_text(new_content, encoding='utf-8')
        except Exception as e:
            self.log(f"[SEMANTIC] ✗ 写入文件失败: {e}")
            return 'failed'

        try:
            updated = file_path.read_text(encoding='utf-8')
        except Exception as e:
            self.log(f"[SEMANTIC] ✗ 验证读取失败: {e}")
            return 'failed'

        return 'applied_now' if target_marker not in updated else 'failed'

    def apply_all(self) -> bool:
        action = '验证' if self.verify_only else '应用'
        self.log(f"[SEMANTIC] 开始{action}语义化 patch...")
        self.log("")

        patches = [
            ('string.cc', self.patch_string_cc),
            ('deserializer.cc', self.patch_deserializer_cc),
            ('code-serializer.cc', self.patch_code_serializer_cc),
        ]

        allowed_success = {'applied_now', 'already_target_state'}

        for name, patch_func in patches:
            self.log(f"[SEMANTIC] 正在处理 {name}...")
            try:
                status = patch_func()
            except Exception as e:
                self.log(f"[SEMANTIC] ✗ 处理 {name} 时发生异常: {e}")
                status = 'failed'
            self.record_result(name, status)
            self.log("")

        success = all(status in allowed_success for status in self.results.values())
        self.log(f"[SEMANTIC] 结果: {self.results}")
        self.log("")
        return success


def main():
    verify_only = False
    args = sys.argv[1:]

    if args and args[0] == '--verify':
        verify_only = True
        args = args[1:]

    if len(args) < 2:
        print("用法: semantic-patches.py [--verify] <v8_dir> <log_file>")
        print("")
        print("参数:")
        print("  v8_dir   - V8 源码目录的绝对路径")
        print("  log_file - 日志文件的绝对路径")
        sys.exit(1)

    v8_dir = args[0]
    log_file = args[1]

    if not os.path.isdir(v8_dir):
        print(f"错误: V8 目录不存在: {v8_dir}")
        sys.exit(1)

    patcher = SemanticPatcher(v8_dir, log_file, verify_only=verify_only)
    success = patcher.apply_all()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
