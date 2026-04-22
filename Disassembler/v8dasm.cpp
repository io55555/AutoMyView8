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

// Compatibility with v8 versions that have different ScriptOrigin constructors
template <typename... Args>
ScriptOrigin CreateScriptOrigin(Args&&... args) {
  if constexpr (std::is_constructible_v<ScriptOrigin, Isolate*, Local<String>>) {
      return ScriptOrigin(isolate, std::forward<Args>(args)...);
  } else {
      return ScriptOrigin(std::forward<Args>(args)...);
  }
}

static bool loadBytecode(uint8_t* bytecodeBuffer, int length) {
  // Load code into code cache.
  ScriptCompiler::CachedData* cached_data =
      new ScriptCompiler::CachedData(bytecodeBuffer, length);

  // Create dummy source.
  ScriptOrigin origin = CreateScriptOrigin(String::NewFromUtf8Literal(isolate, "code.jsc"));

  ScriptCompiler::Source source(String::NewFromUtf8Literal(isolate, "\"ಠ_ಠ\""),
                                origin, cached_data);

  TryCatch try_catch(isolate);
  MaybeLocal<UnboundScript> script = ScriptCompiler::CompileUnboundScript(
      isolate, &source, ScriptCompiler::kConsumeCodeCache);

  if (script.IsEmpty()) {
    std::cerr << "[v8dasm] CompileUnboundScript returned empty" << std::endl;
    if (cached_data->rejected) {
      std::cerr << "[v8dasm] CachedData was rejected" << std::endl;
    }
    if (try_catch.HasCaught()) {
      String::Utf8Value exception(isolate, try_catch.Exception());
      std::cerr << "[v8dasm] Exception: "
                << (*exception ? *exception : "<string conversion failed>")
                << std::endl;
    }
    return false;
  }

  if (cached_data->rejected) {
    std::cerr << "[v8dasm] CachedData was rejected after compile" << std::endl;
    return false;
  }

  return true;
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
