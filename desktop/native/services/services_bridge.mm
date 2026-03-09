/**
 * services_bridge.mm — Native N-API addon for macOS Services integration.
 *
 * Registers an NSApp servicesProvider so Science Reader appears in the
 * system-wide Services menu.  Each handler extracts pasteboard text and
 * dispatches it to a threadsafe JS callback on the Node event loop.
 *
 * Exports:
 *   registerServicesProvider()  — call once from main process
 *   onServiceMessage(callback)  — callback(action: string, text: string)
 */

#import <Cocoa/Cocoa.h>
#include <napi.h>
#include <string>
#include <mutex>

// ── Thread-safe bridge ──────────────────────────────────────────────

static napi_threadsafe_function g_tsfn = nullptr;
static std::mutex g_tsfn_mutex;

struct ServicePayload {
  std::string action;
  std::string text;
};

// Called on the Node.js thread by napi_call_threadsafe_function
static void CallJSCallback(napi_env env, napi_value js_cb, void * /*context*/, void *data) {
  if (env == nullptr || js_cb == nullptr) {
    delete static_cast<ServicePayload *>(data);
    return;
  }

  ServicePayload *payload = static_cast<ServicePayload *>(data);

  napi_value action_val, text_val;
  napi_create_string_utf8(env, payload->action.c_str(), payload->action.size(), &action_val);
  napi_create_string_utf8(env, payload->text.c_str(), payload->text.size(), &text_val);

  napi_value argv[2] = {action_val, text_val};
  napi_value undefined;
  napi_get_undefined(env, &undefined);

  napi_call_function(env, undefined, js_cb, 2, argv, nullptr);

  delete payload;
}

// Enqueue a service event from *any* thread → Node.js event loop
static void DispatchServiceEvent(const std::string &action, const std::string &text) {
  std::lock_guard<std::mutex> lock(g_tsfn_mutex);
  if (g_tsfn == nullptr) return;

  auto *payload = new ServicePayload{action, text};
  napi_status status = napi_call_threadsafe_function(g_tsfn, payload, napi_tsfn_nonblocking);
  if (status != napi_ok) {
    delete payload;
  }
}

// ── Objective-C ServicesProvider ─────────────────────────────────────

@interface ServicesProvider : NSObject
@end

@implementation ServicesProvider

- (NSString *)extractTextFromPasteboard:(NSPasteboard *)pboard error:(NSString **)error {
  NSString *text = [pboard stringForType:NSPasteboardTypeString];
  if (!text) {
    if (error) *error = @"No text on pasteboard";
    return nil;
  }
  return text;
}

- (void)saveToMemory:(NSPasteboard *)pboard userData:(NSString *)userData error:(NSString **)error {
  NSString *text = [self extractTextFromPasteboard:pboard error:error];
  if (text) DispatchServiceEvent("saveToMemory", [text UTF8String]);
}

- (void)askAboutThis:(NSPasteboard *)pboard userData:(NSString *)userData error:(NSString **)error {
  NSString *text = [self extractTextFromPasteboard:pboard error:error];
  if (text) DispatchServiceEvent("askAboutThis", [text UTF8String]);
}

- (void)explainText:(NSPasteboard *)pboard userData:(NSString *)userData error:(NSString **)error {
  NSString *text = [self extractTextFromPasteboard:pboard error:error];
  if (text) DispatchServiceEvent("explain", [text UTF8String]);
}

- (void)summarizeText:(NSPasteboard *)pboard userData:(NSString *)userData error:(NSString **)error {
  NSString *text = [self extractTextFromPasteboard:pboard error:error];
  if (text) DispatchServiceEvent("summarize", [text UTF8String]);
}

- (void)sendToChat:(NSPasteboard *)pboard userData:(NSString *)userData error:(NSString **)error {
  NSString *text = [self extractTextFromPasteboard:pboard error:error];
  if (text) DispatchServiceEvent("sendToChat", [text UTF8String]);
}

- (void)runPrompt:(NSPasteboard *)pboard userData:(NSString *)userData error:(NSString **)error {
  NSString *text = [self extractTextFromPasteboard:pboard error:error];
  if (text) DispatchServiceEvent("runPrompt", [text UTF8String]);
}

@end

// ── N-API exports ───────────────────────────────────────────────────

static ServicesProvider *g_provider = nil;

// registerServicesProvider() — must be called from Electron main process
static napi_value RegisterServicesProvider(napi_env env, napi_callback_info /*info*/) {
  // setServicesProvider must happen on the main (AppKit) thread.
  // In Electron, the main process Node.js code runs on the main thread,
  // but wrap in dispatch_async for safety in case it's called from a worker.
  if ([NSThread isMainThread]) {
    if (!g_provider) {
      g_provider = [[ServicesProvider alloc] init];
    }
    [NSApp setServicesProvider:g_provider];
    [NSApp registerServicesMenuSendTypes:@[NSPasteboardTypeString] returnTypes:@[]];
  } else {
    dispatch_async(dispatch_get_main_queue(), ^{
      if (!g_provider) {
        g_provider = [[ServicesProvider alloc] init];
      }
      [NSApp setServicesProvider:g_provider];
      [NSApp registerServicesMenuSendTypes:@[NSPasteboardTypeString] returnTypes:@[]];
    });
  }

  napi_value undefined;
  napi_get_undefined(env, &undefined);
  return undefined;
}

// onServiceMessage(callback) — register JS callback for service events
static napi_value OnServiceMessage(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value argv[1];
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

  if (argc < 1) {
    napi_throw_error(env, nullptr, "onServiceMessage requires a callback argument");
    return nullptr;
  }

  napi_valuetype vtype;
  napi_typeof(env, argv[0], &vtype);
  if (vtype != napi_function) {
    napi_throw_type_error(env, nullptr, "onServiceMessage argument must be a function");
    return nullptr;
  }

  // Release previous threadsafe function if any
  {
    std::lock_guard<std::mutex> lock(g_tsfn_mutex);
    if (g_tsfn != nullptr) {
      napi_release_threadsafe_function(g_tsfn, napi_tsfn_release);
      g_tsfn = nullptr;
    }
  }

  napi_value resource_name;
  napi_create_string_utf8(env, "ServicesCallback", NAPI_AUTO_LENGTH, &resource_name);

  napi_threadsafe_function tsfn;
  napi_status status = napi_create_threadsafe_function(
      env,
      argv[0],       // JS callback
      nullptr,       // async_resource
      resource_name, // async_resource_name
      0,             // max_queue_size (unlimited)
      1,             // initial_thread_count
      nullptr,       // thread_finalize_data
      nullptr,       // thread_finalize_cb
      nullptr,       // context
      CallJSCallback,// call_js_cb
      &tsfn);

  if (status != napi_ok) {
    napi_throw_error(env, nullptr, "Failed to create threadsafe function");
    return nullptr;
  }

  {
    std::lock_guard<std::mutex> lock(g_tsfn_mutex);
    g_tsfn = tsfn;
  }

  napi_value undefined;
  napi_get_undefined(env, &undefined);
  return undefined;
}

// Module init
static napi_value Init(napi_env env, napi_value exports) {
  napi_property_descriptor props[] = {
    {"registerServicesProvider", nullptr, RegisterServicesProvider, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"onServiceMessage", nullptr, OnServiceMessage, nullptr, nullptr, nullptr, napi_default, nullptr}
  };

  napi_define_properties(env, exports, 2, props);
  return exports;
}

NAPI_MODULE(NODE_GYP_MODULE_NAME, Init)
