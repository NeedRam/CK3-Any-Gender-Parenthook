#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include "agp_close_family.h"

#include <cstring>

namespace agp {
namespace {

constexpr std::size_t kCharacterIdOffset = 0x18;
constexpr std::size_t kFamilyDataOffset = 0x1a0;
constexpr std::size_t kFatherIdOffset = 0x00;
constexpr std::size_t kMotherIdOffset = 0x04;
constexpr std::uint32_t kInvalidCharacterId = 0xffffffffU;

const std::uint8_t close_family_helper[] = {
	0x80, 0xB9, 0x99, 0x01, 0x00, 0x00, 0x00,
	0x4C, 0x8B, 0xC9,
	0x74, 0x3D,
	0x4C, 0x3B, 0xC1,
	0x74, 0x35,
	0x49, 0x8B, 0x88, 0xA0, 0x01, 0x00, 0x00,
	0xB8, 0xFF, 0xFF, 0xFF, 0xFF
};
const char close_family_helper_mask[] = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxx";

template <typename T>
T ReadAt(const void* object, std::size_t offset) {
	T value{};
	std::memcpy(&value, static_cast<const std::uint8_t*>(object) + offset, sizeof(value));
	return value;
}

std::uint32_t ParentId(const void* character, std::size_t slot_offset) {
	if (character == nullptr) {
		return kInvalidCharacterId;
	}
	const auto* family_data = ReadAt<const void*>(character, kFamilyDataOffset);
	if (family_data == nullptr) {
		return kInvalidCharacterId;
	}
	return ReadAt<std::uint32_t>(family_data, slot_offset);
}

bool HasParentId(const void* character, std::uint32_t sought_id) {
	return ParentId(character, kFatherIdOffset) == sought_id ||
		ParentId(character, kMotherIdOffset) == sought_id;
}

extern "C" bool CloseFamilyParentOrGrandparent(
	const void* relative,
	const void* first_parent,
	const void* second_parent) {
	// Vanilla selects one parent slot from the relative's sex. AGP parent roles
	// are explicit, so both native slots must participate in family recognition.
	if (relative == first_parent || relative == second_parent) {
		return true;
	}
	if (relative == nullptr) {
		return false;
	}
	const auto relative_id = ReadAt<std::uint32_t>(relative, kCharacterIdOffset);
	return HasParentId(first_parent, relative_id) || HasParentId(second_parent, relative_id);
}

bool InstallCloseFamilyDetour(std::uint8_t* helper) {
	// CK3's caller keeps a live parent pointer in r11 for its later sibling
	// checks because the original leaf helper does not clobber it. A normal C++
	// function may use volatile r11, so preserve it and provide Win64 shadow space.
	auto* const relay = AllocateNear(helper, 32);
	if (relay == nullptr || !IsRel32Reachable(helper + 5, relay)) {
		return false;
	}

	std::uint8_t relay_code[] = {
		0x41, 0x53,
		0x48, 0x83, 0xEC, 0x20,
		0x48, 0xB8,
		0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
		0xFF, 0xD0,
		0x48, 0x83, 0xC4, 0x20,
		0x41, 0x5B,
		0xC3
	};
	const auto replacement = reinterpret_cast<std::uintptr_t>(&CloseFamilyParentOrGrandparent);
	std::memcpy(relay_code + 8, &replacement, sizeof(replacement));
	if (!WriteBytes(relay, relay_code, sizeof(relay_code))) {
		return false;
	}

	std::uint8_t detour[] = { 0xE9, 0x00, 0x00, 0x00, 0x00, 0x90, 0x90 };
	const auto displacement = static_cast<std::int32_t>(relay - (helper + 5));
	std::memcpy(detour + 1, &displacement, sizeof(displacement));
	return WriteBytes(helper, detour, sizeof(detour));
}

} // namespace

bool PrepareCloseFamilyPatch(const TextSection& text, CloseFamilyPatchPlan* plan) {
	const auto matches = FindPattern(text, close_family_helper, close_family_helper_mask, sizeof(close_family_helper));
	if (matches.size() != 1) {
		Log("AGP Close Family: helper signature mismatch; no changes made.");
		return false;
	}
	plan->helper = matches[0];
	return true;
}

bool ApplyCloseFamilyPatch(const CloseFamilyPatchPlan& plan) {
	if (!InstallCloseFamilyDetour(plan.helper)) {
		Log("AGP Close Family: unable to install gender-neutral parent-role helper.");
		return false;
	}
	Log("AGP Close Family: native parent and grandparent recognition now uses both stored parent roles.");
	return true;
}

} // namespace agp
