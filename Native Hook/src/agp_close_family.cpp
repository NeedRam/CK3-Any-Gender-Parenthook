#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstring>
#include "agp_build_profile.h"
#include "agp_close_family.h"
#include "agp_patch_runtime.h"
#include "agp_stub_builder.h"

namespace agp {
namespace {
template <typename T> T FamilyRead(const void* object, std::size_t offset) {
    T value{};
    std::memcpy(&value, static_cast<const std::uint8_t*>(object) + offset, sizeof(value));
    return value;
}
bool HasParent(const void* character, std::uint32_t id) {
    if (!character) return false;
    const auto* family = FamilyRead<const void*>(character, Profile().offsets.family_data);
    return family && (FamilyRead<std::uint32_t>(family, Profile().offsets.father) == id ||
        FamilyRead<std::uint32_t>(family, Profile().offsets.mother) == id);
}
extern "C" bool CloseFamilyParentOrGrandparent(const void* relative, const void* first, const void* second) {
    if (!relative) return false;
    const auto id = FamilyRead<std::uint32_t>(relative, Profile().offsets.character_id);
    if (id == 0xffffffffU) return false;
    return relative == first || relative == second || HasParent(first, id) || HasParent(second, id);
}
}
bool StageCloseFamilyPatch() {
    auto* helper = SiteAddress("close_family");
    if (!helper) return false;
    auto* relay = AllocateNear(helper, 64);
    if (!relay) return false;
    StubCode code;
    // The caller keeps both r10 and r11 live across the original leaf helper.
    code.Emit({0x41,0x52,0x41,0x53,0x48,0x83,0xEC,0x28});
    code.AbsoluteCall(reinterpret_cast<const void*>(&CloseFamilyParentOrGrandparent));
    code.Emit({0x48,0x83,0xC4,0x28,0x41,0x5B,0x41,0x5A,0xC3});
    return WriteBytes(relay, code.bytes.data(), code.bytes.size()) && StageDetour(helper, relay, 7);
}
}
