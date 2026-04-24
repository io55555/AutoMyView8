#include <algorithm>
#include <fstream>
#include <iostream>
#include <memory>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

#include "v8.h"
#include "libplatform/libplatform.h"

using namespace v8;

static Isolate* isolate = nullptr;

namespace {
constexpr char kDefaultDummySource[] = "\"\xE0\xB2\xA0_\xE0\xB2\xA0\"";
constexpr char kZeroWidthSpaceUtf8[] = "\xE2\x80\x8B";

struct LoadAttempt {
  const char* label;
  size_t patch_offset;
  size_t patch_length;
  bool use_source_hash_dummy;
};
}  // namespace

// Compatibility with v8 versions that have different ScriptOrigin constructors
template <typename... Args>
ScriptOrigin CreateScriptOrigin(Args&&... args) {
  if constexpr (std::is_constructible_v<ScriptOrigin, Isolate*, Local<String>>) {
      return ScriptOrigin(isolate, std::forward<Args>(args)...);
  } else {
      return ScriptOrigin(std::forward<Args>(args)...);
  }
}

static uint32_t readLittleEndianUint32(const uint8_t* data) {
  return static_cast<uint32_t>(data[0]) |
         (static_cast<uint32_t>(data[1]) << 8) |
         (static_cast<uint32_t>(data[2]) << 16) |
         (static_cast<uint32_t>(data[3]) << 24);
}

static uint32_t readSourceHash(const std::vector<uint8_t>& bytecode) {
  if (bytecode.size() < 12) {
    return 0;
  }
  return readLittleEndianUint32(bytecode.data() + 8);
}

static std::string buildSourceHashDummySource(uint32_t source_hash) {
  if (source_hash <= 1) {
    return "";
  }

  std::string dummy_source = "\"";
  dummy_source.reserve(2 + static_cast<size_t>(source_hash - 2) * 3);
  for (uint32_t index = 0; index < source_hash - 2; ++index) {
    dummy_source += kZeroWidthSpaceUtf8;
  }
  dummy_source += "\"";
  return dummy_source;
}

static bool createUtf8String(const std::string& text, Local<String>* out) {
  return String::NewFromUtf8(isolate, text.c_str(), NewStringType::kNormal,
                             static_cast<int>(text.size()))
      .ToLocal(out);
}

static bool createDummyBytecode(const std::string& source_code,
                              std::vector<uint8_t>* out) {
  Local<String> source_text;
  if (!createUtf8String(source_code, &source_text)) {
    return false;
  }

  ScriptOrigin origin = CreateScriptOrigin(String::NewFromUtf8Literal(isolate, "code.jsc"));
  ScriptCompiler::Source source(source_text, origin);
  TryCatch try_catch(isolate);

  Local<UnboundScript> script;
  if (!ScriptCompiler::CompileUnboundScript(isolate, &source).ToLocal(&script)) {
    if (try_catch.HasCaught()) {
      String::Utf8Value exception(isolate, try_catch.Exception());
      std::cerr << "[v8dasm] Failed to compile dummy source: "
                << (*exception ? *exception : "<string conversion failed>")
                << std::endl;
    }
    return false;
  }

  auto cached_data = ScriptCompiler::CreateCodeCache(script);
  if (!cached_data || cached_data->length <= 0) {
    return false;
  }

  out->assign(cached_data->data, cached_data->data + cached_data->length);
  return true;
}

static bool applyCachedHeaderPatch(std::vector<uint8_t>* bytecode,
                                 const std::string& source_code,
                                 size_t patch_offset,
                                 size_t patch_length) {
  if (patch_length == 0) {
    return true;
  }
  if (bytecode->size() < patch_offset + patch_length) {
    return false;
  }

  std::vector<uint8_t> dummy_bytecode;
  if (!createDummyBytecode(source_code, &dummy_bytecode) ||
      dummy_bytecode.size() < patch_offset + patch_length) {
    return false;
  }

  std::copy(dummy_bytecode.begin() + static_cast<std::ptrdiff_t>(patch_offset),
            dummy_bytecode.begin() + static_cast<std::ptrdiff_t>(patch_offset + patch_length),
            bytecode->begin() + static_cast<std::ptrdiff_t>(patch_offset));
  return true;
}

static bool tryLoadBytecode(const std::vector<uint8_t>& original_bytecode,
                            const LoadAttempt& attempt) {
  std::vector<uint8_t> bytecode = original_bytecode;
  std::cerr << "[v8dasm] trying attempt=" << attempt.label
            << " patch_offset=" << attempt.patch_offset
            << " patch_length=" << attempt.patch_length
            << " use_source_hash_dummy=" << (attempt.use_source_hash_dummy ? "true" : "false")
            << std::endl;

  std::string source_text = kDefaultDummySource;
  if (attempt.use_source_hash_dummy) {
    source_text = buildSourceHashDummySource(readSourceHash(bytecode));
    if (source_text.empty()) {
      std::cerr << "[v8dasm] " << attempt.label
                << ": source hash dummy code is empty" << std::endl;
      return false;
    }
  }

  if (!applyCachedHeaderPatch(&bytecode, source_text, attempt.patch_offset,
                              attempt.patch_length)) {
    std::cerr << "[v8dasm] " << attempt.label << ": failed to patch cached data header"
              << std::endl;
    return false;
  }
  if (attempt.patch_length != 0) {
    std::cerr << "[v8dasm] " << attempt.label << ": patched cached data bytes ["
              << attempt.patch_offset << ", "
              << (attempt.patch_offset + attempt.patch_length - 1) << "]"
              << std::endl;
  }

  Local<String> source_string;
  if (!createUtf8String(source_text, &source_string)) {
    std::cerr << "[v8dasm] " << attempt.label << ": failed to create source string"
              << std::endl;
    return false;
  }

  ScriptCompiler::CachedData* cached_data =
      new ScriptCompiler::CachedData(bytecode.data(), static_cast<int>(bytecode.size()));
  ScriptOrigin origin = CreateScriptOrigin(String::NewFromUtf8Literal(isolate, "code.jsc"));
  ScriptCompiler::Source source(source_string, origin, cached_data);
  TryCatch try_catch(isolate);
  MaybeLocal<UnboundScript> script = ScriptCompiler::CompileUnboundScript(
      isolate, &source, ScriptCompiler::kConsumeCodeCache);

  if (script.IsEmpty()) {
    std::cerr << "[v8dasm] " << attempt.label
              << ": CompileUnboundScript returned empty" << std::endl;
    if (cached_data->rejected) {
      std::cerr << "[v8dasm] " << attempt.label << ": CachedData was rejected"
                << std::endl;
    }
    if (try_catch.HasCaught()) {
      String::Utf8Value exception(isolate, try_catch.Exception());
      std::cerr << "[v8dasm] " << attempt.label << ": Exception: "
                << (*exception ? *exception : "<string conversion failed>")
                << std::endl;
    }
    return false;
  }

  if (cached_data->rejected) {
    std::cerr << "[v8dasm] " << attempt.label
              << ": CachedData was rejected after compile" << std::endl;
    return false;
  }

  Local<UnboundScript> resolved_script;
  if (!script.ToLocal(&resolved_script)) {
    std::cerr << "[v8dasm] " << attempt.label
              << ": failed to materialize unbound script" << std::endl;
    return false;
  }

  std::cerr << "[v8dasm] " << attempt.label << ": cache accepted" << std::endl;
  (void)resolved_script;
  return true;
}

static bool loadBytecode(uint8_t* bytecodeBuffer, int length) {
  std::vector<uint8_t> original_bytecode(bytecodeBuffer, bytecodeBuffer + length);
  const std::vector<LoadAttempt> attempts = {
      {"default_dummy_source", 0, 0, false},
      {"source_hash_dummy", 0, 0, true},
      {"patch_words_12_19_source_hash", 12, 8, true},
      {"patch_words_8_19_source_hash", 8, 12, true},
      {"patch_words_12_19_default_dummy", 12, 8, false},
      {"patch_words_8_19_default_dummy", 8, 12, false},
  };

  for (const LoadAttempt& attempt : attempts) {
    if (tryLoadBytecode(original_bytecode, attempt)) {
      return true;
    }
  }

  return false;
}

static void readAllBytes(const std::string& file, std::vector<char>& buffer) {
  std::ifstream infile(file, std::ios::binary);

  infile.seekg(0, infile.end);
  size_t length = infile.tellg();
  infile.seekg(0, infile.beg);

  if (length > 0) {
    buffer.resize(length);
    infile.read(&buffer[0], length);
  }
}

int main(int argc, char* argv[]) {
  if (argc < 2) {
    std::cerr << "Usage: v8dasm <input.jsc>" << std::endl;
    return 1;
  }

  V8::SetFlagsFromString("--no-lazy --no-flush-bytecode");

  V8::InitializeICU();
  std::unique_ptr<Platform> platform = platform::NewDefaultPlatform();
  V8::InitializePlatform(platform.get());
  V8::Initialize();

  Isolate::CreateParams create_params;
  create_params.array_buffer_allocator =
      ArrayBuffer::Allocator::NewDefaultAllocator();

  isolate = Isolate::New(create_params);
  Isolate::Scope isolate_scope(isolate);
  HandleScope handle_scope(isolate);
  Local<v8::Context> context = Context::New(isolate);
  Context::Scope context_scope(context);

  std::vector<char> data;
  readAllBytes(argv[1], data);
  if (data.empty()) {
    std::cerr << "[v8dasm] Input file is empty or unreadable: " << argv[1] << std::endl;
    return 1;
  }

  return loadBytecode(reinterpret_cast<uint8_t*>(data.data()), static_cast<int>(data.size())) ? 0 : 1;
}
