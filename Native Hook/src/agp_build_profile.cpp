#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <string>
#include "agp_build_profile.h"
#include "agp_patch_runtime.h"
#include "agp_profiles.generated.h"

namespace agp {
namespace {
const NativeProfile* selected = nullptr;
std::uint8_t* Base() { return reinterpret_cast<std::uint8_t*>(GetModuleHandleW(nullptr)); }
bool ExecutableHash(char (&output)[65]) {
    wchar_t path[32768]{};
    if (!GetModuleFileNameW(nullptr, path, 32768)) return false;
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    BCRYPT_HASH_HANDLE hash = nullptr;
    bool ok = BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0;
    if (ok) ok = BCryptCreateHash(algorithm, &hash, nullptr, 0, nullptr, 0, 0) >= 0;
    std::array<UCHAR, 65536> buffer{};
    DWORD count = 0;
    while (ok) {
        if (!ReadFile(file, buffer.data(), static_cast<DWORD>(buffer.size()), &count, nullptr)) { ok = false; break; }
        if (!count) break;
        ok = BCryptHashData(hash, buffer.data(), count, 0) >= 0;
    }
    std::array<UCHAR, 32> digest{};
    if (ok) ok = BCryptFinishHash(hash, digest.data(), static_cast<ULONG>(digest.size()), 0) >= 0;
    if (hash) BCryptDestroyHash(hash);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    CloseHandle(file);
    if (ok) for (std::size_t i = 0; i < digest.size(); ++i) std::sprintf(output + i * 2, "%02x", digest[i]);
    return ok;
}
bool InText(const TextSection& text, const std::uint8_t* pointer, std::size_t count) {
    return pointer >= text.begin && pointer <= text.begin + text.size && count <= static_cast<std::size_t>(text.begin + text.size - pointer);
}
}
std::vector<std::uint8_t> ParseHex(const char* text) {
    std::vector<std::uint8_t> bytes;
    while (*text) {
        while (*text == ' ') ++text;
        if (!*text) break;
        char* end = nullptr;
        const auto value = std::strtoul(text, &end, 16);
        if (end == text || value > 255) return {};
        bytes.push_back(static_cast<std::uint8_t>(value));
        text = end;
    }
    return bytes;
}
const NativeProfile& Profile() { return *selected; }
const NativeSite* Site(const char* id) {
    if (selected) for (std::size_t i = 0; i < selected->site_count; ++i)
        if (std::strcmp(selected->sites[i].id, id) == 0) return &selected->sites[i];
    return nullptr;
}
std::uint8_t* SiteAddress(const char* id) {
    const auto* site = Site(id);
    return site ? Base() + site->rva : nullptr;
}
std::uint8_t* ResolveProfileCall(const char* id) {
    if (selected) for (std::size_t i = 0; i < selected->call_count; ++i) {
        const auto& call = selected->calls[i];
        if (std::strcmp(call.id, id) != 0) continue;
        auto* instruction = Base() + call.call_rva;
        std::int32_t delta{};
        std::memcpy(&delta, instruction + 1, sizeof(delta));
        return instruction[0] == 0xE8 ? instruction + 5 + delta : nullptr;
    }
    return nullptr;
}
bool SelectAndValidateProfile() {
    selected = nullptr;
    char hash[65]{};
    if (!ExecutableHash(hash)) { Log("AGP v1.1.0: executable hashing failed; no changes made."); return false; }
    Log("AGP v1.1.0: starting executable/profile preflight.");
    Log(hash);
    for (const auto& profile : kProfiles) if (std::strcmp(hash, profile.executable_sha256) == 0) {
        if (selected) { Log("AGP: ambiguous executable profile; no changes made."); return false; }
        selected = &profile;
    }
    if (!selected) { Log("AGP: unsupported executable hash; no changes made."); return false; }
    Log(selected->id);
    Log(selected->distribution);
    TextSection text{};
    if (!GetTextSection(&text)) return false;
    for (std::size_t i = 0; i < selected->site_count; ++i) {
        const auto& site = selected->sites[i];
        const auto bytes = ParseHex(site.original);
        auto* address = Base() + site.rva;
        if (bytes.empty() || !InText(text, address, bytes.size()) || std::memcmp(address, bytes.data(), bytes.size())) {
            Log(site.id); Log("AGP: patch-site preflight failed; no changes made."); return false;
        }
        const std::string mask(bytes.size(), 'x');
        if (FindPattern(text, bytes.data(), mask.c_str(), bytes.size()).size() != 1) {
            Log(site.id); Log("AGP: patch-site uniqueness failed; no changes made."); return false;
        }
        Log(site.id);
    }
    for (std::size_t i = 0; i < selected->call_count; ++i) {
        const auto& call = selected->calls[i];
        if (!InText(text, Base() + call.call_rva, 5)) return false;
        auto* target = ResolveProfileCall(call.id);
        const auto bytes = ParseHex(call.prologue);
        if (target != Base() + call.target_rva || !InText(text, target, bytes.size()) || std::memcmp(target, bytes.data(), bytes.size())) {
            Log(call.id); Log("AGP: call-target preflight failed; no changes made."); return false;
        }
    }
    return true;
}
bool StageModulePatches(const char* module) {
    for (std::size_t i = 0; i < Profile().site_count; ++i) {
        const auto& site = Profile().sites[i];
        if (std::strcmp(site.module, module)) continue;
        auto* address = Base() + site.rva + site.patch_offset;
        if (!std::strcmp(site.kind, "bytes")) {
            const auto bytes = ParseHex(site.replacement);
            if (bytes.empty() || !WriteBytes(address, bytes.data(), bytes.size())) return false;
        } else if (!std::strcmp(site.kind, "near_jump")) {
            if (!PatchNearConditionalToUnconditional(address)) return false;
        }
    }
    return true;
}
}
