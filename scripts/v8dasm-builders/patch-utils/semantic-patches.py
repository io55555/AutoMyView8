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

    def _contains_in_order(self, content: str, markers: list[str]) -> bool:
        next_index = 0
        for marker in markers:
            next_index = content.find(marker, next_index)
            if next_index == -1:
                return False
            next_index += len(marker)
        return True

    def _find_first_marker(self, content: str, markers: list[str]) -> int:
        positions = [content.find(marker) for marker in markers if marker in content]
        return min(positions) if positions else -1

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

        deserialize_signature = r"CodeSerializer::Deserialize\s*\("
        finish_signature = r"CodeSerializer::FinishOffThreadDeserialize\s*\("
        deserialize_range = self._find_function_body_regex(content, deserialize_signature)
        if deserialize_range is None:
            self.log("[SEMANTIC][code-serializer.cc] reason=deserialize_signature_not_found")
            return "not_matched_unverified"

        print_markers = [
            'std::cout << "\\nStart SharedFunctionInfo\\n";',
            'result->SharedFunctionInfoPrint(std::cout);',
            'std::cout << "\\nEnd SharedFunctionInfo\\n";',
            'std::cout << std::flush;',
        ]

        def function_has_print_block(candidate_content: str, signature_pattern: str) -> bool | None:
            function_range = self._find_function_body_regex(candidate_content, signature_pattern)
            if function_range is None:
                return None
            function_body = candidate_content[function_range[0]:function_range[1]]
            return self._contains_in_order(function_body, print_markers)

        def insert_print_block(
            candidate_content: str,
            signature_pattern: str,
            anchor_patterns: list[str],
            missing_anchor_reason: str,
        ) -> tuple[str, bool, bool]:
            function_range = self._find_function_body_regex(candidate_content, signature_pattern)
            if function_range is None:
                return candidate_content, False, False

            function_body = candidate_content[function_range[0]:function_range[1]]
            if self._contains_in_order(function_body, print_markers):
                return candidate_content, False, True

            print_block = (
                "\n"
                '  std::cout << "\\nStart SharedFunctionInfo\\n";\n'
                '  result->SharedFunctionInfoPrint(std::cout);\n'
                '  std::cout << "\\nEnd SharedFunctionInfo\\n";\n'
                '  std::cout << std::flush;\n'
            )

            next_body = function_body
            for anchor_pattern in anchor_patterns:
                replaced_body = re.sub(
                    anchor_pattern,
                    lambda match: print_block + match.group(1),
                    next_body,
                    count=1,
                    flags=re.MULTILINE,
                )
                if replaced_body != next_body:
                    updated_content = (
                        candidate_content[:function_range[0]]
                        + replaced_body
                        + candidate_content[function_range[1]:]
                    )
                    updated_range = self._find_function_body_regex(updated_content, signature_pattern)
                    if updated_range is None:
                        return updated_content, True, False
                    updated_body = updated_content[updated_range[0]:updated_range[1]]
                    return (
                        updated_content,
                        True,
                        self._contains_in_order(updated_body, print_markers),
                    )

            self.log(f"[SEMANTIC][code-serializer.cc] reason={missing_anchor_reason}")
            return candidate_content, False, False

        has_deserialize_print_block = function_has_print_block(content, deserialize_signature)
        has_finish_print_block = function_has_print_block(content, finish_signature)
        has_sanity_override = "return SerializedCodeSanityCheckResult::kSuccess;" in content
        finish_path_supported = has_finish_print_block is not None
        target_reached = has_deserialize_print_block and has_sanity_override

        if self.verify_only:
            return "already_target_state" if target_reached else "not_matched_unverified"

        updated_content = content
        changed = False

        if not has_deserialize_print_block:
            updated_content, inserted, success = insert_print_block(
                updated_content,
                deserialize_signature,
                [
                    r"(^\s*BaselineBatchCompileIfSparkplugCompiled\s*\(\s*isolate\s*,)",
                    r"(^\s*script->set_deserialized\s*\(\s*true\s*\);\s*$)",
                    r"(^\s*FinalizeDeserialization\s*\(.*$)",
                ],
                "deserialize_print_anchor_not_found",
            )
            if not success:
                return "not_matched_unverified"
            changed = changed or inserted

        if has_finish_print_block is False:
            updated_content, inserted, success = insert_print_block(
                updated_content,
                finish_signature,
                [
                    r"(^\s*DCHECK\s*\(\s*!off_thread_data\.background_merge_task_has_pending_foreground_work.*$)",
                    r"(^\s*return\s+scope\.CloseAndEscape\s*\(\s*result\s*\)\s*;\s*$)",
                    r"(^\s*FinalizeDeserialization\s*\(.*$)",
                ],
                "finish_print_anchor_not_found",
            )
            if success:
                changed = changed or inserted
            elif finish_path_supported:
                self.log("[SEMANTIC][code-serializer.cc] optional_finish_print_block_skipped=true")

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
        updated_deserialize = function_has_print_block(updated, deserialize_signature)
        updated_finish = function_has_print_block(updated, finish_signature)
        updated_finish_supported = updated_finish is not None
        success = updated_deserialize and "return SerializedCodeSanityCheckResult::kSuccess;" in updated
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
        bytecode_markers = [
            'os << "\\nStart BytecodeArray\\n";',
            'GetActiveBytecodeArray(isolate)->Disassemble(os);',
            'os << "\\nEnd BytecodeArray\\n";',
            'os << std::flush;',
        ]
        has_bytecode_block = self._contains_in_order(sfi_body, bytecode_markers)
        bytecode_block = (
            '  os << "\\nStart BytecodeArray\\n";\n'
            '  GetActiveBytecodeArray(isolate)->Disassemble(os);\n'
            '  os << "\\nEnd BytecodeArray\\n";\n'
            '  os << std::flush;\n'
        )

        if not has_bytecode_block:
            source_pattern = r"^\s*PrintSourceCode\(os\);\n"
            next_body = re.sub(
                source_pattern,
                "",
                sfi_body,
                count=1,
                flags=re.MULTILINE,
            )
            if next_body != sfi_body and '  os << "\\n";\n' in next_body:
                next_body = next_body.replace('  os << "\\n";\n', '  os << "\\n";\n' + bytecode_block, 1)
            if next_body == sfi_body:
                fallback_anchors = [
                    '  os << "\\n";\n',
                    '  os << "\\n - script: " << Brief(script());\n',
                    '  os << "\\n - function token position: " << function_token_position();\n',
                ]
                next_body = sfi_body
                for anchor in fallback_anchors:
                    if anchor in next_body:
                        next_body = next_body.replace(anchor, anchor + bytecode_block, 1)
                        break
            if next_body != sfi_body:
                updated_content = updated_content[:sfi_range[0]] + next_body + updated_content[sfi_range[1]:]
                changed = True
                sfi_body = next_body
                source_removed = "PrintSourceCode(os);" not in sfi_body
                has_bytecode_block = self._contains_in_order(sfi_body, bytecode_markers)

        if not source_removed:
            source_pattern = r"^\s*PrintSourceCode\(os\);\n"
            next_body = re.sub(source_pattern, "", sfi_body, count=1, flags=re.MULTILINE)
            if next_body != sfi_body:
                updated_content = updated_content[:sfi_range[0]] + next_body + updated_content[sfi_range[1]:]
                changed = True
                sfi_body = next_body
                source_removed = "PrintSourceCode(os);" not in sfi_body

        printer_wrappers = [
            (
                "void FixedArray::FixedArrayPrint(std::ostream& os)",
                "Start FixedArray",
                '  os << "Start FixedArray\\n";\n',
                '  os << "\\nEnd FixedArray\\n";\n',
            ),
            (
                "void ObjectBoilerplateDescription::ObjectBoilerplateDescriptionPrint",
                "Start ObjectBoilerplateDescription",
                '  os << "Start ObjectBoilerplateDescription\\n";\n',
                '  os << "\\nEnd ObjectBoilerplateDescription\\n";\n',
            ),
            (
                "void FixedDoubleArray::FixedDoubleArrayPrint(std::ostream& os)",
                "Start FixedDoubleArray",
                '  os << "Start FixedDoubleArray\\n";\n',
                '  os << "\\nEnd FixedDoubleArray\\n";\n',
            ),
        ]

        for signature, marker, prefix, suffix in printer_wrappers:
            if marker in updated_content:
                continue
            body_range = self._find_function_body(updated_content, signature)
            if body_range is None:
                body_range = self._find_function_body_regex(updated_content, re.escape(signature))
            if body_range is None:
                continue
            body = updated_content[body_range[0]:body_range[1]]
            next_body = prefix + body + suffix
            updated_content = updated_content[:body_range[0]] + next_body + updated_content[body_range[1]:]
            changed = True

        optional_markers = [
            "Start FixedArray",
            "Start ObjectBoilerplateDescription",
            "Start FixedDoubleArray",
        ]

        def printer_success(candidate_content: str) -> bool:
            candidate_sfi_range = self._find_function_body(candidate_content, sfi_signature)
            if candidate_sfi_range is None:
                return False
            candidate_sfi_body = candidate_content[candidate_sfi_range[0]:candidate_sfi_range[1]]
            return (
                "PrintSourceCode(os);" not in candidate_sfi_body
                and self._contains_in_order(candidate_sfi_body, bytecode_markers)
            )

        if not has_bytecode_block:
            self.log("[SEMANTIC][objects-printer.cc] reason=bytecode_anchor_not_found")
        if not source_removed:
            self.log("[SEMANTIC][objects-printer.cc] reason=print_sourcecode_not_removed")

        optional_missing = [marker for marker in optional_markers if marker not in updated_content]
        if optional_missing:
            self.log(
                "[SEMANTIC][objects-printer.cc] optional_markers_missing=" + ",".join(optional_missing)
            )

        if self.verify_only:
            return "already_target_state" if printer_success(updated_content) else "not_matched_unverified"

        if not changed:
            return "already_target_state" if printer_success(updated_content) else "not_matched_unverified"

        if not self._write_file(file_path, updated_content):
            return "failed"

        updated = self._read_file(file_path)
        if updated is None:
            return "failed"

        return "applied_now" if printer_success(updated) else "failed"

    def patch_compiler_cc(self) -> str:
        file_path = self.v8_dir / "src/codegen/compiler.cc"
        content = self._read_file(file_path)
        if content is None:
            return "failed"

        if "BackgroundDeserializeTask::Finish" not in content:
            self.log("[SEMANTIC][compiler.cc] reason=finish_signature_not_found")
            return "not_matched_unverified"

        self.log("[SEMANTIC][compiler.cc] reason=disabled_use_code_serializer_finish_path")
        return "not_matched_unverified"

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
                return "already_target_state" if has_asm_block else "not_matched_unverified"

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

        return "not_matched_unverified"

    def apply_all(self) -> bool:
        self.log(f"[SEMANTIC] START verify_only={str(self.verify_only).lower()} v8_dir={self.v8_dir}")
        patches = [
            ("objects-printer.cc", self.patch_objects_printer_cc, False),
            ("objects.cc", self.patch_objects_cc, True),
            ("string.cc", self.patch_string_cc, False),
            ("deserializer.cc", self.patch_deserializer_cc, False),
            ("code-serializer.cc", self.patch_code_serializer_cc, False),
            ("compiler.cc", self.patch_compiler_cc, True),
        ]
        allowed_success = {"applied_now", "already_target_state"}
        optional_allowed = allowed_success | {"not_matched_unverified"}

        for name, patch_func, optional in patches:
            self.log(f"[SEMANTIC] APPLY file={name}")
            try:
                status = patch_func()
            except Exception as exc:
                self.log(f"[SEMANTIC] ERROR exception file={name} error={exc}")
                status = "failed"
            self.record_result(name, status)
            if optional and status == "not_matched_unverified":
                self.log(f"[SEMANTIC] OPTIONAL file={name} treated_as=success")

        success = all(
            status in (optional_allowed if optional else allowed_success)
            for name, _, optional in patches
            for status in [self.results[name]]
        )
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
