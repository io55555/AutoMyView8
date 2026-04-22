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

    def _find_function_body_regex(self, content: str, signature_pattern: str, flags: int = 0) -> tuple[int, int] | None:
        match = re.search(signature_pattern, content, flags)
        if match is None:
            return None

        brace_start = content.find("{", match.start())
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
        file_path = self.v8_dir / "src/snapshot/deserializer.cc"
        target_marker = "CHECK_EQ(magic_number_, SerializedData::kMagicNumber);"
        pattern = r"\s*CHECK_EQ\(magic_number_,\s*SerializedData::kMagicNumber\);\n"
        return self._apply_or_verify_block(
            "deserializer.cc",
            file_path,
            pattern,
            "\n",
            target_marker,
        )

    def patch_code_serializer_cc(self) -> str:
        file_path = self.v8_dir / "src/snapshot/code-serializer.cc"
        content = self._read_file(file_path)
        if content is None:
            return "failed"

        deserialize_range = self._find_function_body_regex(
            content,
            r"CodeSerializer::Deserialize\s*\(",
        )
        if deserialize_range is None:
            self.log("[SEMANTIC][code-serializer.cc] reason=deserialize_signature_not_found")
            return "not_matched_unverified"

        deserialize_body = content[deserialize_range[0]:deserialize_range[1]]
        has_print_block = "Start SharedFunctionInfo" in deserialize_body
        has_sanity_override = "return SerializedCodeSanityCheckResult::kSuccess;" in content

        if self.verify_only:
            return "already_target_state" if (has_print_block and has_sanity_override) else "not_matched_unverified"

        updated_content = content
        changed = False

        if not has_print_block:
            print_block = (
                "\n"
                '  std::cout << "\\nStart SharedFunctionInfo\\n";\n'
                '  result->SharedFunctionInfoPrint(std::cout);\n'
                '  std::cout << "\\nEnd SharedFunctionInfo\\n";\n'
                '  std::cout << std::flush;\n'
            )
            anchor_patterns = [
                r"(^\s*BaselineBatchCompileIfSparkplugCompiled\s*\(\s*isolate\s*,)",
                r"(^\s*script->set_deserialized\s*\(\s*true\s*\);\s*$)",
                r"(^\s*FinalizeDeserialization\s*\(.*$)",
            ]
            next_content = updated_content
            for anchor_pattern in anchor_patterns:
                next_content = re.sub(
                    anchor_pattern,
                    lambda match: print_block + match.group(1),
                    updated_content,
                    count=1,
                    flags=re.MULTILINE,
                )
                if next_content != updated_content:
                    break
            if next_content == updated_content:
                self.log("[SEMANTIC][code-serializer.cc] reason=print_anchor_not_found")
                return "not_matched_unverified"
            updated_content = next_content
            changed = True

        sanity_pattern = (
            r"(SerializedCodeSanityCheckResult\s+SerializedCodeData::SanityCheck\s*"
            r"\([^)]*\)\s*const\s*\{)\s*"
            r"SerializedCodeSanityCheckResult\s+result\s*=\s*SanityCheckWithoutSource\s*\(\s*\)\s*;\s*"
            r"if\s*\([^)]*\)\s*return\s+result\s*;\s*"
            r"return\s+SanityCheckJustSource\s*\([^)]*\)\s*;"
        )
        if not has_sanity_override:
            next_content = re.sub(
                sanity_pattern,
                r"\1\n  return SerializedCodeSanityCheckResult::kSuccess;",
                updated_content,
                count=1,
                flags=re.DOTALL,
            )
            if next_content == updated_content:
                return "not_matched_unverified"
            updated_content = next_content
            changed = True

        if not changed:
            return "already_target_state"
        if not self._write_file(file_path, updated_content):
            return "failed"

        updated = self._read_file(file_path)
        if updated is None:
            return "failed"
        updated_range = self._find_function_body_regex(
            updated,
            r"CodeSerializer::Deserialize\s*\(",
        )
        if updated_range is None:
            return "failed"
        updated_body = updated[updated_range[0]:updated_range[1]]
        success = (
            "Start SharedFunctionInfo" in updated_body
            and "return SerializedCodeSanityCheckResult::kSuccess;" in updated
        )
        return "applied_now" if success else "failed"

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
        has_bytecode_block = "Start BytecodeArray" in body and "GetActiveBytecodeArray(isolate)->Disassemble(os);" in body

        if self.verify_only:
            return "already_target_state" if (source_removed and has_bytecode_block) else "not_matched_unverified"

        updated_body = body
        changed = False

        source_pattern = r"\s*PrintSourceCode\(os\);\n"
        if re.search(source_pattern, updated_body):
            updated_body = re.sub(source_pattern, "", updated_body, count=1)
            changed = True

        if not has_bytecode_block:
            tail_anchor = '  os << "\\n";\n'
            bytecode_block = (
                '  os << "\\nStart BytecodeArray\\n";\n'
                '  GetActiveBytecodeArray(isolate)->Disassemble(os);\n'
                '  os << "\\nEnd BytecodeArray\\n";\n'
                '  os << std::flush;\n'
            )
            if tail_anchor not in updated_body:
                return "not_matched_unverified"
            updated_body = updated_body.replace(tail_anchor, tail_anchor + bytecode_block, 1)
            changed = True

        if not changed:
            return "already_target_state" if (source_removed and has_bytecode_block) else "not_matched_unverified"

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
        candidate_files = [
            self.v8_dir / "src/objects/objects.cc",
            self.v8_dir / "src/diagnostics/objects-printer.cc",
        ]

        required_markers = [
            "Start FixedArray",
            "Start ObjectBoilerplateDescription",
            "Start FixedDoubleArray",
            "Start SharedFunctionInfo",
        ]
        optional_markers = [
            "ASM_WASM_DATA_TYPE",
        ]

        for file_path in candidate_files:
            content = self._read_file(file_path)
            if content is None:
                continue

            body_range = self._find_function_body(content, "void HeapObject::HeapObjectShortPrint(std::ostream& os)")
            if body_range is None:
                body_range = self._find_function_body_regex(
                    content,
                    r"void\s+HeapObject::HeapObjectShortPrint\s*\(\s*std::ostream\s*&\s*os\s*\)",
                )
            if body_range is None:
                continue

            body_start, body_end = body_range
            body = content[body_start:body_end]
            already_done = all(marker in body for marker in required_markers)
            optional_done = all(marker in body for marker in optional_markers)
            if self.verify_only:
                return "already_target_state" if already_done else "not_matched_unverified"

            updated_body = body
            changed = False

            if not optional_done and "ASM_WASM_DATA_TYPE" not in updated_body:
                switch_pattern = r'(\n)(?P<indent>\s*)switch \((?P<map_expr>map\(\)|map\(cage_base\))\.instance_type\(\)\) \{'
                switch_match = re.search(switch_pattern, updated_body)
                if switch_match is not None:
                    indent = switch_match.group("indent")
                    map_expr = switch_match.group("map_expr")
                    asm_block = (
                        "\n"
                        f'{indent}// Print array literal members instead of only "<AsmWasmData>"\n'
                        f"{indent}if ({map_expr}.instance_type() == ASM_WASM_DATA_TYPE) {{\n"
                        f'{indent}  os << "<ArrayBoilerplateDescription> ";\n'
                        f"{indent}  Cast<ArrayBoilerplateDescription>(*this)\n"
                        f"{indent}      ->constant_elements()\n"
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
                    if next_body != updated_body:
                        updated_body = next_body
                        changed = True

            case_injections = [
                (
                    r'(?P<indent>\s*)case FIXED_ARRAY_TYPE:\n(?P<body>.*?)(?P=indent)break;\n',
                    r'\g<indent>case FIXED_ARRAY_TYPE:\n'
                    r'\g<body>'
                    r'\g<indent>os << "\\nStart FixedArray\\n";\n'
                    r'\g<indent>Cast<FixedArray>(*this)->FixedArrayPrint(os);\n'
                    r'\g<indent>os << "\\nEnd FixedArray\\n";\n'
                    r'\g<indent>break;\n',
                    "Start FixedArray",
                ),
                (
                    r'(?P<indent>\s*)case OBJECT_BOILERPLATE_DESCRIPTION_TYPE:\n(?P<body>.*?)(?P=indent)break;\n',
                    r'\g<indent>case OBJECT_BOILERPLATE_DESCRIPTION_TYPE:\n'
                    r'\g<body>'
                    r'\g<indent>os << "\\nStart ObjectBoilerplateDescription\\n";\n'
                    r'\g<indent>Cast<ObjectBoilerplateDescription>(*this)\n'
                    r'\g<indent>    ->ObjectBoilerplateDescriptionPrint(os);\n'
                    r'\g<indent>os << "\\nEnd ObjectBoilerplateDescription\\n";\n'
                    r'\g<indent>break;\n',
                    "Start ObjectBoilerplateDescription",
                ),
                (
                    r'(?P<indent>\s*)case FIXED_DOUBLE_ARRAY_TYPE:\n(?P<body>.*?)(?P=indent)break;\n',
                    r'\g<indent>case FIXED_DOUBLE_ARRAY_TYPE:\n'
                    r'\g<body>'
                    r'\g<indent>os << "\\nStart FixedDoubleArray\\n";\n'
                    r'\g<indent>Cast<FixedDoubleArray>(*this)->FixedDoubleArrayPrint(os);\n'
                    r'\g<indent>os << "\\nEnd FixedDoubleArray\\n";\n'
                    r'\g<indent>break;\n',
                    "Start FixedDoubleArray",
                ),
                (
                    r'(?P<case_indent>\s*)case SHARED_FUNCTION_INFO_TYPE:(?P<body>.*?)(?P<break_indent>\s*)break;\n',
                    r'\g<case_indent>case SHARED_FUNCTION_INFO_TYPE:\g<body>'
                    r'\g<break_indent>os << "\\nStart SharedFunctionInfo\\n";\n'
                    r'\g<break_indent>Cast<SharedFunctionInfo>(*this)->SharedFunctionInfoPrint(os);\n'
                    r'\g<break_indent>os << "\\nEnd SharedFunctionInfo\\n";\n'
                    r'\g<break_indent>break;\n',
                    "Start SharedFunctionInfo",
                ),
                (
                    r'(?P<indent>\s*)(?P<call>[^\n]*SharedFunctionInfoPrint\(os\);)\n',
                    r'\g<indent>os << "\\nStart SharedFunctionInfo\\n";\n'
                    r'\g<indent>\g<call>\n'
                    r'\g<indent>os << "\\nEnd SharedFunctionInfo\\n";\n',
                    "Start SharedFunctionInfo",
                ),
            ]

            for pattern, replacement, marker in case_injections:
                if marker in updated_body:
                    continue
                next_body = re.sub(pattern, replacement, updated_body, count=1, flags=re.DOTALL)
                if next_body != updated_body:
                    updated_body = next_body
                    changed = True

            if "Start SharedFunctionInfo" not in updated_body and "SharedFunctionInfoPrint(os);" not in updated_body:
                self.log(f"[SEMANTIC][objects.cc] reason=shared_function_info_call_not_found file={file_path}")

            if not changed:
                return "already_target_state" if already_done else "not_matched_unverified"

            new_content = content[:body_start] + updated_body + content[body_end:]
            if not self._write_file(file_path, new_content):
                return "failed"

            updated = self._read_file(file_path)
            if updated is None:
                return "failed"
            updated_range = self._find_function_body_regex(
                updated,
                r"void\s+HeapObject::HeapObjectShortPrint\s*\(\s*std::ostream\s*&\s*os\s*\)",
            )
            if updated_range is None:
                return "failed"
            updated_body = updated[updated_range[0]:updated_range[1]]
            success = all(marker in updated_body for marker in required_markers)
            if not success:
                missing = [marker for marker in required_markers if marker not in updated_body]
                self.log(f"[SEMANTIC][objects.cc] reason=post_verify_missing required={missing} file={file_path}")
                return "failed"
            return "applied_now"

        return "not_matched_unverified"

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
