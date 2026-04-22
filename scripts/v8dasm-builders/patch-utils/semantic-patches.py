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

        updated_content = content
        changed = False

        sfi_signature = "void SharedFunctionInfo::SharedFunctionInfoPrint(std::ostream& os)"
        sfi_range = self._find_function_body(content, sfi_signature)
        if sfi_range is None:
            return "not_matched_unverified"

        sfi_body = updated_content[sfi_range[0]:sfi_range[1]]
        source_removed = "PrintSourceCode(os);" not in sfi_body
        has_bytecode_block = "Start BytecodeArray" in sfi_body and "GetActiveBytecodeArray(isolate)->Disassemble(os);" in sfi_body

        if not source_removed:
            source_pattern = r"\s*PrintSourceCode\(os\);\n"
            next_body = re.sub(source_pattern, "", sfi_body, count=1)
            if next_body != sfi_body:
                updated_content = updated_content[:sfi_range[0]] + next_body + updated_content[sfi_range[1]:]
                changed = True
                sfi_body = next_body

        if not has_bytecode_block:
            tail_anchor = '  os << "\\n";\n'
            bytecode_block = (
                '  os << "\\nStart BytecodeArray\\n";\n'
                '  GetActiveBytecodeArray(isolate)->Disassemble(os);\n'
                '  os << "\\nEnd BytecodeArray\\n";\n'
                '  os << std::flush;\n'
            )
            if tail_anchor in sfi_body:
                next_body = sfi_body.replace(tail_anchor, tail_anchor + bytecode_block, 1)
                if next_body != sfi_body:
                    updated_content = updated_content[:sfi_range[0]] + next_body + updated_content[sfi_range[1]:]
                    changed = True
                    sfi_body = next_body

        printer_patches = [
            (
                "void FixedArray::FixedArrayPrint(std::ostream& os)",
                'PrintFixedArrayWithHeader(os, this, "FixedArray");\n',
                (
                    '  os << "Start FixedArray\\n";\n'
                    '  PrintFixedArrayWithHeader(os, this, "FixedArray");\n'
                    '  os << "\\nEnd FixedArray\\n";\n'
                ),
                "Start FixedArray",
            ),
            (
                "void ObjectBoilerplateDescription::ObjectBoilerplateDescriptionPrint",
                '  os << "\\n - elements:";\n',
                (
                    '  os << "Start ObjectBoilerplateDescription\\n";\n'
                    '  os << "\\n - elements:";\n'
                ),
                "Start ObjectBoilerplateDescription",
            ),
            (
                "void FixedDoubleArray::FixedDoubleArrayPrint(std::ostream& os)",
                '  DoPrintElements<FixedDoubleArray>(os, this, length());\n',
                (
                    '  os << "Start FixedDoubleArray\\n";\n'
                    '  DoPrintElements<FixedDoubleArray>(os, this, length());\n'
                    '  os << "\\nEnd FixedDoubleArray\\n";\n'
                ),
                "Start FixedDoubleArray",
            ),
        ]

        for signature, anchor, replacement, marker in printer_patches:
            if marker in updated_content:
                continue
            body_range = self._find_function_body(updated_content, signature)
            if body_range is None:
                body_range = self._find_function_body_regex(updated_content, re.escape(signature))
            if body_range is None:
                continue
            body = updated_content[body_range[0]:body_range[1]]
            if anchor not in body:
                continue
            next_body = body.replace(anchor, replacement, 1)
            if next_body != body:
                updated_content = updated_content[:body_range[0]] + next_body + updated_content[body_range[1]:]
                changed = True

        if self.verify_only:
            required = [
                "Start BytecodeArray",
                "GetActiveBytecodeArray(isolate)->Disassemble(os);",
                "Start FixedArray",
                "Start ObjectBoilerplateDescription",
                "Start FixedDoubleArray",
            ]
            success = "PrintSourceCode(os);" not in updated_content and all(marker in updated_content for marker in required)
            return "already_target_state" if success else "not_matched_unverified"

        if not changed:
            required = [
                "Start BytecodeArray",
                "GetActiveBytecodeArray(isolate)->Disassemble(os);",
                "Start FixedArray",
                "Start ObjectBoilerplateDescription",
                "Start FixedDoubleArray",
            ]
            success = "PrintSourceCode(os);" not in updated_content and all(marker in updated_content for marker in required)
            return "already_target_state" if success else "not_matched_unverified"

        if not self._write_file(file_path, updated_content):
            return "failed"

        updated = self._read_file(file_path)
        if updated is None:
            return "failed"

        required = [
            "Start BytecodeArray",
            "GetActiveBytecodeArray(isolate)->Disassemble(os);",
            "Start FixedArray",
            "Start ObjectBoilerplateDescription",
            "Start FixedDoubleArray",
        ]
        success = "PrintSourceCode(os);" not in updated and all(marker in updated for marker in required)
        return "applied_now" if success else "failed"

    def patch_objects_cc(self) -> str:
        candidate_files = [
            self.v8_dir / "src/objects/objects.cc",
            self.v8_dir / "src/diagnostics/objects-printer.cc",
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
            has_asm_block = "ASM_WASM_DATA_TYPE" in body

            if self.verify_only:
                return "already_target_state"

            if has_asm_block:
                return "already_target_state"

            switch_pattern = r'(\n)(?P<indent>\s*)switch \((?P<map_expr>map\(\)|map\(cage_base\))\.instance_type\(\)\) \{'
            switch_match = re.search(switch_pattern, body)
            if switch_match is None:
                return "not_matched_unverified"

            indent = switch_match.group("indent")
            map_expr = switch_match.group("map_expr")
            asm_block = (
                "\n"
                f'{indent}// Print array literal members instead of only "<AsmWasmData>"\n'
                f"{indent}if ({map_expr}.instance_type() == ASM_WASM_DATA_TYPE) {{\n"
                f'{indent}  os << "<ArrayBoilerplateDescription> ";\n'
                f"{indent}  Cast<ArrayBoilerplateDescription>(*this)\n"
                f"{indent}      ->constant_elements()\n"
                f"{indent}      ->HeapObjectShortPrint(os);\n"
                f"{indent}  return;\n"
                f"{indent}}}\n\n"
            )
            updated_body = re.sub(
                switch_pattern,
                r'\1' + asm_block + indent + f'switch ({map_expr}.instance_type()) {{',
                body,
                count=1,
            )
            if updated_body == body:
                return "not_matched_unverified"

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
            return "applied_now" if "ASM_WASM_DATA_TYPE" in updated_body else "failed"

        return "already_target_state"

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
