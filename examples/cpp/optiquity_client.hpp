// optiquity_client.hpp — C++17 proof-of-concept wrapper for the optiquity content pipeline.
// provenance: framework · generic · placeholders only · no client content.
//
// THE SINGLE NEUTRAL SOURCE IS ../../docs/guide/clients.md. This is the C++ co-equal of the
// stdlib Python reference wrapper (pipeline/client/): same method set, same outcome set, same poll
// state machine (§2.3), same normalized-Response rule (§2.5), same Retry-After / malformed-body
// fallback rule (§2.6), same no-invent rule (§2.8). Only the substrate is language-reality: the
// error channel is `throw` (C++17 grounds) and the transport is libcurl + nlohmann/json. Nothing
// else differs from Python.
//
// WIRE-TOKEN VOCABULARY LIVES IN THE DOC, NOT HERE. The four token sets (sync-errors, async-status,
// terminal-codes, callback-events) live ONLY in ../../docs/guide/clients.md, between its
// `<!-- wire-tokens:*:begin/end -->` sentinels. This client does NOT hardcode them: it surfaces the
// RAW `code` (§1.6 open-string rule) and branches on `redrivable` / `terminal`, never on an
// exhaustive enum. When those blocks change, update this file — see examples/cpp/README.md
// "Drift checklist" (CI does NOT build C++, so the doc + this comment are the contract of record).

#ifndef OPTIQUITY_CLIENT_HPP
#define OPTIQUITY_CLIENT_HPP

#include <functional>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

namespace optiquity {

using Json = nlohmann::json;

// --- The normalized transport value (clients.md §2.5) ----------------------------------------
// Every HTTP status funnels into ONE Response — a 4xx/5xx is a Response, never a thrown transport
// error. `json` is null on a non-JSON / empty body (the guarded parse, §2.6); `headers` preserves
// the reply headers (case as received; look them up case-insensitively).
struct Response {
    long status = 0;
    std::map<std::string, std::string> headers;
    Json json;
};

// --- The Tier-A begin-session handle (clients.md §2.3) ---------------------------------------
struct SessionHandle {
    std::string workspace;
    Json token;        // the session cursor the next generate_and_wait consumes (null if absent)
    Response response; // the raw envelope (plan ids / context / warnings)
};

// --- A parsed webhook WAKEUP (clients.md §2.7) — wakeup-only, never the result itself ---------
struct CallbackEvent {
    std::string event;                  // one of {job.done, job.failed}
    std::string workspace;
    std::string key;
    std::vector<std::string> target_ids;
    Json code;        // present only on a failure wakeup (raw, null otherwise)
    Json redrivable;  // present only on a failure wakeup (raw, null otherwise)
};

// --- The outcome set (clients.md §2.4) — identical everywhere; C++ channel is `throw` ---------
// Result is RETURNED; the three failure outcomes + the malformed-body guard are THROWN and all
// subclass ClientError. A genuine transport failure is TransportError, which is deliberately NOT a
// ClientError (it mirrors Python's un-swallowed urllib URLError, §2.5).
struct Result {
    Json json;  // the whole 200 {status: done, job, results} body; NO synthesized cache/cost (§2.8)
};

class ClientError : public std::runtime_error {
public:
    explicit ClientError(const std::string& message) : std::runtime_error(message) {}
};

// Genuine connection failure / timeout — the single non-outcome exception channel (§2.5).
class TransportError : public std::runtime_error {
public:
    explicit TransportError(const std::string& message) : std::runtime_error(message) {}
};

// The await deadline elapsed, or the wire returned a 504 timeout-class terminal. Always redrivable.
class JobTimeout : public ClientError {
public:
    bool redrivable;
    explicit JobTimeout(bool redrivable_ = true)
        : ClientError("job timed out (redrivable=" + std::string(redrivable_ ? "true" : "false") +
                      ")"),
          redrivable(redrivable_) {}
};

// A stored terminal failure: a 4xx/5xx {status: failed, code, redrivable, terminal} poll body.
// `code` is surfaced RAW (an OPEN string, §1.6) — report it, never switch exhaustively on it.
class JobFailed : public ClientError {
public:
    Json code;
    bool redrivable;
    Json terminal;
    JobFailed(Json code_, bool redrivable_, Json terminal_)
        : ClientError("job failed: code=" + code_.dump() +
                      " redrivable=" + std::string(redrivable_ ? "true" : "false")),
          code(std::move(code_)),
          redrivable(redrivable_),
          terminal(std::move(terminal_)) {}
};

// A refused render: a 400 {error: render-blocked, block} body. `block` is the raw refusal record.
class RenderBlocked : public ClientError {
public:
    Json block;
    explicit RenderBlocked(Json block_) : ClientError("render blocked"), block(std::move(block_)) {}
};

// A 200 that is not a well-formed {status: done, results: [...]} body — a truncated / malformed
// done reply (§2.6). Raised as a DEFINED client error, never an uncaught JSON/type crash.
class MalformedResponse : public ClientError {
public:
    Response response;
    MalformedResponse(const std::string& message, Response response_)
        : ClientError(message), response(std::move(response_)) {}
};

// PURE (no network): validate + parse a webhook wakeup body into a CallbackEvent (clients.md §2.7).
// Throws std::invalid_argument for a non-object payload or an `event` outside {job.done, job.failed}.
CallbackEvent parse_callback(const Json& payload);

// --- The canonical pipeline client (clients.md Part 2), libcurl + nlohmann/json ----------------
class Client {
public:
    // Construction / configuration (§2.1). Secret rides `Authorization: Bearer <secret>` by default,
    // or `X-API-Key: <secret>` when api_key_header=true. timeout is per-request seconds;
    // poll_interval is the initial poll cadence; max_poll_seconds is the overall await deadline.
    Client(std::string base_url, std::string secret, bool api_key_header = false, long timeout = 30,
           double poll_interval = 1.0, double max_poll_seconds = 1320);

    // Build from the env config (§2.1): OPTIQUITY_SHIM_URL + OPTIQUITY_SHIM_SECRET — identical
    // across languages. Throws std::invalid_argument if either is unset (the secret NEVER from argv).
    static Client from_env(bool api_key_header = false, long timeout = 30, double poll_interval = 1.0,
                           double max_poll_seconds = 1320);

    // --- The raw layer, 1:1 with the wire (clients.md §2.2) ----------------------------------
    Response invoke(const std::string& verb, const std::string& workspace, const Json& params,
                    const Json& token = nullptr, const Json& pins = nullptr);
    Response poll(const std::string& workspace, const std::string& key,
                  const std::vector<std::string>& target_ids);
    Response list(const std::string& type, const std::string& workspace,
                  const Json& filters = nullptr);
    Response get(const std::string& type, const std::string& id, const std::string& workspace);

    // --- The ergonomic async layer + poll state machine (clients.md §2.3) --------------------
    // `generate` is accepted for surface parity but FORCED to "none" (the one-call
    // begin-session{generate!=none} is a deferred 501; the supported path is two calls).
    SessionHandle begin_session(const std::string& workspace, const Json& selection,
                                const Json& overrides = nullptr, const Json& pins = nullptr,
                                const std::string& generate = "none",
                                const std::string& idempotency_key = "");
    // idempotency_key REQUIRED (empty throws std::invalid_argument fast, before any network).
    Result generate_and_wait(const std::string& workspace, const Json& token,
                             const std::string& idempotency_key, const Json& batch_size = nullptr,
                             const Json& only = nullptr, const std::string& callback_url = "",
                             const Json& extra = nullptr);
    // render is content-addressed + token-free, so idempotency_key is OPTIONAL. A cache-hit 200 at
    // submit collapses into the SAME Result as the 202-then-poll path (§2.8 no-invent).
    Result render_and_wait(const std::string& workspace, const std::string& item,
                           const std::string& platform, const std::string& language,
                           const std::string& output_type, const Json& presentation = nullptr,
                           bool force_reconcile = false, const std::string& idempotency_key = "",
                           const std::string& callback_url = "");

    // --- The webhook fetch (clients.md §2.7) — no receiver server -----------------------------
    Result fetch_after_callback(const CallbackEvent& event);

private:
    Response request(const std::string& path, const Json& payload);
    double retry_after_seconds(const std::map<std::string, std::string>& headers, double fallback);
    Result await_terminal(const std::string& workspace, const std::function<Response()>& submit);

    std::string base_url_;
    long timeout_;
    double poll_interval_;
    double max_poll_seconds_;
    std::string auth_header_name_;
    std::string auth_header_value_;
};

}  // namespace optiquity

#endif  // OPTIQUITY_CLIENT_HPP
