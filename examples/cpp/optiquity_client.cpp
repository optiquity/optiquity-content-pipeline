// optiquity_client.cpp — implementation of the C++17 proof-of-concept wrapper.
// provenance: framework · generic · no client content. See optiquity_client.hpp for the contract.
//
// Mirrors pipeline/client/client.py branch-for-branch against ../../docs/guide/clients.md. The
// substrate is libcurl (HTTP, verified TLS, no-follow-redirect) + nlohmann/json (guarded parse).

#include "optiquity_client.hpp"

#include <algorithm>
#include <cctype>
#include <chrono>
#include <cstdlib>
#include <thread>

#include <curl/curl.h>

namespace optiquity {

namespace {

// --- Endpoints / event names / env keys / cadence (clients.md §1.1, §1.7, §2.1, §2.3) --------
constexpr const char* kInvokePath = "/invoke";
constexpr const char* kPollPath = "/poll";
constexpr const char* kEventDone = "job.done";
constexpr const char* kEventFailed = "job.failed";
constexpr const char* kEnvUrl = "OPTIQUITY_SHIM_URL";
constexpr const char* kEnvSecret = "OPTIQUITY_SHIM_SECRET";
constexpr double kBackoffFactor = 2.0;
constexpr double kBackoffCap = 30.0;

// HTTP statuses the poll state machine branches on (clients.md §2.3).
constexpr long kHttpOk = 200;
constexpr long kHttpAccepted = 202;
constexpr long kHttpBadRequest = 400;
constexpr long kHttpConflict = 409;
constexpr long kHttpTooManyRequests = 429;
constexpr long kHttpGatewayTimeout = 504;

// One-time libcurl global init/cleanup (function-local static → thread-safe init in C++11+).
struct CurlGlobal {
    CurlGlobal() { curl_global_init(CURL_GLOBAL_DEFAULT); }
    ~CurlGlobal() { curl_global_cleanup(); }
};

std::string to_lower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return s;
}

std::string trim(const std::string& s) {
    size_t begin = 0;
    size_t end = s.size();
    while (begin < end && std::isspace(static_cast<unsigned char>(s[begin]))) ++begin;
    while (end > begin && std::isspace(static_cast<unsigned char>(s[end - 1]))) --end;
    return s.substr(begin, end - begin);
}

// Case-insensitive header lookup (HTTP header names are case-insensitive) — mirrors _header_get.
const std::string* header_get(const std::map<std::string, std::string>& headers,
                              const std::string& name) {
    const std::string lowered = to_lower(name);
    for (const auto& kv : headers) {
        if (to_lower(kv.first) == lowered) return &kv.second;
    }
    return nullptr;
}

// A tolerant object-field-as-string read (returns "" if missing or non-string) — mirrors the
// Python `.get()` that never raises on a wrong/absent type.
std::string str_field(const Json& obj, const char* key) {
    if (!obj.is_object()) return std::string();
    auto it = obj.find(key);
    if (it != obj.end() && it->is_string()) return it->get<std::string>();
    return std::string();
}

// Python-truthiness for a Json value (null/false/0/""/[]/{} are falsy) — used for `A or B` and
// bool(redrivable).
bool truthy(const Json& v) {
    if (v.is_null()) return false;
    if (v.is_boolean()) return v.get<bool>();
    if (v.is_number()) return v.get<double>() != 0.0;
    if (v.is_string()) return !v.get<std::string>().empty();
    if (v.is_array() || v.is_object()) return !v.empty();
    return true;
}

// `a or b` (§2.3 JobFailed code): prefer a stored terminal `code`, else fall back to a bare
// {error: <token>} body's token so a non-render-blocked 4xx surfaces its RAW token, not null.
Json json_or(const Json& a, const Json& b) { return truthy(a) ? a : b; }

// Guarded JSON parse (§2.6): a non-JSON / empty body → null, status preserved, never a decode crash.
Json parse_guarded(const std::string& body) {
    if (body.empty()) return Json(nullptr);
    Json parsed = Json::parse(body, /*cb=*/nullptr, /*allow_exceptions=*/false);
    if (parsed.is_discarded()) return Json(nullptr);
    return parsed;
}

void sleep_seconds(double seconds) {
    if (seconds <= 0.0) return;
    std::this_thread::sleep_for(std::chrono::duration<double>(seconds));
}

size_t write_cb(char* ptr, size_t size, size_t nmemb, void* userdata) {
    auto* buf = static_cast<std::string*>(userdata);
    const size_t total = size * nmemb;
    buf->append(ptr, total);
    return total;
}

size_t header_cb(char* buffer, size_t size, size_t nitems, void* userdata) {
    auto* headers = static_cast<std::map<std::string, std::string>*>(userdata);
    const size_t total = size * nitems;
    std::string line(buffer, total);
    while (!line.empty() && (line.back() == '\r' || line.back() == '\n')) line.pop_back();
    const auto colon = line.find(':');  // skips the "HTTP/1.1 200" status line (no colon)
    if (colon != std::string::npos) {
        const std::string name = trim(line.substr(0, colon));
        const std::string value = trim(line.substr(colon + 1));
        if (!name.empty()) (*headers)[name] = value;
    }
    return total;
}

}  // namespace

// --- parse_callback (pure) --------------------------------------------------------------------
CallbackEvent parse_callback(const Json& payload) {
    if (!payload.is_object()) {
        throw std::invalid_argument("callback payload must be a JSON object");
    }
    const std::string event = str_field(payload, "event");
    if (event != kEventDone && event != kEventFailed) {
        const Json raw = payload.contains("event") ? payload["event"] : Json(nullptr);
        throw std::invalid_argument("unknown callback event: " + raw.dump() +
                                    " (expected job.done or job.failed)");
    }
    const Json job = (payload.contains("job") && payload["job"].is_object()) ? payload["job"]
                                                                             : Json::object();
    CallbackEvent ev;
    ev.event = event;
    ev.workspace = str_field(job, "workspace");
    // §23/Z4: read the zone off the job block next to workspace (empty on a pre-zone wakeup).
    ev.zone = str_field(job, "zone");
    ev.key = str_field(job, "key");
    if (job.contains("target_ids") && job["target_ids"].is_array()) {
        for (const auto& t : job["target_ids"]) {
            ev.target_ids.push_back(t.is_string() ? t.get<std::string>() : t.dump());
        }
    }
    ev.code = payload.contains("code") ? payload["code"] : Json(nullptr);
    ev.redrivable = payload.contains("redrivable") ? payload["redrivable"] : Json(nullptr);
    return ev;
}

// --- Client construction ----------------------------------------------------------------------
Client::Client(std::string base_url, std::string secret, bool api_key_header, long timeout,
               double poll_interval, double max_poll_seconds)
    : timeout_(timeout), poll_interval_(poll_interval), max_poll_seconds_(max_poll_seconds) {
    if (base_url.empty()) throw std::invalid_argument("base_url is required");
    if (secret.empty()) throw std::invalid_argument("secret is required");
    while (!base_url.empty() && base_url.back() == '/') base_url.pop_back();  // rstrip("/")
    base_url_ = std::move(base_url);
    if (api_key_header) {
        auth_header_name_ = "X-API-Key";
        auth_header_value_ = std::move(secret);
    } else {
        auth_header_name_ = "Authorization";
        auth_header_value_ = "Bearer " + secret;
    }
}

Client Client::from_env(bool api_key_header, long timeout, double poll_interval,
                        double max_poll_seconds) {
    const char* url = std::getenv(kEnvUrl);
    const char* secret = std::getenv(kEnvSecret);
    if (url == nullptr || *url == '\0') {
        throw std::invalid_argument(std::string(kEnvUrl) + " is not set");
    }
    if (secret == nullptr || *secret == '\0') {
        throw std::invalid_argument(std::string(kEnvSecret) + " is not set");
    }
    return Client(url, secret, api_key_header, timeout, poll_interval, max_poll_seconds);
}

// --- The transport primitive (clients.md §2.5) -----------------------------------------------
Response Client::request(const std::string& path, const Json& payload) {
    static CurlGlobal curl_global;  // one-time global init, thread-safe.
    CURL* curl = curl_easy_init();
    if (curl == nullptr) throw TransportError("curl_easy_init failed");

    const std::string url = base_url_ + path;
    const std::string data = payload.dump();
    std::string body_buf;
    std::map<std::string, std::string> resp_headers;

    struct curl_slist* hdrs = nullptr;
    hdrs = curl_slist_append(hdrs, "Content-Type: application/json");
    const std::string auth = auth_header_name_ + ": " + auth_header_value_;
    hdrs = curl_slist_append(hdrs, auth.c_str());

    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, data.c_str());
    curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, static_cast<long>(data.size()));
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, hdrs);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &body_buf);
    curl_easy_setopt(curl, CURLOPT_HEADERFUNCTION, header_cb);
    curl_easy_setopt(curl, CURLOPT_HEADERDATA, &resp_headers);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, timeout_);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 0L);  // §2.5 no-follow: a 3xx is a Response
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 1L);  // §2.5 verified TLS — never unverified
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYHOST, 2L);
    // CURLOPT_FAILONERROR is deliberately NOT set: a 4xx/5xx must come back as a normal Response
    // (§2.5 normalized-Response rule), NOT as a transport error. Only a genuine connection failure
    // / timeout returns a non-OK CURLcode and becomes the single TransportError channel.

    const CURLcode rc = curl_easy_perform(curl);
    if (rc != CURLE_OK) {
        const std::string err = curl_easy_strerror(rc);
        curl_slist_free_all(hdrs);
        curl_easy_cleanup(curl);
        throw TransportError(std::string("transport failure: ") + err);
    }
    long status = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status);
    curl_slist_free_all(hdrs);
    curl_easy_cleanup(curl);

    return Response{status, std::move(resp_headers), parse_guarded(body_buf)};
}

double Client::retry_after_seconds(const std::map<std::string, std::string>& headers,
                                   double fallback) {
    // Parse Retry-After as INTEGER delta-seconds (§2.3); absent / blank / non-integer → fall back
    // to the backoff cadence (§2.6); never crash on int(None).
    const std::string* raw = header_get(headers, "Retry-After");
    if (raw == nullptr) return fallback;
    const std::string s = trim(*raw);
    if (s.empty()) return fallback;
    try {
        size_t pos = 0;
        const long value = std::stol(s, &pos);
        if (pos != s.size()) return fallback;  // trailing non-integer (e.g. "1.5") → fallback
        return static_cast<double>(value);
    } catch (const std::exception&) {
        return fallback;
    }
}

// --- The raw layer, 1:1 with the wire (clients.md §2.2) --------------------------------------
// `user` is MANDATORY on every request carrying `workspace` (the §23 isolation prefix) — it rides
// the body next to `workspace`, 1:1 with the wire the shim enforces (a missing/empty one 400s).
// `zone` (§23/Z4, default "default") rides the SAME body next to user/workspace, exactly as the shim
// reads it (an omitted zone is the door's own "default").
Response Client::invoke(const std::string& verb, const std::string& workspace,
                        const std::string& user, const Json& params, const Json& token,
                        const Json& pins, const std::string& zone) {
    Json body = {
        {"verb", verb}, {"workspace", workspace}, {"user", user}, {"zone", zone},
        {"params", params}, {"token", token}, {"pins", pins},
    };
    return request(kInvokePath, body);
}

Response Client::poll(const std::string& workspace, const std::string& user, const std::string& key,
                      const std::vector<std::string>& target_ids, const std::string& zone) {
    Json body = {{"workspace", workspace}, {"user", user}, {"zone", zone}, {"key", key},
                 {"target_ids", target_ids}};
    return request(kPollPath, body);
}

Response Client::list(const std::string& type, const std::string& workspace,
                      const std::string& user, const Json& filters, const std::string& zone) {
    Json params = {{"type", type}};
    if (!filters.is_null()) params["filters"] = filters;
    return invoke("list", workspace, user, params, nullptr, nullptr, zone);
}

Response Client::get(const std::string& type, const std::string& id, const std::string& workspace,
                     const std::string& user, const std::string& zone) {
    return invoke("get", workspace, user, Json{{"type", type}, {"id", id}}, nullptr, nullptr, zone);
}

// --- The ergonomic async layer (clients.md §2.3) ---------------------------------------------
SessionHandle Client::begin_session(const std::string& workspace, const std::string& user,
                                    const Json& selection, const Json& overrides, const Json& pins,
                                    const std::string& /*generate*/,
                                    const std::string& idempotency_key, const std::string& zone) {
    Json params = {{"selection", selection}, {"generate", "none"}};  // generate FORCED to "none"
    if (!overrides.is_null()) params["overrides"] = overrides;
    if (!idempotency_key.empty()) params["idempotency_key"] = idempotency_key;
    Response response = invoke("begin-session", workspace, user, params, /*token=*/nullptr, pins,
                               zone);
    const Json token =
        response.json.is_object() ? response.json.value("token", Json(nullptr)) : Json(nullptr);
    // §23/Z4: ECHO the begin zone on the handle so the paired resume carries the SAME zone.
    return SessionHandle{workspace, token, std::move(response), zone};
}

Result Client::generate_and_wait(const std::string& workspace, const std::string& user,
                                 const Json& token, const std::string& idempotency_key,
                                 const Json& batch_size, const Json& only,
                                 const std::string& callback_url, const Json& extra,
                                 const std::string& zone) {
    if (idempotency_key.empty()) {
        throw std::invalid_argument(
            "generate_and_wait requires a non-empty idempotency_key (clients.md §2.3)");
    }
    Json submit_params = {{"action", "generate-next"}, {"idempotency_key", idempotency_key}};
    if (!batch_size.is_null()) submit_params["batch_size"] = batch_size;
    if (!only.is_null()) submit_params["only"] = only;
    if (!callback_url.empty()) submit_params["callback_url"] = callback_url;
    if (extra.is_object()) submit_params.update(extra);
    auto submit = [&]() {
        return invoke("continue-session", workspace, user, submit_params, token, nullptr, zone);
    };
    return await_terminal(workspace, user, submit, zone);
}

Result Client::render_and_wait(const std::string& workspace, const std::string& user,
                               const std::string& item, const std::string& platform,
                               const std::string& language, const std::string& output_type,
                               const Json& presentation, bool force_reconcile,
                               const std::string& idempotency_key,
                               const std::string& callback_url, const std::string& zone) {
    Json params = {{"item", item},
                   {"platform", platform},
                   {"language", language},
                   {"output_type", output_type}};
    if (!presentation.is_null()) params["presentation"] = presentation;
    if (force_reconcile) params["force_reconcile"] = true;
    if (!idempotency_key.empty()) params["idempotency_key"] = idempotency_key;
    if (!callback_url.empty()) params["callback_url"] = callback_url;
    auto submit = [&]() { return invoke("render", workspace, user, params, nullptr, nullptr, zone); };
    return await_terminal(workspace, user, submit, zone);
}

Result Client::fetch_after_callback(const CallbackEvent& event, const std::string& user,
                                    const std::string& zone) {
    // §23/Z4: prefer an explicit zone; else the wakeup's own zone; else the pre-zone default.
    const std::string effective_zone =
        !zone.empty() ? zone : (!event.zone.empty() ? event.zone : "default");
    auto submit = [&]() {
        return poll(event.workspace, user, event.key, event.target_ids, effective_zone);
    };
    return await_terminal(event.workspace, user, submit, effective_zone);
}

// --- The poll state machine (clients.md §2.3) — identical in every language ------------------
Result Client::await_terminal(const std::string& workspace, const std::string& user,
                              const std::function<Response()>& submit, const std::string& zone) {
    using clock = std::chrono::steady_clock;
    const auto deadline =
        clock::now() +
        std::chrono::duration_cast<clock::duration>(std::chrono::duration<double>(max_poll_seconds_));
    double backoff = poll_interval_;
    std::string key;
    std::vector<std::string> target_ids;
    bool have_key = false;
    bool have_targets = false;

    Response response = submit();

    while (true) {
        const Json* body = response.json.is_object() ? &response.json : nullptr;
        if (body != nullptr) {
            auto job_it = body->find("job");
            if (job_it != body->end() && job_it->is_object()) {
                const Json& job = *job_it;
                const std::string job_key = str_field(job, "key");
                if (!job_key.empty()) {
                    key = job_key;
                    have_key = true;
                }
                auto targets_it = job.find("target_ids");
                if (targets_it != job.end() && targets_it->is_array() && !targets_it->empty()) {
                    target_ids.clear();
                    for (const auto& t : *targets_it) {
                        target_ids.push_back(t.is_string() ? t.get<std::string>() : t.dump());
                    }
                    have_targets = true;
                }
            }
        }

        const long status = response.status;

        // 200 done → Result; any other 200 is a malformed / truncated done body (§2.6 / F-H).
        if (status == kHttpOk) {
            if (body != nullptr && str_field(*body, "status") == "done" &&
                body->contains("results") && (*body)["results"].is_array()) {
                return Result{response.json};
            }
            throw MalformedResponse(
                "poll returned 200 without a well-formed {status: done, results: [...]} body",
                response);
        }

        // 504 timeout-class terminal → JobTimeout (re-drivable).
        if (status == kHttpGatewayTimeout) {
            throw JobTimeout(true);
        }

        // 409 re-drivable → re-submit the SAME idempotency_key immediately (no sleep), continue.
        if (status == kHttpConflict) {
            if (clock::now() >= deadline) throw JobTimeout(true);
            response = submit();
            continue;
        }

        // 400 render-blocked → RenderBlocked (a refused render, surfaced with its block record).
        if (status == kHttpBadRequest && body != nullptr &&
            str_field(*body, "error") == "render-blocked") {
            throw RenderBlocked(body->contains("block") ? (*body)["block"] : Json(nullptr));
        }

        // 202 → sleep the backoff cadence; 429 → sleep the integer Retry-After (submit OR poll).
        double delay = 0.0;
        if (status == kHttpAccepted) {
            delay = backoff;
            backoff = std::min(backoff * kBackoffFactor, kBackoffCap);
        } else if (status == kHttpTooManyRequests) {
            delay = retry_after_seconds(response.headers, backoff);
            backoff = std::min(backoff * kBackoffFactor, kBackoffCap);
        } else {
            // any other 4xx/5xx is a stored terminal failure → JobFailed (raw open-string code).
            Json code = Json(nullptr);
            bool redrivable = false;
            Json terminal = Json(nullptr);
            if (body != nullptr) {
                const Json code_field = body->contains("code") ? (*body)["code"] : Json(nullptr);
                const Json error_field = body->contains("error") ? (*body)["error"] : Json(nullptr);
                code = json_or(code_field, error_field);
                redrivable =
                    truthy(body->contains("redrivable") ? (*body)["redrivable"] : Json(nullptr));
                terminal = body->contains("terminal") ? (*body)["terminal"] : Json(nullptr);
            }
            throw JobFailed(code, redrivable, terminal);
        }

        sleep_seconds(delay);
        if (clock::now() >= deadline) throw JobTimeout(true);
        // With a captured job handle, POLL; a submit-time 429 (no handle yet) RE-SUBMITS. The poll
        // carries the SAME zone the submit ran in, so the state machine never crosses zones.
        if (have_key && have_targets) {
            response = poll(workspace, user, key, target_ids, zone);
        } else {
            response = submit();
        }
    }
}

}  // namespace optiquity
