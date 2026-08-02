// example.cpp — a runnable demo of the C++ proof-of-concept wrapper against a live `pipeline serve`.
// provenance: framework · generic · placeholders only · no client content.
//
// This exercises the FULL canonical surface (../../docs/guide/clients.md Part 2), NOT a happy-path
// render that could 200-cache and skip the poll loop:
//
//   1. construction / env-config (§2.1)               — Client::from_env(), secret NEVER printed;
//   2. the raw layer (§2.2)                           — a discovery `list`;
//   3. the ergonomic async layer + poll state machine — a `render_and_wait` FORCED down the
//      submit → 202 → poll(Retry-After) → done traversal (force_reconcile + a fresh idempotency
//      key make a cache-hit 200-at-submit unlikely, so the load-bearing loop actually runs);
//   4. the outcome set + the `throw` error channel    — a SECOND render, deliberately crafted to
//      fail, wrapped in try/catch so a typed outcome (RenderBlocked / JobFailed / JobTimeout) is
//      demonstrably caught (§2.4);
//   5. the webhook receipt (§2.7)                      — parse_callback on a literal wakeup (pure).
//
// Run it (see README.md):
//   OPTIQUITY_SHIM_URL=http://127.0.0.1:8787 OPTIQUITY_SHIM_SECRET=<secret> ./example
// Nothing here embeds a client id or a secret — the shim coordinates below are generic placeholders.

#include <chrono>
#include <iostream>
#include <string>

#include "optiquity_client.hpp"

using optiquity::CallbackEvent;
using optiquity::Client;
using optiquity::ClientError;
using optiquity::Json;
using optiquity::JobFailed;
using optiquity::JobTimeout;
using optiquity::MalformedResponse;
using optiquity::RenderBlocked;
using optiquity::Result;
using optiquity::TransportError;

namespace {

// Generic placeholders — swap in the coordinates your `pipeline serve` allow-lists. No client
// content: these are the same framework defaults the n8n example and the doc's curl slice use.
// `kUser` is the §23 isolation prefix (parallel to the workspace) the shim REQUIRES on every
// request — a missing/empty one 400s, so it is threaded into every call below next to kWorkspace.
constexpr const char* kWorkspace = "acme";
constexpr const char* kUser = "acme-user";
constexpr const char* kItem = "deck-intro";
constexpr const char* kPlatform = "linkedin";
constexpr const char* kLanguage = "en";
constexpr const char* kOutputType = "post";

// A per-run idempotency key so a re-drive collides on the SAME job (exactly-once, §2.3) while a
// fresh run biases toward an uncached submit → 202 → poll traversal rather than a cache hit.
std::string fresh_idempotency_key() {
    const auto now = std::chrono::system_clock::now().time_since_epoch();
    const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(now).count();
    return "cpp-poc-" + std::to_string(ns);
}

void print_result(const Result& result) {
    // The Result is the raw done body (§2.8 no-invent: no synthesized from_cache / cost). Print a
    // compact summary; never dump anything that could carry a secret.
    const Json& body = result.json;
    const std::string status = body.is_object() && body.contains("status") &&
                                       body["status"].is_string()
                                   ? body["status"].get<std::string>()
                                   : "?";
    size_t items = 0;
    if (body.is_object() && body.contains("results") && body["results"].is_array()) {
        items = body["results"].size();
    }
    std::cout << "  -> Result: status=" << status << ", results[" << items << "]\n";
}

}  // namespace

int main() {
    // 1. Construction / env-config (§2.1). from_env throws std::invalid_argument if either
    //    OPTIQUITY_SHIM_URL or OPTIQUITY_SHIM_SECRET is unset — the secret NEVER comes from argv,
    //    and it is never printed anywhere in this demo.
    Client client = [] {
        try {
            return Client::from_env();
        } catch (const std::exception& e) {
            std::cerr << "config error: " << e.what() << "\n"
                      << "set OPTIQUITY_SHIM_URL and OPTIQUITY_SHIM_SECRET, then re-run.\n";
            std::exit(2);
        }
    }();

    // 2. The raw layer (§2.2): a discovery `list` (a Tier-A verb). 1:1 with the wire.
    std::cout << "[1] raw list(platform):\n";
    try {
        const auto response = client.list("platform", kWorkspace, kUser);
        std::cout << "  -> HTTP " << response.status << "\n";
    } catch (const TransportError& e) {
        std::cerr << "  -> transport error: " << e.what() << "\n";
    }

    // 3. Ergonomic async + poll state machine (§2.3): FORCE the submit → 202 → poll → done
    //    traversal (force_reconcile + a fresh key defeat the render cache-hit short-circuit).
    std::cout << "[2] render_and_wait (forced poll traversal):\n";
    try {
        const Result result = client.render_and_wait(
            kWorkspace, kUser, kItem, kPlatform, kLanguage, kOutputType, /*presentation=*/nullptr,
            /*force_reconcile=*/true, /*idempotency_key=*/fresh_idempotency_key());
        print_result(result);
    } catch (const RenderBlocked& e) {
        std::cout << "  -> RenderBlocked: block=" << e.block.dump() << "\n";
    } catch (const JobFailed& e) {
        std::cout << "  -> JobFailed: code=" << e.code.dump() << " redrivable=" << e.redrivable
                  << "\n";
    } catch (const JobTimeout& e) {
        std::cout << "  -> JobTimeout: redrivable=" << e.redrivable << "\n";
    } catch (const MalformedResponse& e) {
        std::cout << "  -> MalformedResponse: " << e.what() << "\n";
    } catch (const TransportError& e) {
        std::cerr << "  -> transport error: " << e.what() << "\n";
    }

    // 4. The outcome set + the `throw` error channel (§2.4): a render deliberately aimed at a
    //    non-existent item so a typed FAILURE outcome is demonstrably caught (this is the
    //    load-bearing error path — not a happy-path render).
    std::cout << "[3] render_and_wait on a missing item (expect a caught typed outcome):\n";
    try {
        const Result result = client.render_and_wait(
            kWorkspace, kUser, "does-not-exist-" + fresh_idempotency_key(), kPlatform, kLanguage,
            kOutputType);
        // Reaching here would be surprising; still honor the no-invent Result contract.
        std::cout << "  -> unexpectedly succeeded; ";
        print_result(result);
    } catch (const RenderBlocked& e) {
        std::cout << "  -> caught RenderBlocked (block record surfaced): " << e.block.dump() << "\n";
    } catch (const JobFailed& e) {
        std::cout << "  -> caught JobFailed: code=" << e.code.dump()
                  << " redrivable=" << e.redrivable << "\n";
    } catch (const JobTimeout& e) {
        std::cout << "  -> caught JobTimeout: redrivable=" << e.redrivable << "\n";
    } catch (const ClientError& e) {
        std::cout << "  -> caught ClientError: " << e.what() << "\n";
    } catch (const TransportError& e) {
        std::cerr << "  -> transport error (server not reachable?): " << e.what() << "\n";
    }

    // 5. The webhook receipt (§2.7): parse_callback is PURE (no network) — validate + parse a
    //    wakeup body. A woken client would then call client.fetch_after_callback(event) to fetch the
    //    finished output through the authenticated poll (shown here as a comment to avoid polling a
    //    synthetic key).
    std::cout << "[4] parse_callback (pure):\n";
    const Json wakeup = {
        {"event", "job.done"},
        {"job", {{"workspace", kWorkspace}, {"key", "r-0123456789abcdef"}, {"target_ids", {"t-1"}}}},
    };
    try {
        const CallbackEvent event = optiquity::parse_callback(wakeup);
        std::cout << "  -> event=" << event.event << " workspace=" << event.workspace
                  << " key=" << event.key << " target_ids[" << event.target_ids.size() << "]\n";
        // const Result woken = client.fetch_after_callback(event, kUser);  // authenticated fetch-after-wake (user supplied by the caller)
    } catch (const std::invalid_argument& e) {
        std::cout << "  -> rejected: " << e.what() << "\n";
    }

    // The generate slice needs a served continue-session door + a mandatory idempotency key:
    //   auto s = client.begin_session(kWorkspace, kUser, /*selection=*/Json::object());  // Tier-A token
    //   Result r = client.generate_and_wait(kWorkspace, kUser, s.token, fresh_idempotency_key());
    // It runs the SAME poll state machine as render_and_wait; omitted from the default run to keep
    // the demo to the render slice (the load-bearing shared algorithm).

    return 0;
}
