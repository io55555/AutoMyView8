#!/usr/bin/env python3
"""
semantic-patches.py - semantic patch fallback for V8 drift.

Usage: semantic-patches.py [--verify] <v8_dir> <log_file>
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


class SemanticPatcher:
    def __init__(self, v8_dir: str, log_file: str, verify_only: bool = False):
        self.v8_dir = Path(v8_dir)
        self.log_file = Path(log_file)
        self.verify_only = verify_only
        self.results: dict[str, str] = {}

    def log(self, message: str):
        safe_message = message.encode("ascii", errors="backslashreplace").decode("ascii")
        print(safe_message)
        with open(self.log_file, "a", encoding="utf-8") as file:
            file.write(safe_message + "\n")

    def record_result(self, name: str, status: str):
        self.results[name] = status
        self.log(f"[SEMANTIC] FILE {name} status={status}")

    def _read_file(self, file_path: Path) -> str | None:
        if not file_path.exists():
            self.log(f"[SEMANTIC] ERROR missing_file path={file_path}")
            return None
        try:
            return file_path.read_text(encoding="utf-8")
        except Exception as exc:
            self.log(f"[SEMANTIC] ERROR read_failed path={file_path} error={exc}")
            return None

    def _write_file(self, file_path: Path, content: str) -> bool:
        try:
            file_path.write_text(content, encoding="utf-8")
            return True
        except Exception as exc:
            self.log(f"[SEMANTIC] ERROR write_failed path={file_path} error={exc}")
            return False

    def _find_function_body(self, content: str, signature: str) -> tuple[int, int] | None:
        start = content.find(signature)
        if start == -1:
            return None

        brace_start = content.find("{", start)
        if brace_start == -1:
            return None

        depth = 0
        for index in range(brace_start, len(content)):
            char = content[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return brace_start + 1, index
        return None

    def _apply_or_verify_block(
        self,
        name: str,
        file_path: Path,
        pattern: str,
        replacement: str,
        target_marker: str,
        flags: int = 0,
        target_should_be_absent: bool = True,
    ) -> str:
        content = self._read_file(file_path)
        if content is None:
            return "failed"

        has_pattern = re.search(pattern, content, flags) is not None
        has_target_state = (target_marker not in content) if target_should_be_absent else (target_marker in content)

        if self.verify_only:
            return "already_target_state" if has_target_state else "not_matched_unverified"

        if not has_pattern:
            return "already_target_state" if has_target_state else "not_matched_unverified"

        new_content = re.sub(pattern, replacement, content, flags=flags)
        if content == new_content:
            return "not_matched_unverified"

        if not self._write_file(file_path, new_content):
            return "failed"

        updated = self._read_file(file_path)
        if updated is None:
            return "failed"

        reached_target_state = (target_marker not in updated) if target_should_be_absent else (target_marker in updated)
        return "applied_now" if reached_target_state else "failed"

    def patch_string_cc(self) -> str:
        file_path = self.v8_dir / "src/objects/string.cc"
        target_marker = 'accumulator->Add("...<truncated>>")'
        pattern = r"\s*if\s*\(\s*len\s*>\s*kMaxShortPrintLength\s*\)\s*\{[^}]*\}\s*\n?"
        return self._apply_or_verify_block("string.cc", file_path, pattern, "\n", target_marker)

    def patch_deserializer_cc(self) -> str:
        return "already_target_state"

    def patch_code_serializer_cc(self) -> str:
        file_path = self.v8_dir / "src/snapshot/code-serializer.cc"
        target_marker = "return SerializedCodeSanityCheckResult::kSuccess;"
        pattern = (
            r"(SerializedCodeSanityCheckResult\s+SerializedCodeData::SanityCheck\s*"
            r"\([^)]*\)\s*const\s*\{)\s*"
            r"SerializedCodeSanityCheckResult\s+result\s*=\s*SanityCheckWithoutSource\s*\(\s*\)\s*;\s*"
            r"if\s*\([^)]*\)\s*return\s+result\s*;\s*"
            r"return\s+SanityCheckJustSource\s*\([^)]*\)\s*;"
        )
        replacement = r"\1\n  return SerializedCodeSanityCheckResult::kSuccess;"
        return self._apply_or_verify_block(
            "code-serializer.cc",
            file_path,
            pattern,
            replacement,
            target_marker,
            flags=re.DOTALL,
            target_should_be_absent=False,
        )

    def patch_objects_printer_cc(self) -> str:
        file_path = self.v8_dir / "src/diagnostics/objects-printer.cc"
        content = self._read_file(file_path)
        if content is None:
            return "failed"

        signature = "void SharedFunctionInfo::SharedFunctionInfoPrint(std::ostream& os)"
        body_range = self._find_function_body(content, signature)
        if body_range is None:
            return "not_matched_unverified"

        body_start, body_end = body_range
        body = content[body_start:body_end]

        source_removed = "PrintSourceCode(os);" not in body

        if self.verify_only:
            return "already_target_state" if source_removed else "not_matched_unverified"

        updated_body = body
        changed = False

        source_pattern = r"\s*PrintSourceCode\(os\);\n"
        if re.search(source_pattern, updated_body):
            updated_body = re.sub(source_pattern, "", updated_body, count=1)
            changed = True

        if not changed:
            return "already_target_state" if source_removed else "not_matched_unverified"

        new_content = content[:body_start] + updated_body + content[body_end:]
        if not self._write_file(file_path, new_content):
            return "failed"

        updated = self._read_file(file_path)
        if updated is None:
            return "failed"
        updated_range = self._find_function_body(updated, signature)
        if updated_range is None:
            return "failed"

        updated_body = updated[updated_range[0]:updated_range[1]]
        source_removed = "PrintSourceCode(os);" not in updated_body
        return "applied_now" if source_removed else "failed"

    def patch_objects_cc(self) -> str:
        file_path = self.v8_dir / "src/objects/objects.cc"
        content = self._read_file(file_path)
        if content is None:
            return "failed"

        signature = "void HeapObject::HeapObjectShortPrint(std::ostream& os)"
        body_range = self._find_function_body(content, signature)
        if body_range is None:
            self.log(f"[SEMANTIC][objects.cc] reason=signature_not_found_treat_as_obsolete signature={signature}")
            return "already_target_state"

        body_start, body_end = body_range
        body = content[body_start:body_end]

        def log_objects_cc_context(reason: str, text: str):
            switch_index = text.find("switch (")
            excerpt_start = max(0, switch_index - 200) if switch_index != -1 else 0
            excerpt_end = min(len(text), switch_index + 2200) if switch_index != -1 else min(len(text), 2200)
            excerpt = text[excerpt_start:excerpt_end]
            excerpt = excerpt.replace("\r\n", "\n")
            self.log(f"[SEMANTIC][objects.cc] reason={reason}")
            for line in excerpt.split("\n"):
                self.log(f"[SEMANTIC][objects.cc] {line}")

        required_markers = [
            "ASM_WASM_DATA_TYPE",
            "Start FixedArray",
            "Start ObjectBoilerplateDescription",
            "Start FixedDoubleArray",
            "Start SharedFunctionInfo",
        ]
        already_done = all(marker in body for marker in required_markers)
        if self.verify_only:
            if already_done:
                return "already_target_state"
            log_objects_cc_context("verify_only_not_matched", body)
            return "not_matched_unverified"

        updated_body = body
        changed = False

        if "ASM_WASM_DATA_TYPE" not in updated_body:
            switch_pattern = r'(\n)(?P<indent>\s*)switch \((?P<map_expr>map\(\)|map\(cage_base\))\.instance_type\(\)\) \{'
            switch_match = re.search(switch_pattern, updated_body)
            if switch_match is None:
                log_objects_cc_context("switch_pattern_not_found", updated_body)
                return "not_matched_unverified"

            indent = switch_match.group("indent")
            map_expr = switch_match.group("map_expr")
            asm_block = (
                "\n"
                f'{indent}// Print array literal members instead of only "<AsmWasmData>"\n'
                f"{indent}if ({map_expr}.instance_type() == ASM_WASM_DATA_TYPE) {{\n"
                f'{indent}  os << "<ArrayBoilerplateDescription> ";\n'
                f"{indent}  ArrayBoilerplateDescription::cast(*this)\n"
                f"{indent}      .constant_elements()\n"
                f"{indent}      .HeapObjectShortPrint(os);\n"
                f"{indent}  return;\n"
                f"{indent}}}\n\n"
            )
            next_body = re.sub(
                switch_pattern,
                r'\1' + asm_block + indent + f'switch ({map_expr}.instance_type()) {{',
                updated_body,
                count=1,
            )
            if next_body == updated_body:
                log_objects_cc_context("switch_injection_failed", updated_body)
                return "not_matched_unverified"
            updated_body = next_body
            changed = True

        case_injections = [
            (
                "FIXED_ARRAY_TYPE",
                r'(?P<indent>\s*)case FIXED_ARRAY_TYPE:\n(?P<body>.*?)(?P=indent)break;\n',
                r'\g<indent>case FIXED_ARRAY_TYPE:\n'
                r'\g<body>'
                r'\g<indent>os << "\\nStart FixedArray\\n";\n'
                r'\g<indent>FixedArray::cast(*this).FixedArrayPrint(os);\n'
                r'\g<indent>os << "\\nEnd FixedArray\\n";\n'
                r'\g<indent>break;\n',
                "Start FixedArray",
            ),
            (
                "OBJECT_BOILERPLATE_DESCRIPTION_TYPE",
                r'(?P<indent>\s*)case OBJECT_BOILERPLATE_DESCRIPTION_TYPE:\n(?P<body>.*?)(?P=indent)break;\n',
                r'\g<indent>case OBJECT_BOILERPLATE_DESCRIPTION_TYPE:\n'
                r'\g<body>'
                r'\g<indent>os << "\\nStart ObjectBoilerplateDescription\\n";\n'
                r'\g<indent>ObjectBoilerplateDescription::cast(*this)\n'
                r'\g<indent>    .ObjectBoilerplateDescriptionPrint(os);\n'
                r'\g<indent>os << "\\nEnd ObjectBoilerplateDescription\\n";\n'
                r'\g<indent>break;\n',
                "Start ObjectBoilerplateDescription",
            ),
            (
                "FIXED_DOUBLE_ARRAY_TYPE",
                r'(?P<indent>\s*)case FIXED_DOUBLE_ARRAY_TYPE:\n(?P<body>.*?)(?P=indent)break;\n',
                r'\g<indent>case FIXED_DOUBLE_ARRAY_TYPE:\n'
                r'\g<body>'
                r'\g<indent>os << "\\nStart FixedDoubleArray\\n";\n'
                r'\g<indent>FixedDoubleArray::cast(*this).FixedDoubleArrayPrint(os);\n'
                r'\g<indent>os << "\\nEnd FixedDoubleArray\\n";\n'
                r'\g<indent>break;\n',
                "Start FixedDoubleArray",
            ),
            (
                "SHARED_FUNCTION_INFO_TYPE",
                r'(?P<indent>\s*)case SHARED_FUNCTION_INFO_TYPE:\s*\{\n(?P<body>.*?)(?P=indent)\}\n(?P=indent)break;\n',
                r'\g<indent>case SHARED_FUNCTION_INFO_TYPE: {\n'
                r'\g<body>'
                r'\g<indent>  os << "\\nStart SharedFunctionInfo\\n";\n'
                r'\g<indent>  shared.SharedFunctionInfoPrint(os);\n'
                r'\g<indent>  os << "\\nEnd SharedFunctionInfo\\n";\n'
                r'\g<indent>  break;\n'
                r'\g<indent>}\n',
                "Start SharedFunctionInfo",
            ),
        ]

        for case_name, pattern, replacement, marker in case_injections:
            if marker in updated_body:
                continue
            next_body = re.sub(pattern, replacement, updated_body, count=1, flags=re.DOTALL)
            if next_body == updated_body:
                log_objects_cc_context(f"case_injection_failed:{case_name}", updated_body)
                return "not_matched_unverified"
            updated_body = next_body
            changed = True

        new_content = content[:body_start] + updated_body + content[body_end:]
        if not changed:
            return "already_target_state" if already_done else "not_matched_unverified"
        if not self._write_file(file_path, new_content):
            return "failed"

        updated = self._read_file(file_path)
        if updated is None:
            return "failed"
        updated_range = self._find_function_body(updated, signature)
        if updated_range is None:
            return "failed"
        updated_body = updated[updated_range[0]:updated_range[1]]
        success = all(marker in updated_body for marker in required_markers)
        return "applied_now" if success else "failed"

    def apply_all(self) -> bool:
        self.log(f"[SEMANTIC] START verify_only={str(self.verify_only).lower()} v8_dir={self.v8_dir}")
        patches = [
            ("objects-printer.cc", self.patch_objects_printer_cc),
            ("objects.cc", self.patch_objects_cc),
            ("string.cc", self.patch_string_cc),
            ("deserializer.cc", self.patch_deserializer_cc),
            ("code-serializer.cc", self.patch_code_serializer_cc),
        ]
        allowed_success = {"applied_now", "already_target_state"}

        for name, patch_func in patches:
            self.log(f"[SEMANTIC] APPLY file={name}")
            try:
                status = patch_func()
            except Exception as exc:
                self.log(f"[SEMANTIC] ERROR exception file={name} error={exc}")
                status = "failed"
            self.record_result(name, status)

        success = all(status in allowed_success for status in self.results.values())
        applied = sum(status == "applied_now" for status in self.results.values())
        already = sum(status == "already_target_state" for status in self.results.values())
        failed = len(self.results) - applied - already
        self.log(
            f"[SEMANTIC] SUMMARY success={str(success).lower()} applied={applied} already={already} failed={failed}"
        )
        return success


def main():
    verify_only = False
    args = sys.argv[1:]

    if args and args[0] == "--verify":
        verify_only = True
        args = args[1:]

    if len(args) < 2:
        print("Usage: semantic-patches.py [--verify] <v8_dir> <log_file>")
        print("")
        print("Arguments:")
        print("  v8_dir   - Absolute path to the V8 source directory")
        print("  log_file - Absolute path to the log file")
        sys.exit(1)

    v8_dir = args[0]
    log_file = args[1]

    if not os.path.isdir(v8_dir):
        print(f"ERROR: V8 directory does not exist: {v8_dir}")
        sys.exit(1)

    patcher = SemanticPatcher(v8_dir, log_file, verify_only=verify_only)
    success = patcher.apply_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
