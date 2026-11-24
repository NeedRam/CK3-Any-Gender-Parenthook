#pragma once
#include <cstddef>
#include <cstdint>
#include <vector>

namespace agp {
struct NativeSite {
    const char* id;
    const char* module;
    const char* kind;
    std::uintptr_t rva;
    const char* original;
    std::size_t patch_offset;
    const char* replacement;
    std::size_t resume_offset;
};
struct NativeCall {
    const char* id;
    std::uintptr_t call_rva;
    std::uintptr_t target_rva;
    const char* prologue;
};
struct CharacterOffsets {
    std::size_t character_id, gender, family_data, mother, father, real_father_override, real_mother_override;
};
struct NativeProfile {
    const char* id;
    const char* distribution;
    const char* executable_sha256;
    CharacterOffsets offsets;
    struct { std::uint32_t father, mother; } parent_tokens;
    const NativeSite* sites;
    std::size_t site_count;
    const NativeCall* calls;
    std::size_t call_count;
};
const NativeProfile& Profile();
bool SelectAndValidateProfile();
const NativeSite* Site(const char* id);
std::uint8_t* SiteAddress(const char* id);
std::uint8_t* ResolveProfileCall(const char* id);
bool StageModulePatches(const char* module);
std::vector<std::uint8_t> ParseHex(const char* text);
}
