#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstring>
#include "agp_build_profile.h"
#include "agp_parent_roles.h"
#include "agp_patch_runtime.h"
#include "agp_stub_builder.h"

namespace agp {
namespace {
using SetParent = void (*)(void*, void*);
SetParent set_father = nullptr, set_mother = nullptr;
using WriterBegin = void (*)(void*);
using WriterValue = void (*)(void*, std::uint32_t);
using ReaderId = void (*)(void*, std::uint32_t*);
WriterBegin writer_begin = nullptr;
WriterValue writer_token = nullptr, writer_id = nullptr;
ReaderId reader_id = nullptr;
template <typename T> T RoleRead(const void* object, std::size_t offset) {
    T value{};
    std::memcpy(&value, static_cast<const std::uint8_t*>(object) + offset, sizeof(value));
    return value;
}
extern "C" void WriteOrdinaryParents(void* writer, const void* family) {
    const auto& profile = Profile();
    const std::size_t offsets[] = {profile.offsets.father, profile.offsets.mother};
    const std::uint32_t tokens[] = {profile.parent_tokens.father, profile.parent_tokens.mother};
    for (std::size_t role = 0; role < 2; ++role) {
        const auto id = RoleRead<std::uint32_t>(family, offsets[role]);
        if (id == 0xffffffffU) continue;
        // Use the game's own persistent writer, including its binary-token
        // representation. Ordinary roles no longer depend on real-parent slots.
        writer_begin(writer);
        writer_token(writer, tokens[role]);
        writer_token(writer, 1); // equals
        writer_id(writer, id);
        writer_token(writer, 0x10); // newline
    }
}
extern "C" bool ReadOrdinaryParent(void* reader, void* family, std::uint32_t token) {
    const auto& profile = Profile();
    std::size_t offset{};
    if (token == profile.parent_tokens.father) offset = profile.offsets.father;
    else if (token == profile.parent_tokens.mother) offset = profile.offsets.mother;
    else return false;
    // Parsing precedes character reconstruction; store the serialized ID
    // without invoking setters or mutating reciprocal child lists here.
    reader_id(reader, reinterpret_cast<std::uint32_t*>(static_cast<std::uint8_t*>(family) + offset));
    return true;
}
extern "C" void ReconstructParentRole(void* child, void* parent) {
    const auto& offsets = Profile().offsets;
    const auto* family = RoleRead<const void*>(child, offsets.family_data);
    const auto id = RoleRead<std::uint32_t>(parent, offsets.character_id);
    bool father = RoleRead<std::uint8_t>(parent, offsets.gender) == 0;
    if (family) {
        // Some initialization paths already populated the ordinary role. Calling
        // its setter again would remove the child from the list being iterated.
        if (RoleRead<std::uint32_t>(family, offsets.father) == id ||
            RoleRead<std::uint32_t>(family, offsets.mother) == id) return;
        if (RoleRead<std::uint32_t>(family, offsets.real_father_override) == id) father = true;
        else if (RoleRead<std::uint32_t>(family, offsets.real_mother_override) == id) father = false;
    }
    (father ? set_father : set_mother)(child, parent);
}
}
std::vector<std::uint8_t> BuildParentPersistenceCode(bool father) {
    const auto& offsets = Profile().offsets;
    const auto marker = static_cast<std::uint8_t>(father ? offsets.real_father_override : offsets.real_mother_override);
    StubCode code;
    // r8 = family data, ecx = new parent ID, rdi = new parent, rax = old
    // parent. Preserve distinct real-parent overrides instead of replacing them.
    if (father) code.Emit({0x41,0x89,0x48,0x04}); else code.Emit({0x41,0x89,0x08});
    code.Emit({0x41,0x52});
    code.Emit({0x80,0xBF}); code.Value(static_cast<std::uint32_t>(offsets.gender)); code.Emit({0x00});
    code.Emit({static_cast<std::uint8_t>(father ? 0x74 : 0x75),0x00});
    const auto ordinary = code.bytes.size() - 1;
    code.Emit({0x41,0x83,0x78,marker,0xFF,0x74,0x00});
    const auto empty = code.bytes.size() - 1;
    code.Emit({0x48,0x85,0xC0,0x74,0x00});
    const auto no_old_parent = code.bytes.size() - 1;
    code.Emit({0x44,0x8B,0x50,static_cast<std::uint8_t>(offsets.character_id),0x45,0x39,0x50,marker,0x75,0x00});
    const auto distinct = code.bytes.size() - 1;
    const auto write_marker = code.bytes.size();
    code.Emit({0x41,0x89,0x48,marker});
    const auto resume = code.bytes.size();
    code.Emit({0x41,0x5A,0x48,0x8B,0xC8,0xE9,0,0,0,0});
    code.Branch8(ordinary, resume); code.Branch8(empty, write_marker);
    code.Branch8(no_old_parent, resume); code.Branch8(distinct, resume);
    return code.bytes;
}
bool StageParentPersistence(bool father) {
    auto* site = SiteAddress(father ? "father_persistence" : "mother_persistence");
    if (!site) return false;
    auto* stub = AllocateNear(site, 128);
    if (!stub) return false;
    const std::size_t overwritten = father ? 7 : 6;
    StubCode code;
    code.bytes = BuildParentPersistenceCode(father);
    if (!IsRel32Reachable(stub + code.bytes.size(), site + overwritten)) return false;
    if (!WriteBytes(stub, code.bytes.data(), code.bytes.size())) return false;
    WriteRel32(stub + code.bytes.size() - 4, site + overwritten);
    return StageDetour(site, stub, overwritten);
}
bool StageParentRoleReconstruction() {
    set_father = reinterpret_cast<SetParent>(ResolveProfileCall("set_father"));
    set_mother = reinterpret_cast<SetParent>(ResolveProfileCall("set_mother"));
    const auto* profile_site = Site("parent_reconstruction");
    auto* site = SiteAddress("parent_reconstruction");
    if (!set_father || !set_mother || !profile_site || !profile_site->resume_offset) return false;
    auto* stub = AllocateNear(site, 64);
    if (!stub) return false;
    StubCode code;
    // This 1.21 site keeps the child in rbx and the list's parent in rdi.
    // The containing function already aligns rsp for Win64 calls.
    code.Emit({0x48,0x8B,0xCB,0x48,0x8B,0xD7,0x48,0x83,0xEC,0x20});
    code.AbsoluteCall(reinterpret_cast<const void*>(&ReconstructParentRole));
    code.Emit({0x48,0x83,0xC4,0x20,0xE9,0,0,0,0});
    auto* resume = site + profile_site->resume_offset;
    if (!IsRel32Reachable(stub + code.bytes.size(), resume)) return false;
    if (!WriteBytes(stub, code.bytes.data(), code.bytes.size())) return false;
    WriteRel32(stub + code.bytes.size() - 4, resume);
    return StageDetour(site, stub, 7);
}
bool StageParentSerialization() {
    writer_begin = reinterpret_cast<WriterBegin>(ResolveProfileCall("writer_begin"));
    writer_token = reinterpret_cast<WriterValue>(ResolveProfileCall("writer_token"));
    writer_id = reinterpret_cast<WriterValue>(ResolveProfileCall("writer_id"));
    reader_id = reinterpret_cast<ReaderId>(ResolveProfileCall("reader_id"));
    auto* writer_site = SiteAddress("family_role_writer");
    auto* reader_site = SiteAddress("family_role_reader");
    auto* handled = SiteAddress("family_role_reader_handled");
    if (!writer_begin || !writer_token || !writer_id || !reader_id || !writer_site || !reader_site || !handled) return false;
    auto* write_stub = AllocateNear(writer_site, 96);
    auto* read_stub = AllocateNear(reader_site, 128);
    if (!write_stub || !read_stub) return false;
    StubCode write;
    // The writer keeps its persistent writer in rbx and family data in rsi.
    write.Emit({0x48,0x8B,0xCB,0x48,0x8B,0xD6,0x48,0x83,0xEC,0x20});
    write.AbsoluteCall(reinterpret_cast<const void*>(&WriteOrdinaryParents));
    write.Emit({0x48,0x83,0xC4,0x20});
    const auto original_write = ParseHex(Site("family_role_writer")->original);
    write.bytes.insert(write.bytes.end(), original_write.begin(), original_write.begin() + 6);
    write.Emit({0xE9,0,0,0,0});
    if (!IsRel32Reachable(write_stub + write.bytes.size(), writer_site + 6)) return false;
    if (!WriteBytes(write_stub, write.bytes.data(), write.bytes.size())) return false;
    WriteRel32(write_stub + write.bytes.size() - 4, writer_site + 6);

    StubCode read;
    const auto original_read = ParseHex(Site("family_role_reader")->original);
    read.bytes.insert(read.bytes.end(), original_read.begin(), original_read.begin() + 9);
    // Preserve the key and family pointer needed by the unhandled vanilla path.
    read.Emit({0x50,0x52,0x44,0x8B,0xC0,0x48,0x8B,0xCF,0x48,0x83,0xEC,0x20});
    read.AbsoluteCall(reinterpret_cast<const void*>(&ReadOrdinaryParent));
    read.Emit({0x48,0x83,0xC4,0x20,0x84,0xC0,0x5A,0x58,0x0F,0x85,0,0,0,0});
    const auto handled_immediate = read.bytes.size() - 4;
    read.Emit({0xE9,0,0,0,0});
    if (!IsRel32Reachable(read_stub + handled_immediate + 4, handled) ||
        !IsRel32Reachable(read_stub + read.bytes.size(), reader_site + 9)) return false;
    if (!WriteBytes(read_stub, read.bytes.data(), read.bytes.size())) return false;
    WriteRel32(read_stub + handled_immediate, handled);
    WriteRel32(read_stub + read.bytes.size() - 4, reader_site + 9);
    return StageDetour(writer_site, write_stub, 6) && StageDetour(reader_site, read_stub, 9);
}
}
