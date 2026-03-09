{
  "targets": [{
    "target_name": "macos_accessibility",
    "sources": ["accessibility_bridge.mm"],
    "include_dirs": ["<!@(node -p \"require('node-addon-api').include\")"],
    "defines": ["NAPI_DISABLE_CPP_EXCEPTIONS"],
    "conditions": [
      ["OS=='mac'", {
        "xcode_settings": {
          "CLANG_ENABLE_OBJC_ARC": "YES",
          "OTHER_CPLUSPLUSFLAGS": ["-std=c++20", "-ObjC++"],
          "OTHER_LDFLAGS": ["-framework Cocoa", "-framework AppKit", "-framework ApplicationServices"]
        }
      }]
    ]
  }]
}
