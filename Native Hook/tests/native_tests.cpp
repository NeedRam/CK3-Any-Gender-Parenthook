#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <array>
#include <cassert>
#include <cstdio>
#include <cstring>
// One test translation unit exposes the private callbacks without exporting a
// test interface from the production DLL.
#include "../src/agp_build_profile.cpp"
#include "../src/agp_parent_roles.cpp"
#include "../src/agp_close_family.cpp"

namespace {
template <typename T> void Put(void* object, std::size_t offset, T value) {
    std::memcpy(static_cast<std::uint8_t*>(object) + offset, &value, sizeof(value));
}
struct Character {
    std::array<std::uint8_t, 512> data{};
    std::array<std::uint8_t, 96> family{};
    Character(std::uint32_t id, bool female) {
        const auto& o = agp::Profile().offsets;
        std::memset(family.data(), 0xff, 16);
        Put(data.data(), o.family_data, family.data());
        Put(data.data(), o.character_id, id);
        Put(data.data(), o.gender, static_cast<std::uint8_t>(female));
    }
};
bool father_called = false, mother_called = false;
void Father(void*, void*) { father_called = true; }
void Mother(void*, void*) { mother_called = true; }
std::vector<std::uint32_t> serialized;
void BeginField(void*) { serialized.push_back(0xfffffffeU); }
void WriteValue(void*, std::uint32_t value) { serialized.push_back(value); }
void ReadValue(void* source, std::uint32_t* destination) { *destination = *static_cast<std::uint32_t*>(source); }

void TestSerializedRoles() {
    Character child(30, true);
    const auto& profile = agp::Profile();
    Put(child.family.data(), profile.offsets.father, std::uint32_t{41});
    Put(child.family.data(), profile.offsets.mother, std::uint32_t{42});
    Put(child.family.data(), profile.offsets.real_father_override, std::uint32_t{43});
    Put(child.family.data(), profile.offsets.real_mother_override, std::uint32_t{44});
    agp::writer_begin = &BeginField;
    agp::writer_token = agp::writer_id = &WriteValue;
    agp::reader_id = &ReadValue;
    agp::WriteOrdinaryParents(nullptr, child.family.data());
    const std::vector<std::uint32_t> expected{0xfffffffeU,profile.parent_tokens.father,1,41,16,
        0xfffffffeU,profile.parent_tokens.mother,1,42,16};
    assert(serialized == expected);
    std::uint32_t value = 45;
    assert(!agp::ReadOrdinaryParent(&value,child.family.data(),0xffffffffU));
    assert(agp::ReadOrdinaryParent(&value,child.family.data(),profile.parent_tokens.father));
    value = 46;
    assert(agp::ReadOrdinaryParent(&value,child.family.data(),profile.parent_tokens.mother));
    assert(agp::RoleRead<std::uint32_t>(child.family.data(),profile.offsets.father) == 45);
    assert(agp::RoleRead<std::uint32_t>(child.family.data(),profile.offsets.mother) == 46);
    assert(agp::RoleRead<std::uint32_t>(child.family.data(),profile.offsets.real_father_override) == 43);
    assert(agp::RoleRead<std::uint32_t>(child.family.data(),profile.offsets.real_mother_override) == 44);
    std::memset(child.family.data(),0xff,16);
    serialized.clear();
    agp::WriteOrdinaryParents(nullptr,child.family.data());
    assert(serialized.empty());
}

void TestRoleAndFamily() {
    const auto& o = agp::Profile().offsets;
    Character child(11, false), father(12, true), mother(13, false), grandparent(14, false), unrelated(15, true);
    agp::set_father = &Father; agp::set_mother = &Mother;
    Put(child.family.data(), o.real_father_override, std::uint32_t{12});
    Put(child.family.data(), o.real_mother_override, std::uint32_t{13});
    agp::ReconstructParentRole(child.data.data(), father.data.data());
    assert(father_called && !mother_called);
    father_called = mother_called = false;
    agp::ReconstructParentRole(child.data.data(), mother.data.data());
    assert(mother_called && !father_called);
    father_called = mother_called = false;
    Put(child.family.data(), o.father, std::uint32_t{12});
    agp::ReconstructParentRole(child.data.data(), father.data.data());
    assert(!father_called && !mother_called);
    Put(father.family.data(), o.mother, std::uint32_t{14});
    assert(agp::CloseFamilyParentOrGrandparent(father.data.data(), father.data.data(), mother.data.data()));
    assert(agp::CloseFamilyParentOrGrandparent(grandparent.data.data(), father.data.data(), mother.data.data()));
    assert(!agp::CloseFamilyParentOrGrandparent(unrelated.data.data(), father.data.data(), mother.data.data()));
    assert(!agp::CloseFamilyParentOrGrandparent(nullptr, nullptr, nullptr));
}

void TestActualPersistenceInstructions() {
    const auto& o = agp::Profile().offsets;
    for (const bool father : {false, true}) {
        for (const bool opposite_gender : {false, true}) {
            for (const std::uint32_t existing : {0xffffffffU, 20U, 99U}) {
              for (const bool has_old_parent : {false, true}) {
                Character parent(21, father == opposite_gender), old_parent(20, false);
                std::array<std::uint32_t, 8> family{};
                const auto marker = father ? o.real_father_override : o.real_mother_override;
                family[marker / 4] = existing;
                // Adapt the Win64 C++ arguments to the registers at the real
                // setter site, then execute the exact production emitter output.
                agp::StubCode wrapper;
                wrapper.Emit({0x57,0x49,0x8B,0xC0,0x4C,0x8B,0xC1,0x48,0x8B,0xFA,0x8B,0x4F,0x18});
                auto code = agp::BuildParentPersistenceCode(father);
                wrapper.bytes.insert(wrapper.bytes.end(), code.begin(), code.end());
                wrapper.Emit({0x5F,0xC3}); // final rel32 jump has zero displacement
                auto* executable = static_cast<std::uint8_t*>(VirtualAlloc(nullptr, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
                assert(executable);
                std::memcpy(executable, wrapper.bytes.data(), wrapper.bytes.size());
                DWORD protection{};
                assert(VirtualProtect(executable,4096,PAGE_EXECUTE_READ,&protection));
                FlushInstructionCache(GetCurrentProcess(),executable,wrapper.bytes.size());
                using Function = void* (*)(void*,void*,void*);
                void* old = has_old_parent ? old_parent.data.data() : nullptr;
                auto* returned = reinterpret_cast<Function>(executable)(family.data(),parent.data.data(),old);
                assert(returned == old);
                assert(family[(father ? o.father : o.mother) / 4] == 21);
                const auto expected = opposite_gender && (existing == 0xffffffffU || (has_old_parent && existing == 20)) ? 21U : existing;
                assert(family[marker / 4] == expected);
                VirtualFree(executable,0,MEM_RELEASE);
              }
            }
        }
    }
}

void TestTransaction() {
    auto* memory = static_cast<std::uint8_t*>(VirtualAlloc(nullptr,4096,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE));
    assert(memory);
    const std::uint8_t first[] = {1,2,3,4}, second[] = {9,8};
    for (std::size_t failure = 0; failure < 3; ++failure) {
        std::memset(memory,0x7a,16);
        agp::BeginPatchTransaction();
        assert(agp::WriteBytes(memory,first,sizeof(first)));
        assert(agp::WriteBytes(memory+1,second,sizeof(second)));
        assert(memory[0] == 0x7a && memory[1] == 0x7a);
        const bool committed = agp::CommitPatchTransaction(failure);
        if (failure < 2) {
            assert(!committed);
            for (std::size_t i=0;i<16;++i) assert(memory[i] == 0x7a);
        } else assert(committed && memory[0] == 1 && memory[1] == 9 && memory[2] == 8 && memory[3] == 4);
    }
    agp::BeginPatchTransaction();
    assert(agp::WriteBytes(memory,second,sizeof(second)));
    agp::AbortPatchTransaction();
    assert(memory[0] == 1);
    VirtualFree(memory,0,MEM_RELEASE);
}
}
int main() {
    agp::selected = &agp::kProfiles[0];
    TestRoleAndFamily();
    TestSerializedRoles();
    TestActualPersistenceInstructions();
    TestTransaction();
    assert(!agp::SelectAndValidateProfile()); // this test executable is unsupported
    std::puts("PASS: role serialization, role callbacks, family negatives, 24 emitted-stub cases, staged writes, abort, rollback, unknown executable.");
    return 0;
}
