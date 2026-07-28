# CMakeLists.txt — build the C++ proof-of-concept wrapper example.
# provenance: framework · generic · no client content.
#
# This is one of two documented build paths (the other is the one-line g++ in README.md). It builds
# a SINGLE executable and installs nothing — the wrapper is a worked example, not a packaged library
# (a packaged C++ SDK is explicitly out of MVP scope; see docs/guide/clients.md and the plan).

cmake_minimum_required(VERSION 3.14)  # 3.14+ for FetchContent_MakeAvailable
project(optiquity_client_poc CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# --- Dependency 1: libcurl (system dev package) ----------------------------------------------
# macOS Command Line Tools usually already ship it; otherwise: brew install curl /
# apt-get install libcurl4-openssl-dev (see README.md).
find_package(CURL REQUIRED)

# --- Dependency 2: nlohmann/json (single header) ---------------------------------------------
# Prefer a system/vendored copy if one is already discoverable; otherwise fetch the pinned single
# header at configure time. Fetching needs network; offline builds can instead drop json.hpp into an
# include dir and point the compiler at it (README.md "Option B").
find_package(nlohmann_json 3.11.0 QUIET)
if(NOT nlohmann_json_FOUND)
  include(FetchContent)
  FetchContent_Declare(
    nlohmann_json
    URL https://github.com/nlohmann/json/releases/download/v3.11.3/json.tar.xz
  )
  FetchContent_MakeAvailable(nlohmann_json)
endif()

# --- The one executable target (NO install target) -------------------------------------------
add_executable(example example.cpp optiquity_client.cpp)
target_link_libraries(example PRIVATE CURL::libcurl nlohmann_json::nlohmann_json)

# Run it (secret from env, never argv — see README.md):
#   OPTIQUITY_SHIM_URL=http://127.0.0.1:8787 OPTIQUITY_SHIM_SECRET=<secret> ./example
