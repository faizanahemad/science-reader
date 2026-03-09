/**
 * accessibility_bridge.mm — Native N-API addon for macOS Accessibility APIs.
 *
 * Provides synchronous accessors for the frontmost application, window titles,
 * selected text, focused UI element info, browser URLs, Finder selection,
 * VS Code file paths, and accessibility permission checks.
 *
 * Exports:
 *   getActiveApp()                → { name, bundleId, pid }
 *   getWindowTitle()              → string
 *   getSelectedText()             → string | null
 *   getFocusedElementInfo()       → { role, title, value } | null
 *   getBrowserURL()               → string | null
 *   getFinderSelection()          → string[]
 *   getVSCodeFilePath()           → string | null
 *   isAccessibilityEnabled()      → boolean
 *   requestAccessibilityAccess()  → boolean
 */

#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>
#include <napi.h>
#include <string>

// ── Helpers ──────────────────────────────────────────────────────────

static std::string NSStringToStdString(NSString *str) {
  if (!str) return "";
  return std::string([str UTF8String]);
}

static napi_value CreateStringOrNull(napi_env env, const std::string &str) {
  if (str.empty()) {
    napi_value null_val;
    napi_get_null(env, &null_val);
    return null_val;
  }
  napi_value result;
  napi_create_string_utf8(env, str.c_str(), str.size(), &result);
  return result;
}

// ── AX helpers ───────────────────────────────────────────────────────

static std::string AXCopyStringAttribute(AXUIElementRef element, CFStringRef attribute) {
  CFTypeRef value = nullptr;
  AXError err = AXUIElementCopyAttributeValue(element, attribute, &value);
  if (err != kAXErrorSuccess || !value) return "";

  std::string result;
  if (CFGetTypeID(value) == CFStringGetTypeID()) {
    NSString *nsStr = (__bridge NSString *)value;
    result = NSStringToStdString(nsStr);
  }
  CFRelease(value);
  return result;
}

static AXUIElementRef AXCopyElementAttribute(AXUIElementRef element, CFStringRef attribute) {
  CFTypeRef value = nullptr;
  AXError err = AXUIElementCopyAttributeValue(element, attribute, &value);
  if (err != kAXErrorSuccess || !value) return nullptr;
  // value is an AXUIElementRef; caller must CFRelease
  return (AXUIElementRef)value;
}

// ── getActiveApp() ───────────────────────────────────────────────────

static napi_value GetActiveApp(napi_env env, napi_callback_info /*info*/) {
  NSRunningApplication *app = [[NSWorkspace sharedWorkspace] frontmostApplication];
  if (!app) {
    napi_value null_val;
    napi_get_null(env, &null_val);
    return null_val;
  }

  std::string name = NSStringToStdString([app localizedName]);
  std::string bundleId = NSStringToStdString([app bundleIdentifier]);
  pid_t pid = [app processIdentifier];

  napi_value obj;
  napi_create_object(env, &obj);

  napi_value name_val, bundle_val, pid_val;
  napi_create_string_utf8(env, name.c_str(), name.size(), &name_val);
  napi_create_string_utf8(env, bundleId.c_str(), bundleId.size(), &bundle_val);
  napi_create_int32(env, pid, &pid_val);

  napi_set_named_property(env, obj, "name", name_val);
  napi_set_named_property(env, obj, "bundleId", bundle_val);
  napi_set_named_property(env, obj, "pid", pid_val);

  return obj;
}

// ── getWindowTitle() ─────────────────────────────────────────────────

static napi_value GetWindowTitle(napi_env env, napi_callback_info /*info*/) {
  NSRunningApplication *app = [[NSWorkspace sharedWorkspace] frontmostApplication];
  if (!app) {
    napi_value null_val;
    napi_get_null(env, &null_val);
    return null_val;
  }

  pid_t pid = [app processIdentifier];
  AXUIElementRef axApp = AXUIElementCreateApplication(pid);
  if (!axApp) {
    napi_value null_val;
    napi_get_null(env, &null_val);
    return null_val;
  }

  AXUIElementRef window = AXCopyElementAttribute(axApp, kAXFocusedWindowAttribute);
  CFRelease(axApp);

  if (!window) {
    napi_value null_val;
    napi_get_null(env, &null_val);
    return null_val;
  }

  std::string title = AXCopyStringAttribute(window, kAXTitleAttribute);
  CFRelease(window);

  return CreateStringOrNull(env, title);
}

// ── getSelectedText() ────────────────────────────────────────────────

static napi_value GetSelectedText(napi_env env, napi_callback_info /*info*/) {
  NSRunningApplication *app = [[NSWorkspace sharedWorkspace] frontmostApplication];
  if (!app) {
    napi_value null_val;
    napi_get_null(env, &null_val);
    return null_val;
  }

  pid_t pid = [app processIdentifier];
  AXUIElementRef axApp = AXUIElementCreateApplication(pid);
  if (!axApp) {
    napi_value null_val;
    napi_get_null(env, &null_val);
    return null_val;
  }

  AXUIElementRef focusedElement = AXCopyElementAttribute(axApp, kAXFocusedUIElementAttribute);
  CFRelease(axApp);

  if (!focusedElement) {
    napi_value null_val;
    napi_get_null(env, &null_val);
    return null_val;
  }

  // Try direct kAXSelectedTextAttribute first
  std::string selectedText = AXCopyStringAttribute(focusedElement, kAXSelectedTextAttribute);

  // Fallback: use kAXSelectedTextRangeAttribute + kAXValueAttribute
  if (selectedText.empty()) {
    CFTypeRef rangeRef = nullptr;
    AXError err = AXUIElementCopyAttributeValue(focusedElement, kAXSelectedTextRangeAttribute, &rangeRef);
    if (err == kAXErrorSuccess && rangeRef) {
      CFRange range;
      if (AXValueGetValue((AXValueRef)rangeRef, (AXValueType)kAXValueCFRangeType, &range) && range.length > 0) {
        std::string fullValue = AXCopyStringAttribute(focusedElement, kAXValueAttribute);
        if (!fullValue.empty() && (size_t)(range.location + range.length) <= fullValue.size()) {
          selectedText = fullValue.substr(range.location, range.length);
        }
      }
      CFRelease(rangeRef);
    }
  }

  CFRelease(focusedElement);

  return CreateStringOrNull(env, selectedText);
}

// ── getFocusedElementInfo() ──────────────────────────────────────────

static napi_value GetFocusedElementInfo(napi_env env, napi_callback_info /*info*/) {
  NSRunningApplication *app = [[NSWorkspace sharedWorkspace] frontmostApplication];
  if (!app) {
    napi_value null_val;
    napi_get_null(env, &null_val);
    return null_val;
  }

  pid_t pid = [app processIdentifier];
  AXUIElementRef axApp = AXUIElementCreateApplication(pid);
  if (!axApp) {
    napi_value null_val;
    napi_get_null(env, &null_val);
    return null_val;
  }

  AXUIElementRef focusedElement = AXCopyElementAttribute(axApp, kAXFocusedUIElementAttribute);
  CFRelease(axApp);

  if (!focusedElement) {
    napi_value null_val;
    napi_get_null(env, &null_val);
    return null_val;
  }

  std::string role = AXCopyStringAttribute(focusedElement, kAXRoleAttribute);
  std::string title = AXCopyStringAttribute(focusedElement, kAXTitleAttribute);
  std::string value = AXCopyStringAttribute(focusedElement, kAXValueAttribute);
  CFRelease(focusedElement);

  napi_value obj;
  napi_create_object(env, &obj);

  napi_value role_val, title_val, value_val;
  napi_create_string_utf8(env, role.c_str(), role.size(), &role_val);
  napi_create_string_utf8(env, title.c_str(), title.size(), &title_val);
  napi_create_string_utf8(env, value.c_str(), value.size(), &value_val);

  napi_set_named_property(env, obj, "role", role_val);
  napi_set_named_property(env, obj, "title", title_val);
  napi_set_named_property(env, obj, "value", value_val);

  return obj;
}

// ── getBrowserURL() ──────────────────────────────────────────────────

static std::string RunAppleScript(const std::string &source) {
  @autoreleasepool {
    NSString *scriptSource = [NSString stringWithUTF8String:source.c_str()];
    NSAppleScript *script = [[NSAppleScript alloc] initWithSource:scriptSource];
    NSDictionary *error = nil;
    NSAppleEventDescriptor *result = [script executeAndReturnError:&error];
    if (error || !result) return "";
    NSString *str = [result stringValue];
    return str ? NSStringToStdString(str) : "";
  }
}

static napi_value GetBrowserURL(napi_env env, napi_callback_info /*info*/) {
  NSRunningApplication *app = [[NSWorkspace sharedWorkspace] frontmostApplication];
  if (!app) {
    napi_value null_val;
    napi_get_null(env, &null_val);
    return null_val;
  }

  std::string bundleId = NSStringToStdString([app bundleIdentifier]);
  std::string url;

  if (bundleId == "com.apple.Safari") {
    url = RunAppleScript("tell application \"Safari\" to get URL of current tab of front window");
  } else if (bundleId == "com.google.Chrome") {
    url = RunAppleScript("tell application \"Google Chrome\" to get URL of active tab of front window");
  } else if (bundleId == "company.thebrowser.Browser") {
    url = RunAppleScript("tell application \"Arc\" to get URL of active tab of front window");
  } else if (bundleId == "org.mozilla.firefox") {
    // Firefox has no AppleScript URL API; use System Events to read the address bar
    url = RunAppleScript(
      "tell application \"System Events\" to get value of UI element 1 "
      "of combo box 1 of toolbar \"Navigation\" of first window "
      "of application process \"Firefox\"");
  }

  return CreateStringOrNull(env, url);
}

// ── getFinderSelection() ─────────────────────────────────────────────

static napi_value GetFinderSelection(napi_env env, napi_callback_info /*info*/) {
  std::string script =
    "tell application \"Finder\"\n"
    "  set theSelection to selection as alias list\n"
    "  set thePaths to {}\n"
    "  repeat with anAlias in theSelection\n"
    "    set end of thePaths to POSIX path of anAlias\n"
    "  end repeat\n"
    "  set AppleScript's text item delimiters to \"\\n\"\n"
    "  return thePaths as text\n"
    "end tell";

  std::string result = RunAppleScript(script);

  napi_value arr;
  napi_create_array(env, &arr);

  if (result.empty()) return arr;

  // Split by newline
  uint32_t index = 0;
  size_t start = 0;
  while (start < result.size()) {
    size_t end = result.find('\n', start);
    if (end == std::string::npos) end = result.size();
    std::string path = result.substr(start, end - start);
    if (!path.empty()) {
      napi_value path_val;
      napi_create_string_utf8(env, path.c_str(), path.size(), &path_val);
      napi_set_element(env, arr, index, path_val);
      index++;
    }
    start = end + 1;
  }

  return arr;
}

// ── getVSCodeFilePath() ──────────────────────────────────────────────

static napi_value GetVSCodeFilePath(napi_env env, napi_callback_info /*info*/) {
  std::string windowName = RunAppleScript(
    "tell application \"System Events\" to get name of front window "
    "of application process \"Code\""
  );

  return CreateStringOrNull(env, windowName);
}

// ── isAccessibilityEnabled() ─────────────────────────────────────────

static napi_value IsAccessibilityEnabled(napi_env env, napi_callback_info /*info*/) {
  Boolean trusted = AXIsProcessTrusted();

  napi_value result;
  napi_get_boolean(env, trusted, &result);
  return result;
}

// ── requestAccessibilityAccess() ─────────────────────────────────────

static napi_value RequestAccessibilityAccess(napi_env env, napi_callback_info /*info*/) {
  NSDictionary *options = @{(__bridge id)kAXTrustedCheckOptionPrompt: @YES};
  Boolean trusted = AXIsProcessTrustedWithOptions((__bridge CFDictionaryRef)options);

  napi_value result;
  napi_get_boolean(env, trusted, &result);
  return result;
}

// ── Module init ──────────────────────────────────────────────────────

static napi_value Init(napi_env env, napi_value exports) {
  napi_property_descriptor props[] = {
    {"getActiveApp", nullptr, GetActiveApp, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"getWindowTitle", nullptr, GetWindowTitle, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"getSelectedText", nullptr, GetSelectedText, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"getFocusedElementInfo", nullptr, GetFocusedElementInfo, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"getBrowserURL", nullptr, GetBrowserURL, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"getFinderSelection", nullptr, GetFinderSelection, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"getVSCodeFilePath", nullptr, GetVSCodeFilePath, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"isAccessibilityEnabled", nullptr, IsAccessibilityEnabled, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"requestAccessibilityAccess", nullptr, RequestAccessibilityAccess, nullptr, nullptr, nullptr, napi_default, nullptr}
  };

  napi_define_properties(env, exports, 9, props);
  return exports;
}

NAPI_MODULE(NODE_GYP_MODULE_NAME, Init)
